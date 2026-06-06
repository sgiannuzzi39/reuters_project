# Mapping AI Adoption in News Organisations

**Reuters Institute for the Study of Journalism · University of Oxford**

A data collection and processing pipeline that systematically documents how news organisations worldwide have adopted artificial intelligence. Records are scraped from industry databases, publications, and curated reports, stored in a structured SQLite database, and served through an interactive dashboard.

---

## Project Structure

```
diss/
├── README.md
├── requirements.txt
├── generate_dashboard.py          # Builds index.html + spreadsheet.html from DB
├── clean_data.py                  # Cross-source dedup + LLM re-filter
│
├── scrapers/
│   ├── scraper_base.py            # Shared DB schema, insert logic, LLM filter
│   │
│   ├── scraper_arxiv.py           # arXiv API
│   ├── scraper_cjr.py             # Columbia Journalism Review
│   ├── scraper_digiday.py         # Digiday
│   ├── scraper_editorandpublisher.py
│   ├── scraper_generativeainewsroom.py
│   ├── scraper_gni.py             # Google News Initiative
│   ├── scraper_inma.py            # INMA
│   ├── scraper_journalism_co_uk.py
│   ├── scraper_niemanlab.py
│   ├── scraper_poynter.py
│   ├── scraper_pressgazette.py
│   ├── scraper_reutersinstitute.py
│   ├── scraper_wanifra.py
│   │
│   ├── import_journalismai_csv.py     # Bulk import from JournalismAI CSV
│   ├── import_reuters_dnr_2025.py     # Reuters Digital News Report 2025
│   └── import_women_in_news_2025.py   # WAN-IFRA Age of AI in the Newsroom
│
├── data/
│   ├── usecases_FINAL.db          # Canonical SQLite database (WAL mode)
│   ├── usecases_FINAL.sql         # SQL dump — source of truth / backup
│   └── JournalismAI_case_studies.csv  # Input data for import_journalismai_csv.py
│
├── logs/                          # Runtime logs (gitignored)
│
├── index.html                     # Dashboard — auto-generated, open directly in browser
└── spreadsheet.html               # Full data table — auto-generated
```

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export OPENAI_API_KEY=<your-key>   # required for LLM relevance filtering
```

### 3. Run a scraper

Each scraper runs standalone from the project root:

```bash
python scrapers/scraper_niemanlab.py
python scrapers/scraper_inma.py
```

For long-running scrapers, keep them running with the terminal closed:

```bash
nohup python scrapers/scraper_arxiv.py > logs/arxiv.log 2>&1 & disown
```

### 4. Clean the data (optional)

Remove cross-source duplicates and re-filter academic records:

```bash
python clean_data.py --dry-run   # preview changes
python clean_data.py             # apply
```

### 5. Regenerate the dashboard

```bash
python generate_dashboard.py
```

Open `index.html` directly in a browser — no server required.

---

## Sources

Current database: **448 records** across 16 sources.

| Source | Category | Records |
|--------|----------|---------|
| JournalismAI | Database | 212 |
| WAN-IFRA | Industry | 53 |
| INMA | Industry | 50 |
| Google News Initiative | Industry | 24 |
| Nieman Lab | Industry | 20 |
| Press Gazette | Industry | 19 |
| Reuters Institute Digital News Report 2025 | Curated | 13 |
| Generative AI Newsroom | Industry | 11 |
| Journalism.co.uk | Industry | 9 |
| WAN-IFRA Age of AI in the Newsroom | Curated | 8 |
| Poynter | Industry | 7 |
| Reuters Institute | Curated | 7 |
| Columbia Journalism Review | Industry | 6 |
| Digiday | Industry | 6 |
| Editor & Publisher | Industry | 2 |
| arXiv | Academic | 1 |

---

## Database Schema

All records are stored in `data/usecases_FINAL.db`, table `use_cases`.

| Column | Description |
|--------|-------------|
| `source_name` | Human-readable source (e.g. `"Nieman Lab"`) |
| `source_category` | `"Academic"`, `"Curated"`, `"Database"`, or `"Industry"` |
| `source_url` | URL that was scraped |
| `date_scraped` | ISO-8601 UTC timestamp |
| `title` | Headline or case study title |
| `organisation` | News organisation (e.g. `"BBC"`) |
| `country` | Country of the news organisation |
| `date_published` | `YYYY-MM-DD`, `YYYY-MM`, or `YYYY` |
| `url` | Canonical link to the source article |
| `summary` | Short description of the AI use case |
| `raw_text` | Full extracted text (used as LLM input) |
| `llm_category` | Phase 3 — e.g. `"Automation"`, `"Content Generation"` |
| `llm_theme` | Phase 3 — e.g. `"Efficiency"`, `"Personalisation"` |
| `llm_stage` | Phase 3 — `"Experiment"`, `"Pilot"`, or `"Production"` |
| `dedup_hash` | SHA-256 of `title + organisation + url`; enforces uniqueness |

```bash
# Query examples
sqlite3 data/usecases_FINAL.db "SELECT source_name, COUNT(*) FROM use_cases GROUP BY source_name;"
sqlite3 data/usecases_FINAL.db "SELECT * FROM use_cases WHERE organisation LIKE '%BBC%';"
```

---

## LLM Relevance Filter

All scrapers use `is_ai_journalism_relevant()` from `scraper_base.py` before inserting records. It calls `gpt-4o-mini` to verify the record describes a **concrete AI use case by a specific news organisation** — not a generic opinion piece or policy discussion. On any API error the record is passed through conservatively so no valid record is silently dropped.

---

## Dashboard

`generate_dashboard.py` reads `data/usecases_FINAL.db` and produces:

- **`index.html`** — interactive overview with timeline, type breakdown, source chart, and country chart
- **`spreadsheet.html`** — sortable, filterable table of all 448 records

Both files embed the data inline, so they open directly from the filesystem without a web server.

---

## Legal & Ethical Notes

This pipeline is for non-commercial academic research. It:

- Uses official APIs where available (arXiv, Elsevier)
- Applies polite delays between requests (0.5–3 seconds)
- Does not bypass authentication or paywalls
- Does not store personal data
