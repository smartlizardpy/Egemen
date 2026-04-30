"""
Turkish people scraper — fast concurrent version.

Speedups vs original:
  - ThreadPoolExecutor fetches multiple categories and extract batches in parallel
  - No sleep() between requests — the pool's concurrency provides natural spacing
  - Single shared requests.Session with connection pooling
  - News name lookups also parallelised (search + extract in one shot)

Two sources → data/people.txt:
  1. Wikipedia category crawler (35 seed categories, depth-2 recursion)
  2. News name extractor (regex → Wikipedia lookup for names found in news files)
"""

import re
import time
import threading
import requests
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_FILE = Path(__file__).parent / "data" / "people.txt"
NEWS_DIR    = Path(__file__).parent / "data" / "news"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

API     = "https://tr.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "TurkishSLMScraper/1.0 (research; remzi.kaygusuz@durham.ac.uk)"}

WORKERS               = 4    # conservative — avoids 429s from Wikipedia
MAX_PAGES_PER_CATEGORY = 500
MAX_SUBCATEGORY_DEPTH  = 2
EXTRACT_BATCH_SIZE     = 50  # Wikipedia API max per request

# rate limiter: max N requests per second across all threads
_rate_sem   = threading.Semaphore(WORKERS)
_rate_delay = 0.25  # seconds between each request slot release

SEED_CATEGORIES = [
    "Kategori:Türk politikacılar",
    "Kategori:Türk sporcular",
    "Kategori:Türk yazarlar",
    "Kategori:Türk şairler",
    "Kategori:Türk aktörler",
    "Kategori:Türk müzisyenler",
    "Kategori:Türk yönetmenler",
    "Kategori:Türk bilim insanları",
    "Kategori:Türk iş insanları",
    "Kategori:Türk gazeteciler",
    "Kategori:Türk mimarlar",
    "Kategori:Türk hukukçular",
    "Kategori:Türk askerler",
    "Kategori:Türk filozoflar",
    "Kategori:Türk tarihçiler",
    "Kategori:Türk ekonomistler",
    "Kategori:Türk mühendisler",
    "Kategori:Türk ressam",
    "Kategori:Türk fotoğrafçılar",
    "Kategori:Türk futbolcular",
    "Kategori:Türk basketbolcular",
    "Kategori:Türk tenisçiler",
    "Kategori:Türk boksörler",
    "Kategori:Türk güreşçiler",
    "Kategori:Türk komedyenler",
    "Kategori:Türk sunucular",
    "Kategori:Türk model",
    "Kategori:Türk tiyatro oyuncuları",
    "Kategori:Türk dizi oyuncuları",
    "Kategori:Türk siyasetçiler",
    "Kategori:Osmanlı padişahları",
    "Kategori:Osmanlı sadrazamları",
    "Kategori:Osmanlı bilim insanları",
    "Kategori:Amerikalı politikacılar",
    "Kategori:Alman politikacılar",
    "Kategori:Nobel ödüllüler",
]


# ── shared session with connection pooling ────────────────────────────────────

_session_local = threading.local()

def get_session() -> requests.Session:
    """One session per thread — avoids lock contention on the shared connection pool."""
    if not hasattr(_session_local, "session"):
        s = requests.Session()
        s.headers.update(HEADERS)
        _session_local.session = s
    return _session_local.session


def api_get(params: dict) -> dict:
    """Rate-limited API call with exponential backoff on 429."""
    _rate_sem.acquire()
    try:
        for attempt in range(5):
            r = get_session().get(API, params={**params, "format": "json"}, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
    finally:
        threading.Timer(_rate_delay, _rate_sem.release).start()


# ── category page collection ──────────────────────────────────────────────────

def _fetch_category_pages_flat(category: str) -> set[str]:
    """Fetch all page titles in one category (no recursion), handling pagination."""
    titles: set[str] = set()
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "page",
        "cmlimit": 500,
    }
    cont: dict = {}
    while len(titles) < MAX_PAGES_PER_CATEGORY:
        data = api_get({**params, **cont})
        for m in data["query"]["categorymembers"]:
            titles.add(m["title"])
        if "continue" not in data:
            break
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}
    return titles


def _fetch_subcategories(category: str) -> list[str]:
    data = api_get({
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "subcat",
        "cmlimit": 50,
        "format": "json",
    })
    return [m["title"] for m in data["query"]["categorymembers"]]


def collect_all_titles(seed_categories: list[str]) -> set[str]:
    """
    Parallel category fetch:
      - All seed categories fetched concurrently
      - Their subcategories fetched concurrently (up to depth 2)
    """
    all_titles: set[str] = set()
    lock = threading.Lock()

    def fetch_one(cat: str) -> tuple[str, set[str]]:
        return cat, _fetch_category_pages_flat(cat)

    # depth 0 — seed categories
    print(f"Fetching {len(seed_categories)} seed categories...")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, cat): cat for cat in seed_categories}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="cat", desc="Seed cats"):
            _, titles = fut.result()
            with lock:
                all_titles.update(titles)

    # depth 1 — subcategories
    print(f"Fetching subcategories...")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        sub_futures = {pool.submit(_fetch_subcategories, cat): cat for cat in seed_categories}
        subcats: list[str] = []
        for fut in tqdm(as_completed(sub_futures), total=len(sub_futures), unit="cat", desc="Subcats"):
            subcats.extend(fut.result())
    subcats = list(set(subcats))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, cat): cat for cat in subcats}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="cat", desc="Depth-1"):
            _, titles = fut.result()
            with lock:
                all_titles.update(titles)

    # depth 2 — sub-subcategories
    print("Fetching sub-subcategories...")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        sub2_futures = {pool.submit(_fetch_subcategories, cat): cat for cat in subcats}
        subcats2: list[str] = []
        for fut in as_completed(sub2_futures):
            subcats2.extend(fut.result())
    subcats2 = list(set(subcats2) - set(subcats))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, cat): cat for cat in subcats2}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="cat", desc="Depth-2"):
            _, titles = fut.result()
            with lock:
                all_titles.update(titles)

    return all_titles


