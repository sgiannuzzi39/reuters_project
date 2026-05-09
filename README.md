# Mapping AI Adoption in News Organisations
### Data Collection Pipeline — Technical Documentation

This repository contains the data collection and processing pipeline for a dissertation project systematically analysing how news organisations globally have adopted artificial intelligence over time. It scrapes publicly documented AI use cases from industry databases, publications, and academic sources, stores them in a structured SQLite database, and exports them for LLM-assisted categorisation and visualisation.

---

## Research Context

The central research question is: **Is AI adoption in journalism primarily an extension of existing practices (efficiency/rationalisation), or does it represent a more transformative shift in news production?**

This pipeline addresses Phase 1 (Data Collection) and Phase 2 (Data Cleaning & Structuring) of the broader project. Phases 3–5 — LLM categorisation, visualisation, and public interface — build on the dataset produced here.

**Note on scope:** This approach captures only publicly documented cases, which represents the tip of the iceberg. Many adoptions go unreported, and published case studies are often self-serving. These limitations are acknowledged and addressed in the dissertation methodology.

---

## Project Structure

```
dissertation/
├── README.md                        # This file
├── requirements.txt                 # Python dependencies
├── run_all.py                       # Master script: runs all scrapers in sequence
│
├── scrapers/
│   ├── scraper_base.py              # Shared DB schema, insert logic, deduplication
│   ├── scraper_arxiv.py             # arXiv API (academic papers)
│   ├── scraper_niemanlab.py         # Nieman Lab (industry coverage)
│   └── scraper_journalismai.py      # JournalismAI case studies database
│
├── data/
│   └── usecases.db                  # SQLite database (created on first run)
│
├── export/
│   └── export_json.py               # Exports DB → JSON/JSONL for analysis
│
└── logs/
    └── scraper.log                  # Cumulative log of all scraper runs
```

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

If you need JavaScript rendering for dynamic sites (try without first):

```bash
playwright install chromium
```

### 2. Run a single scraper to test

```bash
cd scrapers
python scraper_arxiv.py --max-results 50
```

### 3. Run all scrapers

```bash
python run_all.py
```

This prints a summary table on completion:

```
════════════════════════════════════════════════════════════
  PIPELINE SUMMARY
════════════════════════════════════════════════════════════
  ✓  scrapers.scraper_arxiv              +87 rows
  ✓  scrapers.scraper_niemanlab          +134 rows
  ✓  scrapers.scraper_journalismai       +62 rows

  Total rows in database: 283
  Database path: data/usecases.db
════════════════════════════════════════════════════════════
```

### 4. Export for analysis

```bash
# Clean JSON for visualisation (no raw text)
python export/export_json.py

# JSONL with full raw text for LLM categorisation (Phase 3)
python export/export_json.py --format jsonl --include-raw

# Only rows not yet categorised (useful after partial Phase 3 runs)
python export/export_json.py --uncategorised-only --format jsonl --include-raw
```

---

## Database Schema

All scraped records are stored in a single SQLite table: `use_cases`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-incrementing primary key |
| `source_name` | TEXT | Human-readable source name (e.g. `"Nieman Lab"`) |
| `source_category` | TEXT | `"Curated"`, `"Database"`, `"Industry"`, `"Academic"`, `"Conference"`, `"Tools"` |
| `source_url` | TEXT | The URL that was scraped |
| `date_scraped` | TEXT | ISO-8601 UTC timestamp of when the record was collected |
| `title` | TEXT | Headline or case study title |
| `organisation` | TEXT | News organisation mentioned (e.g. `"BBC"`, `"Reuters"`) |
| `country` | TEXT | Country of the news organisation |
| `date_published` | TEXT | Publication date (ISO-8601, or `YYYY`, or `YYYY-MM` where only partial date available) |
| `url` | TEXT | Canonical link to the article or case study |
| `summary` | TEXT | Short description of the AI use case (≤500 chars) |
| `raw_text` | TEXT | Full extracted text, used as input for LLM categorisation in Phase 3 |
| `llm_category` | TEXT | **Phase 3** — assigned category (e.g. `"Automation"`, `"Content Generation"`) |
| `llm_theme` | TEXT | **Phase 3** — assigned theme (e.g. `"Efficiency"`, `"Personalisation"`) |
| `llm_stage` | TEXT | **Phase 3** — `"Experiment"`, `"Pilot"`, or `"Production"` |
| `dedup_hash` | TEXT | SHA-256 of `title + organisation + url`; enforces uniqueness |

