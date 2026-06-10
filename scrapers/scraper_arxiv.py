\
\
\
\
\
\
\
\
   

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("arxiv")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

                                                                                 
API_URL     = "http://export.arxiv.org/api/query"
SOURCE_URL  = "https://arxiv.org/search/"
SOURCE_NAME = "arXiv"
SOURCE_CAT  = "Academic"

BATCH_SIZE             = 100                            
MAX_RESULTS_PER_QUERY  = 300                  
DELAY_BETWEEN_PAGES    = 3.0                              
DELAY_BETWEEN_QUERIES  = 5.0

                                                                 
SEARCH_QUERIES = [
    'all:journalism AND all:"artificial intelligence"',
    'all:journalism AND all:"machine learning"',
    'all:journalism AND all:"deep learning"',
    'all:journalism AND all:"large language model"',
    'all:journalism AND all:"generative AI"',
    'all:journalism AND all:GPT',
    'all:journalism AND all:NLP',
    'all:newsroom AND all:"artificial intelligence"',
    'all:newsroom AND all:"machine learning"',
    'all:newsroom AND all:"language model"',
    'all:newsroom AND all:"generative AI"',
    'all:"news organization" AND all:"artificial intelligence"',
    'all:"news organization" AND all:"machine learning"',
    'all:"news media" AND all:"machine learning"',
    'all:"news media" AND all:"artificial intelligence"',
    'all:"fake news" AND all:detection',
    'all:misinformation AND all:detection AND all:news',
    'all:"fact-checking" AND all:"machine learning"',
    'all:"news recommendation" AND all:"machine learning"',
    'all:"media bias" AND all:"machine learning"',
]


                                                                                 
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}


def get(params: dict) -> BeautifulSoup | None:
                                                                      
    for attempt in range(3):
        try:
            resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning("Rate-limited — sleeping %d s", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "xml")
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(10 * (attempt + 1))
    return None


                                                                                 
def _arxiv_id(raw_id: str) -> str:
                                                              
    m = re.search(r"arxiv\.org/abs/([^v]+)", raw_id)
    return m.group(1) if m else raw_id


def _parse_entry(entry) -> dict:
    title_el = entry.find("title")
    title = title_el.get_text(strip=True) if title_el else None

    summary_el = entry.find("summary")
    abstract = summary_el.get_text(strip=True) if summary_el else ""

    published_el = entry.find("published")
    date_published = None
    if published_el:
        raw = published_el.get_text(strip=True)
        date_published = raw[:10] if raw else None                    

    authors = [a.find("name").get_text(strip=True)
               for a in entry.find_all("author") if a.find("name")]
    author_str = ", ".join(authors[:5])
    if len(authors) > 5:
        author_str += " et al."

                                                       
    url = None
    for link in entry.find_all("link"):
        if link.get("rel") == "alternate" or link.get("type") == "text/html":
            url = link.get("href")
            break
    if not url:
        id_el = entry.find("id")
        url = id_el.get_text(strip=True) if id_el else None

                                       
    id_el = entry.find("id")
    paper_id = _arxiv_id(id_el.get_text(strip=True)) if id_el else None

    return {
        "_paper_id":      paper_id,
        "title":          title,
        "organisation":   author_str or None,
        "date_published": date_published,
        "summary":        abstract[:500] if abstract else None,
        "raw_text":       abstract[:5000] if abstract else None,
        "url":            url,
    }


def _total_results(soup: BeautifulSoup) -> int:
    el = soup.find("totalResults")
    try:
        return int(el.get_text(strip=True)) if el else 0
    except ValueError:
        return 0


                                                                                 
def search_papers(query: str) -> list[dict]:
    papers = []
    start  = 0

    while len(papers) < MAX_RESULTS_PER_QUERY:
        params = {
            "search_query": query,
            "start":        start,
            "max_results":  BATCH_SIZE,
            "sortBy":       "submittedDate",
            "sortOrder":    "descending",
        }
        soup = get(params)
        if not soup:
            break

        entries = soup.find_all("entry")
        if not entries:
            break

        total = _total_results(soup)
        papers.extend(_parse_entry(e) for e in entries)
        logger.info("  '%s': fetched %d (offset %d / %d available)",
                    query[:60], len(entries), start, total)

        if start + BATCH_SIZE >= total or len(entries) < BATCH_SIZE:
            break

        start += BATCH_SIZE
        time.sleep(DELAY_BETWEEN_PAGES)

    return papers


                                                                                 
def scrape(dry_run: bool = False) -> None:
    seen_ids: set[str]      = set()
    all_records: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Query %d/%d: %s", i + 1, len(SEARCH_QUERIES), query)
        papers = search_papers(query)
        new = 0
        for paper in papers:
            pid = paper.get("_paper_id") or paper.get("url") or ""
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_records.append(paper)
                new += 1
        logger.info("  → %d new (total unique: %d)", new, len(all_records))
        time.sleep(DELAY_BETWEEN_QUERIES)

    logger.info("Collected %d unique papers across %d queries",
                len(all_records), len(SEARCH_QUERIES))

    if dry_run:
        for r in all_records:
            print(f"  [{(r.get('title') or '?')[:75]}]")
            print(f"    {r.get('date_published', '?')}  {r.get('url', '')[:80]}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for record in all_records:
        record.pop("_paper_id", None)

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
        description="Scrape arXiv API for AI-in-journalism papers")
    parser.add_argument("--dry-run", action="store_true",
                        help="List papers without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