# ── article text extraction ───────────────────────────────────────────────────

def _fetch_extract_batch(titles: list[str]) -> dict[str, str]:
    """Fetch plain-text extracts for up to 50 titles in one API call."""
    data = api_get({
        "action": "query",
        "titles": "|".join(titles),
        "prop": "extracts|categories",
        "explaintext": True,
        "exsectionformat": "plain",
        "exintro": False,
        "cllimit": 5,
    })
    results = {}
    for page in data["query"]["pages"].values():
        title = page.get("title", "")
        text  = page.get("extract", "").strip()
        cats  = [c["title"] for c in page.get("categories", [])]
        if any("anlam ayrım" in c.lower() or "listesi" in c.lower() for c in cats):
            continue
        if text and len(text) > 100:
            results[title] = text
    return results


def fetch_all_extracts(titles: list[str]) -> dict[str, str]:
    """Parallel extract fetching — splits into 50-title batches, fetches concurrently."""
    batches = [titles[i : i + EXTRACT_BATCH_SIZE] for i in range(0, len(titles), EXTRACT_BATCH_SIZE)]
    results: dict[str, str] = {}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_fetch_extract_batch, batch): batch for batch in batches}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="batch", desc="Extracts"):
            batch_results = fut.result()
            with lock:
                results.update(batch_results)

    return results


def is_person_page(title: str, text: str) -> bool:
    skip = ("listesi", "kategorisi", "şablonu", "taslak", "portal")
    if any(s in title.lower() for s in skip):
        return False
    if re.search(r"\b(doğdu|öldü|\d{4}–\d{4}|\d{4} doğumlu)", text):
        return True
    return len(text) > 300


# ── Part 2: names from news ───────────────────────────────────────────────────

_NOISE_CAPS = {
    "Türkiye", "İstanbul", "Ankara", "İzmir", "Avrupa", "Amerika",
    "Cumhurbaşkanı", "Başbakan", "Bakan", "Meclis", "TBMM", "AB",
    "ABD", "NATO", "BM", "IMF", "TRT", "BBC", "NTV", "CNN",
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
}

_NAME_RE = re.compile(
    r"\b([A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,20})"
    r"(?:\s+([A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,20})){1,3}\b"
)


def extract_names_from_text(text: str) -> set[str]:
    names = set()
    for m in _NAME_RE.finditer(text):
        candidate = m.group(0)
        parts = candidate.split()
        if any(p in _NOISE_CAPS for p in parts) or len(parts) < 2:
            continue
        names.add(candidate)
    return names


def extract_names_from_news() -> set[str]:
    if not NEWS_DIR.exists():
        return set()
    files = list(NEWS_DIR.rglob("*.txt"))
    print(f"\nExtracting names from {len(files)} news files...")
    all_names: set[str] = set()
    for path in tqdm(files, unit="file"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        all_names.update(extract_names_from_text(text))
    print(f"Found {len(all_names)} candidate names")
    return all_names


def _lookup_name(name: str) -> tuple[str, str] | None:
    """Search Wikipedia for a name, return (title, extract) or None."""
    try:
        data = api_get({
            "action": "query",
            "list": "search",
            "srsearch": name,
            "srnamespace": 0,
            "srlimit": 1,
        })
        results = data["query"].get("search", [])
        if not results:
            return None
        title = results[0]["title"]
        batch = _fetch_extract_batch([title])
        if title in batch and is_person_page(title, batch[title]):
            return title, batch[title]
    except Exception:
        pass
    return None


def lookup_news_names(
    names: set[str], known_titles: set[str]
) -> dict[str, str]:
    """Parallel Wikipedia lookup for names found in news, up to 2000."""
    candidates = [n for n in names if n.lower() not in known_titles][:2000]
    print(f"Looking up {len(candidates)} new names in parallel...")

    found: dict[str, str] = {}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_lookup_name, name): name for name in candidates}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="name", desc="News lookups"):
            result = fut.result()
            if result:
                title, text = result
                with lock:
                    found[title] = text

    return found


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    # Part 1 — Wikipedia categories
    print("=== Part 1: Wikipedia category crawl ===")
    all_titles = collect_all_titles(SEED_CATEGORIES)
    print(f"Total unique titles: {len(all_titles)}")

    print(f"\nFetching article text for {len(all_titles)} pages...")
    extracts = fetch_all_extracts(list(all_titles))

    all_people = {t: x for t, x in extracts.items() if is_person_page(t, x)}
    print(f"Kept {len(all_people)} person articles")

    # Part 2 — names from news
    print("\n=== Part 2: Person names from news articles ===")
    news_names = extract_names_from_news()
    known = {t.lower() for t in all_people}
    news_people = lookup_news_names(news_names, known)
    all_people.update(news_people)
    print(f"Added {len(news_people)} more people from news")

    # Write output
    print(f"\nWriting {len(all_people)} people → {OUTPUT_FILE}")
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        for title, text in sorted(all_people.items()):
            f.write(f"=== {title} ===\n{text}\n---\n\n")

    size_mb = OUTPUT_FILE.stat().st_size / 1_000_000
    print(f"Done. {len(all_people)} people, {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
