"""
scraper_sciencedirect.py
------------------------
Scrapes ScienceDirect via the Elsevier Developer API for academic papers
about AI use cases in news organisations and journalism.

Authentication:
  A free API key is required. Register at https://dev.elsevier.com and
  create an application to receive a key, then set:
      export ELSEVIER_API_KEY=<your-key>

  Rate limits (free / non-institutional key):
    - 3 requests/second
    - 20 000 requests/week
    - Search results include title, teaser, date, DOI
    - Full abstracts require fetching each article individually via the
      Abstract Retrieval API; this scraper does that only when the search
      teaser is too short for the LLM filter.

Query syntax (Elsevier ScienceDirect):
  tak(phrase)    — title + abstract + keywords (combined)
  title(phrase)  — title only
  Boolean: AND, OR, AND NOT

Usage:
    python scraper_sciencedirect.py
    python scraper_sciencedirect.py --dry-run
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("sciencedirect")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
SEARCH_URL   = "https://api.elsevier.com/content/search/sciencedirect"
ABSTRACT_URL = "https://api.elsevier.com/content/abstract/doi/{doi}"
SOURCE_URL   = "https://www.sciencedirect.com/search"
SOURCE_NAME  = "ScienceDirect"
SOURCE_CAT   = "Academic"

BATCH_SIZE             = 100    # results per request (API max)
MAX_RESULTS_PER_QUERY  = 500
DELAY_BETWEEN_PAGES    = 1.0    # seconds (stay under 3 req/s)
DELAY_BETWEEN_QUERIES  = 3.0
MIN_TEASER_LEN         = 80     # fetch full abstract if teaser shorter than this

# Simple two-term queries — broad enough to catch any paper where both concepts
# appear in title, abstract, or keywords. The LLM filter handles false positives.
# tak() searches title + abstract + keywords combined.
SEARCH_QUERIES = [
    'tak(journalism) AND tak("artificial intelligence")',
    'tak(journalism) AND tak("machine learning")',
    'tak(journalism) AND tak("deep learning")',
    'tak(journalism) AND tak("large language model")',
    'tak(journalism) AND tak("generative AI")',
    'tak(journalism) AND tak(GPT)',
    'tak(journalism) AND tak(NLP)',
    'tak(newsroom) AND tak("artificial intelligence")',
    'tak(newsroom) AND tak("machine learning")',
    'tak(newsroom) AND tak("language model")',
    'tak(newsroom) AND tak("generative AI")',
    'tak("news organization") AND tak("artificial intelligence")',
    'tak("news organization") AND tak("machine learning")',
    'tak("news media") AND tak("machine learning")',
    'tak("news media") AND tak("artificial intelligence")',
    'tak("fake news") AND tak(detection)',
    'tak(misinformation) AND tak(detection) AND tak(news)',
    'tak("fact-checking") AND tak("machine learning")',
    'tak("news recommendation") AND tak("machine learning")',
    'tak("media bias") AND tak("machine learning")',
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def _api_key() -> str:
    key = os.environ.get("ELSEVIER_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ELSEVIER_API_KEY is not set.\n"
            "Register free at https://dev.elsevier.com, create an application,\n"
            "then: export ELSEVIER_API_KEY=<your-key>"
        )
    return key


def _headers() -> dict:
    return {
        "Accept": "application/json",
        "X-ELS-APIKey": _api_key(),
    }


def get_json(url: str, params: dict) -> dict | None:
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=30)
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning("Rate-limited — sleeping %d s", wait)
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                raise EnvironmentError(
                    "Elsevier API returned 401 — check your ELSEVIER_API_KEY")
            resp.raise_for_status()
            return resp.json()
        except EnvironmentError:
            raise
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(10 * (attempt + 1))
    return None


# ── Abstract fetch ─────────────────────────────────────────────────────────────
def fetch_abstract(doi: str) -> str | None:
    """Fetch full abstract for a DOI via the Abstract Retrieval API."""
    url = ABSTRACT_URL.format(doi=doi)
    data = get_json(url, params={"view": "META_ABS"})
    if not data:
        return None
    try:
        return (data
                .get("abstracts-retrieval-response", {})
                .get("coredata", {})
                .get("dc:description"))
    except (AttributeError, KeyError):
        return None


# ── Search ─────────────────────────────────────────────────────────────────────
def _entry_to_record(entry: dict) -> dict:
    title      = (entry.get("dc:title") or "").strip() or None
    teaser     = (entry.get("prism:teaser") or "").strip()
    abstract   = (entry.get("prism:abstract") or "").strip()  # present for OA papers
    summary    = abstract or teaser or None
    raw_text   = (abstract or teaser or "")[:5000] or None

    creator    = (entry.get("dc:creator") or "").strip() or None
    pub_name   = (entry.get("prism:publicationName") or "").strip()
    cover_date = (entry.get("prism:coverDate") or "")[:10] or None  # YYYY-MM-DD
    doi        = (entry.get("prism:doi") or "").strip() or None

    # Canonical URL: prefer the ScienceDirect HTML link
    url = None
    for link in (entry.get("link") or []):
        if link.get("@ref") == "scidir":
            url = link.get("@href")
            break
    if not url and doi:
        url = f"https://doi.org/{doi}"

    return {
        "_doi":           doi,
        "_teaser_len":    len(teaser),
        "_pub_name":      pub_name,
        "title":          title,
        "organisation":   creator,
        "date_published": cover_date,
        "summary":        (summary or "")[:500] or None,
        "raw_text":       raw_text,
        "url":            url,
    }


def search_papers(query: str) -> list[dict]:
    papers = []
    start  = 0

    while len(papers) < MAX_RESULTS_PER_QUERY:
        params = {
            "query":   query,
            "count":   BATCH_SIZE,
            "start":   start,
            "sort":    "date",
        }
        data = get_json(SEARCH_URL, params)
        if not data:
            break

        results    = data.get("search-results", {})
        total_str  = results.get("opensearch:totalResults", "0")
        total      = int(total_str) if str(total_str).isdigit() else 0
        entries    = results.get("entry", [])

        if not entries:
            break

        batch = [_entry_to_record(e) for e in entries]
        papers.extend(batch)
        logger.info("  '%s': fetched %d (offset %d / %d)",
                    query[:55], len(entries), start, total)

        if start + BATCH_SIZE >= total or len(entries) < BATCH_SIZE:
            break

        start += BATCH_SIZE
        time.sleep(DELAY_BETWEEN_PAGES)

    return papers


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    try:
        _api_key()   # fail fast if key missing
    except EnvironmentError as e:
        logger.error("%s", e)
        sys.exit(1)

    seen_urls: set[str]     = set()
    all_records: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Query %d/%d: %s", i + 1, len(SEARCH_QUERIES), query)
        papers = search_papers(query)
        new = 0
        for paper in papers:
            url = paper.get("url") or paper.get("_doi") or ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_records.append(paper)
                new += 1
        logger.info("  → %d new (total unique: %d)", new, len(all_records))
        time.sleep(DELAY_BETWEEN_QUERIES)

    logger.info("Collected %d unique papers across %d queries",
                len(all_records), len(SEARCH_QUERIES))

    if dry_run:
        for r in all_records:
            pub = r.pop("_pub_name", "") or ""
            r.pop("_doi", None); r.pop("_teaser_len", None)
            print(f"  [{(r.get('title') or '?')[:75]}]")
            print(f"    {r.get('date_published', '?')}  {pub[:50]}  {r.get('url', '')[:60]}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for record in all_records:
        doi        = record.pop("_doi", None)
        teaser_len = record.pop("_teaser_len", 999)
        record.pop("_pub_name", None)

        if not record.get("title"):
            skipped += 1
            continue

        # Upgrade teaser → full abstract if the teaser is too short for LLM filter
        if teaser_len < MIN_TEASER_LEN and doi and not dry_run:
            abstract = fetch_abstract(doi)
            if abstract:
                record["summary"]  = abstract[:500]
                record["raw_text"] = abstract[:5000]
            time.sleep(DELAY_BETWEEN_PAGES)

        attempted += 1
        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SOURCE_URL,
        })

        if not is_ai_journalism_relevant(
            record.get("title", ""),
            record.get("summary", ""),
            record.get("raw_text", ""),
        ):
            skipped += 1
            logger.debug("  ✗ not relevant: %s", (record.get("title") or "")[:80])
            time.sleep(0.3)
            continue

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + %s", (record.get("title") or "")[:80])

        time.sleep(0.5)

    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape ScienceDirect for AI-in-journalism papers")
    parser.add_argument("--dry-run", action="store_true",
                        help="List papers without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
