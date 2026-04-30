"""
Merge all scraped .txt files into a single training corpus.
Applies basic Turkish text cleaning:
  - Remove lines that are too short (navigation, captions)
  - Deduplicate paragraphs (exact match)
  - Ensure UTF-8 with Turkish chars intact
"""

import re
import hashlib
from pathlib import Path
from tqdm import tqdm

DATA_DIR = Path(__file__).parent / "data"
OUTPUT = DATA_DIR / "corpus.txt"

MIN_LINE_LEN = 40  # chars — below this is likely a caption or header
MIN_DOC_LEN = 200  # chars — skip very short documents


def is_turkish(text: str) -> bool:
    """Rough check — Turkish has distinctive chars."""
    tr_chars = set("ğüşıöçĞÜŞİÖÇ")
    return bool(tr_chars & set(text))


def clean_doc(text: str) -> str:
    lines = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        # drop short lines (nav, stubs)
        if len(line) < MIN_LINE_LEN:
            continue
        # dedup exact lines
        h = hashlib.md5(line.encode()).digest()
        if h in seen:
            continue
        seen.add(h)
        lines.append(line)
    return "\n".join(lines)


def iter_txt_files(root: Path):
    for p in root.rglob("*.txt"):
        if p == OUTPUT:
            continue
        yield p


def main():
    files = list(iter_txt_files(DATA_DIR))
    print(f"Found {len(files)} source files")

    seen_docs: set[bytes] = set()
    total_chars = 0
    kept = 0

    with OUTPUT.open("w", encoding="utf-8") as out:
        for path in tqdm(files, unit="file"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # strip SOURCE: header added by news scraper
            text = re.sub(r"^SOURCE:.*\n\n", "", text)
            cleaned = clean_doc(text)

            if len(cleaned) < MIN_DOC_LEN:
                continue
            if not is_turkish(cleaned):
                continue

            doc_hash = hashlib.md5(cleaned.encode()).digest()
            if doc_hash in seen_docs:
                continue
            seen_docs.add(doc_hash)

            out.write(cleaned + "\n\n")
            total_chars += len(cleaned)
            kept += 1

    size_mb = OUTPUT.stat().st_size / 1_000_000
    print(f"\nKept {kept}/{len(files)} docs")
    print(f"Total chars: {total_chars:,}")
    print(f"Output: {OUTPUT} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
