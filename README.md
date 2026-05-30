# Mapping AI Adoption in News Organisations
### Data Collection Pipeline — Technical Documentation

This repository contains the data collection and processing pipeline for a dissertation project systematically analysing how news organisations globally have adopted artificial intelligence over time. It scrapes publicly documented AI use cases from industry databases, publications, and academic sources, stores them in a structured SQLite database, and exports them for visualisation.

---

## Research Context

The central research question is: **Is AI adoption in journalism primarily an extension of existing practices (efficiency/rationalisation), or does it represent a more transformative shift in news production?**

This pipeline addresses Phase 1 (Data Collection) and Phase 2 (Data Cleaning & Structuring) of the broader project. Phases 3–5 — LLM categorisation, visualisation, and public interface — build on the dataset produced here.

**Note on scope:** This approach captures only publicly documented cases, which represents the tip of the iceberg. Many adoptions go unreported, and published case studies are often self-serving. These limitations are acknowledged in the dissertation methodology.

---

## Project Structure

```
diss/
├── README.md                        # This file
├── requirements.txt                 # Python dependencies
├── generate_dashboard.py            # Generates index.html, spreadsheet.html, data.json
│
├── scrapers/
│   ├── scraper_base.py              # Shared DB schema, insert logic, LLM filter
│   │
│   ├── # ── Academic sources ──────────────────────────────────────
│   ├── scraper_arxiv.py             # arXiv API
│   ├── scraper_semanticscholar.py   # Semantic Scholar API
│   ├── scraper_sciencedirect.py     # Elsevier ScienceDirect API
│   │
│   ├── # ── Industry / curated sources ────────────────────────────
│   ├── scraper_journalismai.py      # JournalismAI case studies (Polis/LSE)
│   ├── scraper_niemanlab.py         # Nieman Lab
│   ├── scraper_pressgazette.py      # Press Gazette
│   ├── scraper_journalism_co_uk.py  # Journalism.co.uk
│   ├── scraper_digiday.py           # Digiday
│   ├── scraper_poynter.py           # Poynter
│   ├── scraper_cjr.py               # Columbia Journalism Review
│   ├── scraper_editorandpublisher.py# Editor & Publisher
│   ├── scraper_inma.py              # INMA
│   ├── scraper_wanifra.py           # WAN-IFRA
│   ├── scraper_ona.py               # ONA AI in the Newsroom
│   ├── scraper_reutersinstitute.py  # Reuters Institute
│   ├── scraper_reutersinstitute_news.py
│   ├── scraper_generativeainewsroom.py  # Generative AI Newsroom blog
│   ├── scraper_gni.py               # Google News Initiative case studies
│   ├── scraper_github.py            # GitHub repository search
│   ├── scraper_huggingface.py       # HuggingFace JournalistsonHF org
│   ├── scraper_gijn.py              # GIJN (Cloudflare-blocked, non-functional)
│   │
│   └── # ── Data importers ────────────────────────────────────────
│       ├── import_journalismai_csv.py   # Bulk import from CSV export
│       ├── import_reuters_dnr_2025.py   # Reuters Digital News Report 2025
│       └── import_women_in_news_2025.py # WAN-IFRA Women in News AI Report
│
├── data/
│   └── usecases.db                  # SQLite database (WAL mode)
│
├── export/                          # Export utilities
├── logs/
│   └── scraper.log                  # Cumulative log of all runs
│
├── index.html                       # Dashboard (auto-generated)
└── spreadsheet.html                 # Scrollable data table (auto-generated)
```

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export OPENAI_API_KEY=<your-key>       # required for LLM relevance filtering
export GITHUB_TOKEN=<your-token>       # required for GitHub scraper (free, no scopes)
export ELSEVIER_API_KEY=<your-key>     # required for ScienceDirect scraper
export SEMANTICSCHOLAR_API_KEY=<key>   # optional — increases Semantic Scholar rate limit
```

### 3. Run a scraper

Each scraper runs standalone from the project root:

```bash
python scrapers/scraper_niemanlab.py
python scrapers/scraper_github.py
python scrapers/scraper_huggingface.py
```

For long-running scrapers, use `nohup` to keep them running with the lid closed:

```bash
nohup python scrapers/scraper_arxiv.py > logs/arxiv.log 2>&1 &
disown
```

### 4. Regenerate the dashboard

```bash
python generate_dashboard.py
```

This writes `index.html`, `spreadsheet.html`, and `data.json` from the current database state.

---

## Database Schema

All scraped records are stored in a single SQLite table: `use_cases` (`data/usecases.db`).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-incrementing primary key |
| `source_name` | TEXT | Human-readable source name (e.g. `"Nieman Lab"`) |
| `source_category` | TEXT | `"Academic"`, `"Curated"`, `"Database"`, `"Industry"` |
| `source_url` | TEXT | The URL that was scraped |
| `date_scraped` | TEXT | ISO-8601 UTC timestamp of when the record was collected |
| `title` | TEXT | Headline or case study title |
| `organisation` | TEXT | News organisation mentioned (e.g. `"BBC"`, `"Reuters"`) |
| `country` | TEXT | Country of the news organisation |
| `date_published` | TEXT | Publication date (`YYYY-MM-DD`, `YYYY-MM`, or `YYYY`) |
| `url` | TEXT | Canonical link to the article or case study |
| `summary` | TEXT | Short description of the AI use case (≤500 chars) |
| `raw_text` | TEXT | Full extracted text, used as LLM input |
| `llm_category` | TEXT | **Phase 3** — e.g. `"Automation"`, `"Content Generation"` |
| `llm_theme` | TEXT | **Phase 3** — e.g. `"Efficiency"`, `"Personalisation"` |
| `llm_stage` | TEXT | **Phase 3** — `"Experiment"`, `"Pilot"`, or `"Production"` |
| `dedup_hash` | TEXT | SHA-256 of `title + organisation + url`; enforces uniqueness |

### Querying the database directly

```bash
sqlite3 data/usecases.db