### Querying the database directly

```bash
# Open with the SQLite CLI
sqlite3 data/usecases.db

# Useful queries
SELECT source_name, COUNT(*) FROM use_cases GROUP BY source_name;
SELECT * FROM use_cases WHERE organisation LIKE '%BBC%';
SELECT * FROM use_cases WHERE date_published >= '2023' ORDER BY date_published;
SELECT * FROM use_cases WHERE llm_category IS NULL LIMIT 10;
```

Or with Python:

```python
import sqlite3
conn = sqlite3.connect("data/usecases.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM use_cases WHERE country = 'UK'").fetchall()
for row in rows:
    print(dict(row))
```

---

## Scrapers

### `scraper_base.py` — Foundation module

Not run directly. Imported by all other scrapers. Provides:

- `get_db()` — creates/connects to the SQLite database and initialises the schema
- `insert_use_case(conn, record)` — inserts a record, returns `True` if inserted or `False` if it's a duplicate
- `make_dedup_hash(title, org, url)` — SHA-256 fingerprint for deduplication
- `log_summary(source, attempted, inserted)` — standardised end-of-run log line

---

### `scraper_arxiv.py` — arXiv (Academic)

**Method:** Official arXiv REST API — no scraping restrictions apply.

**What it collects:** Academic papers on AI in journalism. Captures title, abstract, publication date, author, arXiv URL, and subject categories.

**Note on `organisation` field:** arXiv records do not include news organisation names. The first author's name is stored as a proxy. The LLM categorisation pass in Phase 3 will refine this.

```bash
python scraper_arxiv.py                          # uses 5 default queries, 100 results each
python scraper_arxiv.py --max-results 200        # more results per query
python scraper_arxiv.py --query "NLP newsroom"   # single custom query
```

Default queries:
- `journalism artificial intelligence`
- `AI newsroom`
- `news automation natural language processing`
- `computational journalism`
- `news recommendation deep learning`

Rate limiting: 3-second delay between API calls, as requested by arXiv.

---

### `scraper_niemanlab.py` — Nieman Lab (Industry)

**Method:** Search-based HTML scraping with `requests` + `BeautifulSoup`. Fetches search result pages, then visits each article individually for full text.

**What it collects:** Articles about AI in journalism published by the Nieman Journalism Lab at Harvard. Captures title, publication date, article URL, and full article body text.

```bash
python scraper_niemanlab.py                      # 5 default queries, 5 pages each
python scraper_niemanlab.py --max-pages 10       # deeper pagination
python scraper_niemanlab.py --query "generative AI"  # single custom query
```

Default queries:
- `artificial intelligence`
- `AI newsroom`
- `machine learning journalism`
- `automated journalism`
- `generative AI news`

Rate limiting: 1.5s between article fetches, 2s between result pages.

---

### `scraper_journalismai.py` — JournalismAI Case Studies (Database)

**Method:** HTML scraping with pagination. Falls back to Playwright (headless Chromium) if the site requires JavaScript rendering.

**What it collects:** AI use cases from the JournalismAI case studies database (Polis, LSE). Captures title, organisation name, summary, tags/categories, and links to full case study pages.

```bash
python scraper_journalismai.py                   # static HTML (try this first)
python scraper_journalismai.py --use-playwright  # if the page renders blank
python scraper_journalismai.py --no-details      # skip fetching detail pages (faster)
```

**Troubleshooting:** If the scraper reports "No cards parsed", the site likely requires JavaScript. Re-run with `--use-playwright`.

---

## Deduplication

The same case study often appears across multiple sources. Deduplication works at two levels:

**1. Exact deduplication (automatic):** Every record gets a SHA-256 hash of `title + organisation + url` (lowercased, stripped). SQLite's `UNIQUE` constraint on `dedup_hash` silently discards exact duplicates on insert — no manual intervention needed.

