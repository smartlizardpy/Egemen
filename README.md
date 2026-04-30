# Turkish SLM Corpus — Egemen

This is the training dataset for **Egemen**, a Turkish small language model (SLM). The corpus is scraped from Wikipedia, Turkish news outlets, and biographical sources.

> The Egemen model will be released separately once trained.

## Dataset

| File | Description | Size | Where |
|------|-------------|------|-------|
| `scraper/data/wikipedia_dump.txt` | Full Turkish Wikipedia (~500k articles) | ~1.4 GB | [GitHub Release](../../releases/latest) |
| `scraper/data/corpus.txt` | Merged + deduplicated corpus (all sources) | ~1.5 GB | Generate locally |
| `scraper/data/people.txt` | Biographies of ~50k people | ~4 MB | This repo |
| `scraper/data/news/` | News articles (8 outlets) | ~6 MB | This repo |

### Sources

| Source | Type | Language |
|--------|------|----------|
| [Turkish Wikipedia](https://tr.wikipedia.org) | Encyclopedia | TR |
| [BBC Türkçe](https://www.bbc.com/turkce) | News | TR |
| [TRT Haber](https://www.trthaber.com) | News | TR |
| [Anadolu Ajansı](https://www.aa.com.tr) | News | TR |
| [CNN Türk](https://www.cnnturk.com) | News | TR |
| [Hürriyet](https://www.hurriyet.com.tr) | News | TR |
| [NTV](https://www.ntv.com.tr) | News | TR |
| [Sözcü](https://www.sozcu.com.tr) | News | TR |

## Quickstart

```bash
git clone https://github.com/YOUR_USERNAME/turkish-slm-corpus
cd turkish-slm-corpus

python3 -m venv .venv && source .venv/bin/activate
pip install -r scraper/requirements.txt
```

### Run the scrapers

```bash
cd scraper

# 1. Download full Turkish Wikipedia dump (~2 GB download, produces wikipedia_dump.txt)
python wiki_dump_downloader.py

# 2. Scrape news articles from 8 Turkish outlets
python news_scraper.py

# 3. Scrape biographies of ~50k people from Wikipedia categories
python people_scraper.py

# 4. Merge everything into a single corpus.txt
python merge_and_clean.py
```

### Or download the pre-built files

Download `wikipedia_dump.txt` from the [latest release](../../releases/latest) and place it in `scraper/data/`, then run `merge_and_clean.py`.

## Stats

- ~500,000 Wikipedia articles
- ~1,100+ news articles (growing)
- ~26,000 lines of biographical text
- ~1.5 GB merged corpus

## License

- Wikipedia content: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- News content: scraped for non-commercial research purposes
- Scraper code: MIT
