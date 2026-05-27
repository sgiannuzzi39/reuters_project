"""
scraper_semanticscholar.py
--------------------------
Scrapes the Semantic Scholar API (api.semanticscholar.org) for academic papers
about AI use cases in news organisations.

Strategy:
  1. Run a curated list of search queries (each targeting a different facet of
     AI-in-journalism research) against the /graph/v1/paper/search endpoint.
  2. Paginate each query up to MAX_RESULTS_PER_QUERY results (100 per page).
  3. Deduplicate across queries by Semantic Scholar paperId.
  4. Run the standard LLM relevance filter and insert into the DB.

Authentication:
  A free API key raises the rate limit from ~1 req/s to 5 000 req/5 min.
  Register at https://www.semanticscholar.org/product/api and set:
      export SEMANTICSCHOLAR_API_KEY=<your-key>
  The scraper works without a key — it just sleeps 1 s between requests.

Usage:
    python scraper_semanticscholar.py
    python scraper_semanticscholar.py --dry-run
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

logger = logging.getLogger("semanticscholar")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
API_BASE   = "https://api.semanticscholar.org/graph/v1"
SOURCE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SOURCE_NAME = "Semantic Scholar"
SOURCE_CAT  = "Academic"

# Fields to request from the API
FIELDS = "title,authors,year,abstract,venue,publicationTypes,openAccessPdf,externalIds,url"

# Maximum papers to retrieve per query (API paginates 100 at a time)
MAX_RESULTS_PER_QUERY = 500

# Search queries covering different facets of AI use in journalism
SEARCH_QUERIES = [
    "journalism artificial intelligence",
    "journalism machine learning",
    "journalism deep learning",
    "journalism large language model",
    "journalism generative AI",
    "journalism GPT",
    "journalism NLP",
    "newsroom artificial intelligence",
    "newsroom machine learning",
    "newsroom language model",
    "newsroom generative AI",
    "news organization artificial intelligence",
    "news organization machine learning",
    "news media machine learning",
    "news media artificial intelligence",
    "fake news detection",
    "misinformation detection news",
    "fact-checking machine learning",
    "news recommendation machine learning",
    "media bias machine learning",
]


# ── HTTP helper ────────────────────────────────────────────────────────────────
def _make_headers() -> dict:
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("SEMANTICSCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _has_api_key() -> bool:
    return bool(os.environ.get("SEMANTICSCHOLAR_API_KEY"))


def get(url: str, params: dict) -> dict | None:
    headers = _make_headers()
    # Exponential backoff: up to 4 attempts with increasing waits
    wait = 30
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", wait))
                actual_wait = max(retry_after, wait)
                logger.warning("Rate-limited (attempt %d) — sleeping %d s",
                               attempt + 1, actual_wait)
                time.sleep(actual_wait)
                wait *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, e)
            if attempt < 3:
                time.sleep(wait)
                wait *= 2
    return None


# ── Search ─────────────────────────────────────────────────────────────────────
def search_papers(query: str) -> list[dict]:
    """
    Page through all results for a single query up to MAX_RESULTS_PER_QUERY.
    Returns a list of raw API paper dicts.
    """
    papers = []
    offset = 0
    limit  = 100

    while len(papers) < MAX_RESULTS_PER_QUERY:
        params = {
            "query":  query,
            "fields": FIELDS,
            "limit":  limit,
            "offset": offset,
        }
        data = get(f"{API_BASE}/paper/search", params)
        if not data:
            break

        batch = data.get("data", [])
        if not batch:
            break

        papers.extend(batch)
        logger.info("  Query '%s': fetched %d (total so far: %d / %d available)",
                    query[:50], len(batch), len(papers), data.get("total", "?"))

        # Stop if we've received everything available
        if data.get("next") is None or len(batch) < limit:
            break

        offset += limit
        # Polite delay — 3 s without key (avoid bursting the 100/5min bucket),
        # 0.2 s with an API key (5000/5min bucket)
        time.sleep(0.2 if _has_api_key() else 3.0)

    return papers


# ── Record builder ─────────────────────────────────────────────────────────────
def _build_record(paper: dict) -> dict:
    """Convert a raw Semantic Scholar paper dict into a scraper record."""
    title  = (paper.get("title") or "").strip() or None
    year   = paper.get("year")
    venue  = (paper.get("venue") or "").strip() or None

    authors = paper.get("authors") or []
    author_names = ", ".join(a.get("name", "") for a in authors[:5])
    if len(authors) > 5:
        author_names += " et al."

    abstract = (paper.get("abstract") or "").strip()
    summary  = abstract[:500] if abstract else None
    raw_text = abstract[:5000] if abstract else None

    # Prefer open-access PDF URL, fall back to Semantic Scholar page
    oa_pdf  = (paper.get("openAccessPdf") or {}).get("url")
    ss_url  = paper.get("url") or ""
    ext_ids = paper.get("externalIds") or {}
    doi     = ext_ids.get("DOI")
    doi_url = f"https://doi.org/{doi}" if doi else None
    article_url = oa_pdf or doi_url or ss_url or None

    date_published = str(year) if year else None

    return {
        "title":          title,
        "organisation":   author_names or None,
        "date_published": date_published,
        "summary":        summary,
        "raw_text":       raw_text,
        "url":            article_url,
        "_venue":         venue,   # kept for dry-run display, not in DB schema
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    if not _has_api_key():
        logger.info("No SEMANTICSCHOLAR_API_KEY found — using unauthenticated "
                    "access (1 req/s). Set the env var for faster scraping.")

    # Collect unique papers across all queries, deduped by paperId
    seen_ids: set[str]   = set()
    all_records: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Query %d/%d: '%s'", i + 1, len(SEARCH_QUERIES), query)
        papers = search_papers(query)
        new = 0
        for paper in papers:
            pid = paper.get("paperId")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_records.append(_build_record(paper))
                new += 1
        logger.info("  → %d new unique papers (total: %d)", new, len(all_records))
        time.sleep(3.0 if _has_api_key() else 5.0)

    logger.info("Collected %d unique papers across %d queries",
                len(all_records), len(SEARCH_QUERIES))

    if dry_run:
        for r in all_records:
            venue = r.pop("_venue", "") or ""
            print(f"  [{(r.get('title') or '?')[:70]}]")
            print(f"    {r.get('date_published', '?')}  {venue}  {r.get('url', '')[:80]}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for record in all_records:
        record.pop("_venue", None)

        if not record.get("title"):
            skipped += 1
            continue

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
        description="Scrape Semantic Scholar for AI-in-journalism papers")
    parser.add_argument("--dry-run", action="store_true",
                        help="List papers without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