**2. Fuzzy deduplication (Phase 2, manual):** Near-duplicates with slightly different titles (e.g. `"BBC uses AI for subtitles"` vs `"BBC deploys AI subtitling tool"`) are not caught by the hash. A separate cleanup pass using `rapidfuzz` string similarity can identify these. This will be documented in Phase 2 scripts when built.

---

## Adding a New Scraper

Each scraper follows the same pattern. To add a new source:

1. Create `scrapers/scraper_sourcename.py`
2. Import from `scraper_base`:
   ```python
   from scraper_base import get_db, insert_use_case, log_summary
   ```
3. Build a `scrape()` function that:
   - Fetches pages (with polite delays)
   - Parses records into the standard dict format
   - Calls `insert_use_case(conn, record)` for each
   - Calls `log_summary()` at the end
4. Add an entry to `SCRAPERS_TO_RUN` in `run_all.py`

Minimum required keys in a record dict:
```python
{
    "source_name":     "My Source",
    "source_category": "Industry",   # see schema above for valid values
    "source_url":      "https://...",
}
```

---

## Sources Covered / Planned

| Source | Category | Scraper | Status |
|--------|----------|---------|--------|
| arXiv | Academic | `scraper_arxiv.py` | ✅ Built |
| Nieman Lab | Industry | `scraper_niemanlab.py` | ✅ Built |
| JournalismAI Case Studies | Database | `scraper_journalismai.py` | ✅ Built |
| WAN-IFRA AI Report | Curated | `scraper_wanifra.py` | 🔲 Planned |
| Poynter | Industry | `scraper_poynter.py` | 🔲 Planned |
| Columbia Journalism Review | Industry | `scraper_cjr.py` | 🔲 Planned |
| Reuters Institute Digital News Report | Curated | `scraper_reutersinstitute.py` | 🔲 Planned |
| ONA AI in the Newsroom | Database | `scraper_ona.py` | 🔲 Planned |
| Trusting News AI Examples | Database | `scraper_trustingnews.py` | 🔲 Planned |
| Press Gazette | Industry | `scraper_pressgazette.py` | 🔲 Planned |
| Journalism.co.uk | Industry | `scraper_journalismcouk.py` | 🔲 Planned |
| Digiday | Industry | `scraper_digiday.py` | 🔲 Planned |
| Generative AI Newsroom (blog) | Thematic | `scraper_gai_newsroom.py` | 🔲 Planned |
| GIJN | Thematic | `scraper_gijn.py` | 🔲 Planned |
| Women in News AI Report | Curated | (PDF extraction) | 🔲 Planned |
| Airtable AI Newsroom Dataset | Database | (API/HTML) | 🔲 Planned |
| Google Scholar | Academic | (manual) | ⚠️ Manual only |
| ScienceDirect / SAGE | Academic | (paywalled) | ⚠️ Manual only |

---

## Legal & Ethical Notes

Web scraping for non-commercial academic research is generally permissible under UK law. Key references:

- UK guidance: [tech.cam.ac.uk/data-research](https://www.tech.cam.ac.uk/data-research) (search "scraping")
- General overview: [aballatore.space/2020/04/01/web-scraping-is-legal](https://aballatore.space/2020/04/01/web-scraping-is-legal/)

This pipeline follows best practices:
- Identifies itself via a `User-Agent` string including the institution
- Respects `robots.txt` (check per source before enabling)
- Uses polite delays between requests (1.5–3 seconds)
- Does not collect personal data
- Uses official APIs where available (arXiv)

---

## Next Steps (Phases 3–5)

Once sufficient data is collected:

**Phase 3 — LLM Categorisation**
- Export with `python export/export_json.py --format jsonl --include-raw`
- Run `analysis/categorise.py` (to be built) — sends `raw_text` to Claude API
- Populates `llm_category`, `llm_theme`, `llm_stage` columns in the DB

**Phase 4 — Visualisation**
- Timeline of adoption trends
- Heatmaps by region and organisation type
- Category distributions over time

**Phase 5 — Public Interface**
- Searchable, filterable web dashboard
- Downloadable dataset
- Interactive visualisations
