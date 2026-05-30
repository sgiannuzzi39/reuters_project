"""
scraper_sage.py
---------------
Scrapes SAGE Journals for academic papers about AI use cases in journalism,
using the CrossRef REST API.

journals.sagepub.com is behind Cloudflare and cannot be scraped directly.
The CrossRef API (api.crossref.org) provides full metadata — titles, abstracts,
DOIs, dates — for all SAGE Publications journals (DOI prefix 10.1177) without
any authentication.

CrossRef polite-pool: include a mailto address in requests for higher rate
limits (50 req/s vs unauthenticated). No key needed.

Rate limits: very generous with mailto — 1 req/s is well within limits.

Usage:
    python scraper_sage.py
    python scraper_sage.py --dry-run
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("sage")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
CROSSREF_URL           = "https://api.crossref.org/works"
CROSSREF_MAILTO        = "sgiannuzzi39@gmail.com"   # polite-pool access
SAGE_DOI_PREFIX        = "10.1177"                   # SAGE Publications prefix

SOURCE_URL             = "https://journals.sagepub.com"
SOURCE_NAME            = "SAGE Journals"
SOURCE_CAT             = "Academic"

ROWS_PER_PAGE          = 100
MAX_RESULTS_PER_QUERY  = 500
DELAY_BETWEEN_PAGES    = 1.5
DELAY_BETWEEN_QUERIES  = 3.0

SEARCH_QUERIES = [
    "journalism artificial intelligence",
    "journalism machine learning",
    "journalism deep learning",
    "journalism large language model",
    "journalism generative AI",
    "newsroom artificial intelligence",
    "newsroom automation",
    "newsroom machine learning",
    "computational journalism",
    "automated journalism",
    "automated news writing",
    "news recommendation machine learning",
    "fact checking artificial intelligence",
    "misinformation detection machine learning",
    "fake news detection deep learning",
    "media bias machine learning",
    "news summarization NLP",
    "journalism natural language processing",
]

# ── JATS XML stripper ──────────────────────────────────────────────────────────
_JATS_RE = re.compile(r"<[^>]+>")

def _strip_jats(text: str) -> str:
    """Remove JATS XML tags from CrossRef abstracts."""
    return _JATS_RE.sub("", text).strip()


# ── HTTP helper ────────────────────────────────────────────────────────────────
def get_json(params: dict) -> dict | None:
    params["mailto"] = CROSSREF_MAILTO
    for attempt in range(4):
        try:
            resp = requests.get(CROSSREF_URL, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning("Rate-limited — sleeping %d s", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(10 * (attempt + 1))
    return None


# ── Record parser ──────────────────────────────────────────────────────────────
def _parse_work(work: dict) -> dict | None:
    title_list = work.get("title") or []
    title = title_list[0].strip() if title_list else None
    if not title:
        return None

    doi = work.get("DOI", "").strip() or None
    url = f"https://doi.org/{doi}" if doi else None

    # Abstract: strip JATS XML tags if present
    raw_abstract = work.get("abstract") or ""
    abstract = _strip_jats(raw_abstract) if raw_abstract else ""

    # Authors: join first 3 as a string
    authors = work.get("author") or []
    author_names = [
        " ".join(filter(None, [a.get("given", ""), a.get("family", "")]))
        for a in authors[:3]
    ]
    author_str = "; ".join(author_names) or None

    # Journal name
    journal = ((work.get("container-title") or [""])[0]).strip() or None

    # Publication date: prefer print date, fall back to online/created
    date_parts = (
        (work.get("published-print") or work.get("published-online") or work.get("created") or {})
        .get("date-parts", [[]])
    )
    parts = date_parts[0] if date_parts else []
    if len(parts) >= 3:
        date_published = f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    elif len(parts) == 2:
        date_published = f"{parts[0]:04d}-{parts[1]:02d}"
    elif len(parts) == 1:
        date_published = str(parts[0])
    else:
        date_published = None

    # raw_text for LLM filter
    parts_text = [f"Title: {title}"]
    if journal:
        parts_text.append(f"Journal: {journal}")
    if abstract:
        parts_text.append(f"Abstract: {abstract}")
    raw_text = "\n".join(parts_text)[:5000]

    return {
        "title":          title,
        "organisation":   author_str,
        "date_published": date_published,
        "url":            url,
        "summary":        abstract[:500] if abstract else None,
        "raw_text":       raw_text,
    }


# ── Search ─────────────────────────────────────────────────────────────────────
def search_sage(query: str) -> list[dict]:
    works = []
    offset = 0

    while len(works) < MAX_RESULTS_PER_QUERY:
        params = {
            "query.bibliographic": query,
            "filter":  f"prefix:{SAGE_DOI_PREFIX},type:journal-article",
            "rows":    ROWS_PER_PAGE,
            "offset":  offset,
            "select":  "DOI,title,abstract,author,published-print,published-online,created,container-title",
        }
        data = get_json(params)
        if not data:
            break

        message = data.get("message", {})
        total   = message.get("total-results", 0)
        items   = message.get("items", [])
        if not items:
            break

        works.extend(items)
        logger.info("  '%s': fetched %d (offset %d / %d)",
                    query[:55], len(items), offset, total)

        if offset + ROWS_PER_PAGE >= min(total, MAX_RESULTS_PER_QUERY):
            break
        if len(items) < ROWS_PER_PAGE:
            break

        offset += ROWS_PER_PAGE
        time.sleep(DELAY_BETWEEN_PAGES)

    return works


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    seen_dois: set[str]     = set()
    all_records: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Query %d/%d: '%s'", i + 1, len(SEARCH_QUERIES), query)
        works = search_sage(query)
        new = 0
        for work in works:
            doi = (work.get("DOI") or "").strip()
            key = doi or (work.get("title") or [""])[0]
            if key and key not in seen_dois:
                seen_dois.add(key)
                record = _parse_work(work)
                if record:
                    all_records.append(record)
                    new += 1
        logger.info("  → %d new (total unique: %d)", new, len(all_records))
        time.sleep(DELAY_BETWEEN_QUERIES)

    logger.info("Collected %d unique SAGE papers across %d queries",
                len(all_records), len(SEARCH_QUERIES))

    if dry_run:
        for r in all_records:
            print(f"  [{(r.get('title') or '?')[:75]}]")
            print(f"    {r.get('date_published', '?')}  {(r.get('summary') or '')[:80]}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    filtered  = 0

    for record in all_records:
        if not record.get("title"):
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
            filtered += 1
            logger.debug("  ✗ not relevant: %s", (record.get("title") or "")[:80])
            time.sleep(0.2)
            continue

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + %s", (record.get("title") or "")[:80])

        time.sleep(0.3)

    log_summary(SOURCE_NAME, attempted, inserted, filtered=filtered)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape SAGE Journals via CrossRef API for AI-in-journalism papers")
    parser.add_argument("--dry-run", action="store_true",
                        help="List papers without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
