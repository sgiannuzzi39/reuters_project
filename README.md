# Mapping AI Adoption in News Organisations

Reuters Institute for the Study of Journalism · University of Oxford

Scrapers collect documented AI use cases from 16 industry sources into a SQLite database. A dashboard visualises the dataset interactively.

---

## Setup

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=<your-key>
```

## Usage

```bash
# run a scraper
python scrapers/scraper_niemanlab.py

# classify the dataset
python categorise.py --dry-run   # preview
python categorise.py             # run

# clean duplicates
python clean_data.py

# regenerate dashboard
python generate_dashboard.py
```

Open `index.html` in a browser — no server needed.

---

## Structure

```
├── generate_dashboard.py       # builds index.html + spreadsheet.html
├── categorise.py               # llm classification (task_type, effect_type)
├── clean_data.py               # dedup + academic re-filter
├── categorisation_prompt.md    # system prompt for gpt-4o-mini
│
├── scrapers/
│   ├── scraper_base.py         # shared db schema + insert logic
│   ├── scraper_*.py            # one scraper per source
│   └── import_*.py             # manual imports from pdfs / csvs
│
├── data/
│   ├── usecases_FINAL.db       # sqlite database
│   └── JournalismAI_case_studies.csv
│
├── index.html                  # dashboard (auto-generated)
└── spreadsheet.html            # full table (auto-generated)
```

---

## Sources

448 records across 16 sources.

| source | category | records |
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

## Database

Table `use_cases` in `data/usecases_FINAL.db`.

| column | description |
|--------|-------------|
| `source_name` | e.g. `"Nieman Lab"` |
| `source_category` | `"Academic"`, `"Curated"`, `"Database"`, or `"Industry"` |
| `title` | headline or case study title |
| `organisation` | news org (e.g. `"BBC"`) |
| `country` | country of the news org |
| `date_published` | `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` |
| `url` | link to the source article |
| `summary` | short description of the use case |
| `raw_text` | full extracted text (llm input) |
| `task_type` | one of 11 functional categories |
| `effect_type` | `"efficiency"`, `"effectiveness_and_scaling"`, or `"optimisation"` |
| `low_confidence` | `1` if the llm flagged the classification as uncertain |
| `dedup_hash` | sha-256 of title + org + url |
