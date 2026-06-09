# Mapping AI Adoption in News Organisations

Reuters Institute for the Study of Journalism · University of Oxford

Scrapers collect documented AI use cases from 16 industry sources into a SQLite database. A three-page dashboard visualises the dataset interactively.

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

# classify gatekeeping stage
python gatekeeper.py --dry-run   # preview
python gatekeeper.py             # run

# clean duplicates
python clean_data.py

# regenerate dashboard
python generate_dashboard.py
```

Open `index.html` in a browser — no server needed.

---

## Structure

```
├── generate_dashboard.py       # builds index.html + spreadsheet.html + sources.html
├── categorise.py               # llm classification (task_type, effect_type)
├── gatekeeper.py               # llm classification (gatekeeping_stage)
├── clean_data.py               # dedup + academic re-filter
├── categorisation_prompt.md    # system prompt for task/effect classification
├── gatekeeper_prompt.md        # system prompt for gatekeeping stage classification
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
├── index.html                  # overview dashboard (auto-generated)
├── spreadsheet.html            # full filterable table (auto-generated)
└── sources.html                # methodology, sources, and geographic coverage (auto-generated)
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

## Classification pipelines

### `categorise.py`

Classifies every record by **task type** (what the AI does) and **effect type** (what benefit it delivers) using GPT-4o-mini and `categorisation_prompt.md`.

```bash
python categorise.py             # classify unclassified records
python categorise.py --rerun-low # retry low-confidence records
python categorise.py --limit 20  # test on 20 records
```

Valid `task_type` values: `discovery_and_monitoring`, `data_extraction_and_analysis`, `verification_and_validation`, `transcription_and_translation`, `search_and_retrieval`, `content_generation`, `content_transformation`, `editing_and_optimisation`, `audience_targeting_and_personalisation`, `commercial_optimisation`, `moderation_and_interaction`.

Valid `effect_type` values: `efficiency`, `effectiveness_and_scaling`, `optimisation`.

### `gatekeeper.py`

Classifies every record by **gatekeeping stage** (where in the news production process the AI operates) using GPT-4o-mini and `gatekeeper_prompt.md`.

```bash
python gatekeeper.py             # classify unclassified records
python gatekeeper.py --rerun-low # retry low-confidence records
python gatekeeper.py --rerun     # re-run all records
python gatekeeper.py --limit 20  # test on 20 records
```

Valid `gatekeeping_stage` values: `access_and_observation`, `selection_and_filtering`, `processing_and_editing`, `publishing_and_distribution`.

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
| `task_type` | one of 11 functional categories (see above) |
| `task_type_reasoning` | llm explanation for `task_type` assignment |
| `effect_type` | `"efficiency"`, `"effectiveness_and_scaling"`, or `"optimisation"` |
| `effect_type_reasoning` | llm explanation for `effect_type` assignment |
| `low_confidence` | `1` if the llm flagged the task/effect classification as uncertain |
| `gatekeeping_stage` | one of 4 news production stages (see above) |
| `gatekeeping_stage_reasoning` | llm explanation for `gatekeeping_stage` assignment |
| `gatekeeping_low_confidence` | `1` if the llm flagged the gatekeeping classification as uncertain |
| `dedup_hash` | sha-256 of title + org + url |
