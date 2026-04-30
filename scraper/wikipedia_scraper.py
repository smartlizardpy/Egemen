"""
Turkish Wikipedia scraper.
Uses the MediaWiki API to fetch article text — cleaner than HTML parsing.
Saves one .txt file per article in data/wikipedia/.
"""

import json
import time
import requests
from pathlib import Path
from tqdm import tqdm

OUTPUT_DIR = Path(__file__).parent / "data" / "wikipedia"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

API = "https://tr.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "TurkishSLMScraper/1.0 (research; remzi.kaygusuz@durham.ac.uk)"}

# How many articles to fetch per run (-1 = all, slow!)
MAX_ARTICLES = 5000
BATCH_SIZE = 50  # articles per API call
DELAY = 0.5      # seconds between requests (be polite)


def get_all_article_titles(limit: int) -> list[str]:
    """Stream article titles from the TR Wikipedia namespace."""
    titles = []
    params = {
        "action": "query",
        "list": "allpages",
        "apnamespace": 0,
        "aplimit": 500,
        "apfilterredir": "nonredirects",
        "format": "json",
    }
    print(f"Fetching article titles (target: {limit})...")
    with tqdm(total=limit, unit="title") as bar:
        while len(titles) < limit:
            r = requests.get(API, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
            batch = [p["title"] for p in data["query"]["allpages"]]
            titles.extend(batch)
            bar.update(len(batch))

            cont = data.get("continue", {}).get("apcontinue")
            if not cont:
                break
            params["apcontinue"] = cont
            time.sleep(DELAY)

    return titles[:limit]


def fetch_article_texts(titles: list[str]) -> dict[str, str]:
    """Batch-fetch plain text for a list of titles via the Extracts API."""
    texts = {}
    for i in range(0, len(titles), BATCH_SIZE):
        chunk = titles[i : i + BATCH_SIZE]
        params = {
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "extracts",
            "explaintext": True,       # plain text, no HTML
            "exsectionformat": "plain",
            "format": "json",
        }
        r = requests.get(API, params=params, headers=HEADERS, timeout=60)
        r.raise_for_status()
        pages = r.json()["query"]["pages"]
        for page in pages.values():
            title = page.get("title", "")
            text = page.get("extract", "")
            if text and len(text.strip()) > 200:  # skip stubs
                texts[title] = text.strip()
        time.sleep(DELAY)
    return texts


def save_texts(texts: dict[str, str]) -> None:
    for title, text in texts.items():
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)
        path = OUTPUT_DIR / f"{safe[:100]}.txt"
        path.write_text(text, encoding="utf-8")


def main():
    titles = get_all_article_titles(MAX_ARTICLES)
    print(f"Got {len(titles)} titles. Fetching full text...")

    saved = 0
    for i in tqdm(range(0, len(titles), BATCH_SIZE), unit="batch"):
        chunk = titles[i : i + BATCH_SIZE]
        texts = fetch_article_texts(chunk)
        save_texts(texts)
        saved += len(texts)

    print(f"\nDone. Saved {saved} articles to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
