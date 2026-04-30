"""
Turkish news scraper — 8 sites, RSS-driven + category crawl for volume.

Sources (all verified working):
  BBC Türkçe, TRT Haber, Anadolu Ajansı, CNN Türk,
  Hürriyet, NTV, Sözcü, Cumhuriyet

Strategy:
  1. Parse RSS feed → seed article URLs (always fresh)
  2. Crawl category / tag pages to discover more article URLs
  3. Scrape full article text from each URL via broad <p> selection
  4. Save one .txt per article in data/news/<site>/
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from tqdm import tqdm
from urllib.parse import urljoin, urlparse

OUTPUT_DIR = Path(__file__).parent / "data" / "news"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
DELAY = 1.0          # seconds between requests
MIN_PARA_LEN = 40    # chars — shorter paragraphs are nav/caption noise
MIN_ARTICLE_LEN = 200  # chars total

# ── site configs ──────────────────────────────────────────────────────────────
# rss:          RSS/Atom feed URL (reliable seed)
# category_urls: extra pages to crawl for more article links
# article_re:   regex that article URLs must match
# skip_re:      regex to reject non-article URLs

SITES: dict[str, dict] = {
    "bbc": {
        "rss": "https://feeds.bbci.co.uk/turkce/rss.xml",
        "category_urls": [
            "https://www.bbc.com/turkce",
            "https://www.bbc.com/turkce/topics/c340zp0l9let",  # türkiye
            "https://www.bbc.com/turkce/topics/c06g4k0zp74t",  # dünya
        ],
        "article_re": r"bbc\.com/turkce/articles/",
        "skip_re": r"(#|/live|/sport|/weather)",
    },
    "trt": {
        "rss": "https://www.trthaber.com/sondakika.rss",
        "category_urls": [
            "https://www.trthaber.com/",
            "https://www.trthaber.com/haber/dunya/",
            "https://www.trthaber.com/haber/turkiye/",
            "https://www.trthaber.com/haber/ekonomi/",
            "https://www.trthaber.com/haber/spor/",
            "https://www.trthaber.com/haber/kultur-sanat/",
        ],
        "article_re": r"trthaber\.com/haber/.+\.html",
        "skip_re": r"(#|/fotogaleri/|/video/)",
    },
    "aa": {
        "rss": "https://www.aa.com.tr/tr/rss/default?cat=guncel",
        "category_urls": [
            "https://www.aa.com.tr/tr/guncel",
            "https://www.aa.com.tr/tr/dunya",
            "https://www.aa.com.tr/tr/ekonomi",
            "https://www.aa.com.tr/tr/spor",
            "https://www.aa.com.tr/tr/politika",
        ],
        "article_re": r"aa\.com\.tr/tr/[^/]+/[^/]+-/\d+",
        "skip_re": r"(#|/foto-galeri/|/video/|/infografik/)",
    },
    "cnnturk": {
        "rss": "https://www.cnnturk.com/feed/rss/news",
        "category_urls": [
            "https://www.cnnturk.com/turkiye",
            "https://www.cnnturk.com/dunya",
            "https://www.cnnturk.com/ekonomi",
            "https://www.cnnturk.com/spor",
            "https://www.cnnturk.com/yasam",
        ],
        "article_re": r"cnnturk\.com/(?!video|foto|canli)",
        "skip_re": r"(#|/video/|/foto/|/canli)",
    },
    "hurriyet": {
        "rss": "https://www.hurriyet.com.tr/rss/anasayfa",
        "category_urls": [
            "https://www.hurriyet.com.tr/gundem/",
            "https://www.hurriyet.com.tr/ekonomi/",
            "https://www.hurriyet.com.tr/dunya/",
            "https://www.hurriyet.com.tr/sporarena/",
            "https://www.hurriyet.com.tr/teknoloji/",
        ],
        "article_re": r"hurriyet\.com\.tr/[^/]+/\d+",
        "skip_re": r"(#|/foto/|/video/|/etiket/)",
    },
    "ntv": {
        "rss": "https://www.ntv.com.tr/son-dakika.rss",
        "category_urls": [
            "https://www.ntv.com.tr/turkiye",
            "https://www.ntv.com.tr/dunya",
            "https://www.ntv.com.tr/ekonomi",
            "https://www.ntv.com.tr/spor",
            "https://www.ntv.com.tr/saglik",
            "https://www.ntv.com.tr/teknoloji",
        ],
        "article_re": r"ntv\.com\.tr/[^/]+/[^/]+-\d+",
        "skip_re": r"(#|/video/|/fotogaleri/|/canli/)",
    },
    "sozcu": {
        "rss": "https://www.sozcu.com.tr/rss/",
        "category_urls": [
            "https://www.sozcu.com.tr/",
            "https://www.sozcu.com.tr/gundem/",
            "https://www.sozcu.com.tr/dunya/",
            "https://www.sozcu.com.tr/ekonomi/",
            "https://www.sozcu.com.tr/spor/",
            "https://www.sozcu.com.tr/yasam/",
        ],
        "article_re": r"sozcu\.com\.tr/[^/]+-p\d+",
        "skip_re": r"(#|/foto/|/video/|/etiket/|/category/)",
    },
    "cumhuriyet": {
        "rss": "https://www.cumhuriyet.com.tr/rss",
        "category_urls": [
            "https://www.cumhuriyet.com.tr/turkiye",
            "https://www.cumhuriyet.com.tr/dunya",
            "https://www.cumhuriyet.com.tr/ekonomi",
            "https://www.cumhuriyet.com.tr/spor",
            "https://www.cumhuriyet.com.tr/kultur-sanat",
        ],
        "article_re": r"cumhuriyet\.com\.tr/[^/]+/[^/]+-\d+",
        "skip_re": r"(#|/foto/|/video/|/etiket/)",
    },
}

MAX_ARTICLES_PER_SITE = 3000


# ── helpers ───────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def parse_rss_urls(session: requests.Session, feed_url: str) -> list[str]:
    """Pull article URLs out of an RSS or Atom feed."""
    try:
        r = session.get(feed_url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  RSS fetch failed: {e}")
        return []

    soup = BeautifulSoup(r.content, "xml")
    urls = []
    for item in soup.find_all(["item", "entry"]):
        link = item.find("link")
        if link:
            url = link.get("href") or link.text.strip()
            if url.startswith("http"):
                urls.append(url.split("?")[0])  # drop tracking params
    return urls


def crawl_category_urls(
    session: requests.Session,
    category_urls: list[str],
    article_re: str,
    skip_re: str,
    max_urls: int,
) -> list[str]:
    """Fetch category pages and extract article links from them."""
    found: set[str] = set()
    art_pat  = re.compile(article_re)
    skip_pat = re.compile(skip_re) if skip_re else None

    for cat_url in category_urls:
        if len(found) >= max_urls:
            break
        try:
            r = session.get(cat_url, timeout=15)
            r.raise_for_status()
        except Exception:
            continue

        soup = BeautifulSoup(r.text, "lxml")
        base = f"{urlparse(cat_url).scheme}://{urlparse(cat_url).netloc}"

        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"]).split("?")[0].rstrip("/")
            if not art_pat.search(href):
                continue
            if skip_pat and skip_pat.search(href):
                continue
            found.add(href)

        time.sleep(DELAY)

    return list(found)


def extract_article_text(session: requests.Session, url: str) -> str | None:
    """Fetch a page and extract its article text using broad <p> selection."""
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, "lxml")

    # Remove common noise blocks before collecting paragraphs
    for sel in [
        "nav", "header", "footer", ".related", ".tags", ".comments",
        ".advertisement", ".social-share", ".breadcrumb", "script", "style",
        "[class*='related']", "[class*='social']", "[class*='widget']",
    ]:
        for el in soup.select(sel):
            el.decompose()

    paras = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) >= MIN_PARA_LEN
    ]
    text = "\n".join(paras)
    return text if len(text) >= MIN_ARTICLE_LEN else None


def url_to_filename(url: str) -> str:
    path = urlparse(url).path.strip("/").replace("/", "_")
    safe = re.sub(r"[^\w\-]", "_", path)
    return safe[:120] + ".txt"


# ── per-site scrape ───────────────────────────────────────────────────────────

def scrape_site(name: str, config: dict) -> int:
    session = make_session()
    site_dir = OUTPUT_DIR / name
    site_dir.mkdir(exist_ok=True)

    # 1. RSS seed
    rss_urls = parse_rss_urls(session, config["rss"])
    print(f"  RSS: {len(rss_urls)} URLs")

    # 2. Category crawl
    cat_urls = crawl_category_urls(
        session,
        config["category_urls"],
        config["article_re"],
        config.get("skip_re", ""),
        max_urls=MAX_ARTICLES_PER_SITE,
    )
    print(f"  Category crawl: {len(cat_urls)} URLs")

    # Merge & deduplicate, RSS first (freshest)
    all_urls = list(dict.fromkeys(rss_urls + cat_urls))[:MAX_ARTICLES_PER_SITE]
    print(f"  Total unique: {len(all_urls)}")

    saved = 0
    for url in tqdm(all_urls, desc=f"  {name}", unit="article"):
        fname    = url_to_filename(url)
        out_path = site_dir / fname
        if out_path.exists():
            continue

        text = extract_article_text(session, url)
        if text:
            out_path.write_text(f"SOURCE: {url}\n\n{text}", encoding="utf-8")
            saved += 1

        time.sleep(DELAY)

    return saved


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    total = 0
    for name, config in SITES.items():
        print(f"\n[{name}]")
        saved = scrape_site(name, config)
        print(f"  Saved: {saved} articles")
        total += saved
    print(f"\nDone. Total: {total} articles → {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