SELECT source_name, COUNT(*) FROM use_cases GROUP BY source_name;
SELECT * FROM use_cases WHERE organisation LIKE '%BBC%';
SELECT * FROM use_cases WHERE date_published >= '2023' ORDER BY date_published;
```

---

## Sources Covered

Current database: **~850 records** (as of May 2026).

| Source | Category | Scraper | Status |
|--------|----------|---------|--------|
| JournalismAI (Polis/LSE) | Database | `scraper_journalismai.py` | ✅ 270 records |
| GitHub | Industry | `scraper_github.py` | ✅ 179 records |
| Google News Initiative | Industry | `scraper_gni.py` | ✅ 52 records |
| Press Gazette | Industry | `scraper_pressgazette.py` | ✅ 51 records |
| INMA | Industry | `scraper_inma.py` | ✅ 49 records |
| WAN-IFRA | Industry | `scraper_wanifra.py` | ✅ 49 records |
| Generative AI Newsroom | Academic | `scraper_generativeainewsroom.py` | ✅ 25 records |
| Nieman Lab | Industry | `scraper_niemanlab.py` | ✅ 28 records |
| arXiv | Academic | `scraper_arxiv.py` | ✅ 23 records |
| Journalism.co.uk | Industry | `scraper_journalism_co_uk.py` | ✅ 21 records |
| Digiday | Industry | `scraper_digiday.py` | ✅ 20 records |
| Reuters Institute | Academic | `scraper_reutersinstitute.py` | ✅ 17 records |
| Reuters Institute Digital News Report 2025 | Curated | `import_reuters_dnr_2025.py` | ✅ 15 records |
| Poynter | Industry | `scraper_poynter.py` | ✅ 13 records |
| Editor & Publisher | Industry | `scraper_editorandpublisher.py` | ✅ 11 records |
| ONA AI in the Newsroom | Database | `scraper_ona.py` | ✅ 10 records |
| WAN-IFRA Women in News AI Report | Curated | `import_women_in_news_2025.py` | ✅ 8 records |
| Columbia Journalism Review | Industry | `scraper_cjr.py` | ✅ 5 records |
| Semantic Scholar | Academic | `scraper_semanticscholar.py` | ✅ 1 record |
| HuggingFace (JournalistsonHF) | Industry | `scraper_huggingface.py` | 🔄 In progress |
| ScienceDirect | Academic | `scraper_sciencedirect.py` | ⏳ Needs `ELSEVIER_API_KEY` |
| GIJN | Industry | `scraper_gijn.py` | ⚠️ Cloudflare-blocked |

---

## Scraper Notes

### LLM relevance filter (`scraper_base.py`)

All scrapers use a shared OpenAI filter (`is_ai_journalism_relevant()`) before inserting records. It calls `gpt-4o-mini` to verify the record describes a **concrete AI use case by a specific news organisation** — not a generic opinion piece or academic theory. On API error, the record is allowed through conservatively.

Some scrapers (GitHub, HuggingFace) use a source-specific LLM prompt rather than the shared one, to match the different nature of those sources.

### `scraper_arxiv.py` — arXiv

Uses the official arXiv Atom API (`export.arxiv.org/api/query`). No API key required. 20 co-occurrence queries (e.g. `all:journalism AND all:"artificial intelligence"`). 3s between pages, 5s between queries. Subject to rate limiting — exponential backoff applied.

### `scraper_semanticscholar.py` — Semantic Scholar

Uses the Semantic Scholar Graph API. No key required, but `SEMANTICSCHOLAR_API_KEY` increases the rate limit. 20 queries with exponential backoff (30→60→120→240s on 429s).

### `scraper_sciencedirect.py` — ScienceDirect

Requires a free `ELSEVIER_API_KEY` from [dev.elsevier.com](https://dev.elsevier.com). Uses `tak()` (title/abstract/keyword) field syntax. Fetches full abstracts via the Abstract Retrieval API when the teaser is too short.

### `scraper_github.py` — GitHub

Requires `GITHUB_TOKEN` (free personal access token, no scopes needed). Searches 23 queries across free-text and topic tags. Fetches READMEs for repos with short descriptions. Uses a GitHub-specific LLM prompt requiring repos to be tied to a **specific named news organisation** — generic NLP libraries and academic projects are excluded.

### `scraper_huggingface.py` — HuggingFace

No API key required. Fetches all ~407 members of the [JournalistsonHF](https://huggingface.co/JournalistsonHF) org, then all Spaces belonging to each member. Fetches READMEs for LLM context. **Privacy**: member usernames are not stored in the database; the `organisation` field is always `None` for member spaces.

### `scraper_gni.py` — Google News Initiative

Scrapes the GNI case studies listing page (server-rendered). Extracts 200+ story slugs, visits each individually. Organisation name parsed from breadcrumb metadata.

---

## Deduplication

Every record gets a SHA-256 hash of `title + organisation + url` (lowercased, stripped). SQLite's `UNIQUE` constraint on `dedup_hash` silently discards exact duplicates — no manual intervention needed. Near-duplicates with slightly different titles are not caught automatically; these would require a fuzzy-matching pass.

---

## Dashboard

Running `python generate_dashboard.py` produces two HTML files:

- **`index.html`** — interactive dashboard with charts (timeline, category breakdown, source distribution, country map)
- **`spreadsheet.html`** — scrollable, filterable table of all records
- **`data.json`** — underlying data used by both pages

---

## Legal & Ethical Notes

Web scraping for non-commercial academic research is generally permissible under UK law. This pipeline:

- Identifies itself via a descriptive `User-Agent` string
- Uses polite delays between requests (0.5–3 seconds depending on source)
- Uses official APIs where available (arXiv, Semantic Scholar, GitHub, HuggingFace, Elsevier)
- Does not store personal data (HuggingFace member usernames explicitly excluded)
- Does not bypass authentication or paywalls

---

## Next Steps (Phases 3–5)

**Phase 3 — LLM Categorisation**
- Send `raw_text` to Claude API to populate `llm_category`, `llm_theme`, `llm_stage`

**Phase 4 — Visualisation**
- Timeline of adoption trends; heatmaps by region; category distributions over time

**Phase 5 — Public Interface**
- Searchable, filterable web dashboard with downloadable dataset
