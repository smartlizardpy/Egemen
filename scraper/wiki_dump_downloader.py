"""
Download & extract the Turkish Wikipedia XML dump — MUCH faster than API scraping.
Produces a single merged .txt file with all article text.
Run this on the M4 Mac for bulk data.

Usage:
    python wiki_dump_downloader.py
"""

import bz2
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from tqdm import tqdm
import urllib.request

DUMP_URL = "https://dumps.wikimedia.org/trwiki/latest/trwiki-latest-pages-articles.xml.bz2"
DUMP_FILE = Path("data/trwiki-latest.xml.bz2")
OUTPUT_FILE = Path("data/wikipedia_dump.txt")

NS = "{http://www.mediawiki.org/xml/export-0.11/}"

# Wikitext noise patterns to strip
NOISE = re.compile(
    r"\{\{[^}]*\}\}"      # templates {{...}}
    r"|\[\[Kategori:[^\]]*\]\]"  # category links
    r"|\[\[Dosya:[^\]]*\]\]"     # file links
    r"|\[\[File:[^\]]*\]\]"
    r"|<ref[^>]*>.*?</ref>"      # references
    r"|<[^>]+>"                  # HTML tags
    r"|\[\[(?:[^\]|]*\|)?([^\]]*)\]\]",  # wiki links — keep display text
    re.DOTALL,
)


def download_dump():
    DUMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DUMP_FILE.exists():
        print(f"Dump already downloaded: {DUMP_FILE}")
        return

    print(f"Downloading TR Wikipedia dump (~2 GB compressed)...")
    print(f"URL: {DUMP_URL}")

    def _progress(block_num, block_size, total_size):
        done = block_num * block_size
        pct = done / total_size * 100 if total_size > 0 else 0
        mb = done / 1_000_000
        print(f"\r  {pct:.1f}%  ({mb:.0f} MB)", end="", flush=True)

    urllib.request.urlretrieve(DUMP_URL, DUMP_FILE, reporthook=_progress)
    print()


def clean_wikitext(text: str) -> str:
    text = NOISE.sub(r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_articles(min_length: int = 300):
    print("Extracting articles from dump (streaming)...")
    count = 0
    with bz2.open(DUMP_FILE, "rb") as f, OUTPUT_FILE.open("w", encoding="utf-8") as out:
        context = ET.iterparse(f, events=("end",))
        for event, elem in context:
            if elem.tag != f"{NS}page":
                continue

            ns_tag = elem.find(f"{NS}ns")
            if ns_tag is None or ns_tag.text != "0":  # main namespace only
                elem.clear()
                continue

            title = elem.findtext(f"{NS}title", "")
            text_el = elem.find(f".//{NS}text")
            raw = text_el.text if text_el is not None else ""

            if raw and len(raw) >= min_length:
                clean = clean_wikitext(raw)
                if len(clean) >= min_length:
                    out.write(f"=== {title} ===\n{clean}\n\n")
                    count += 1
                    if count % 10_000 == 0:
                        print(f"  Extracted {count:,} articles...")

            elem.clear()

    print(f"Done. {count:,} articles → {OUTPUT_FILE}")


def main():
    download_dump()
    extract_articles()


if __name__ == "__main__":
    main()
