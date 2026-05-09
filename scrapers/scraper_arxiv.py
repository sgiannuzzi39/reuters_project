"""
scraper_arxiv.py
----------------
Scrapes arXiv for papers on AI in journalism using the arXiv API.
No scraping restrictions — this uses the official arXiv API.
 
Usage:
    python scraper_arxiv.py
    python scraper_arxiv.py --max-results 200 --query "AI newsroom"
"""
 
import argparse
import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
 
import requests
 
from scraper_base import get_db, insert_use_case, log_summary
 
logger = logging.getLogger("arxiv")
 
# ── Config ─────────────────────────────────────────────────────────────────────
ARXIV_API   = "https://export.arxiv.org/api/query"
SOURCE_NAME = "arXiv"
SOURCE_CAT  = "Academic"
SOURCE_URL  = "https://arxiv.org/search/?query=journalism+AI&searchtype=all"
 
# Namespace used in arXiv Atom feeds
NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv":   "http://arxiv.org/schemas/atom",
}
 
DEFAULT_QUERIES = [
    "journalism artificial intelligence",
    "AI newsroom",
    "news automation natural language processing",
    "computational journalism",
    "news recommendation deep learning",
]
 
 
# ── Fetch ──────────────────────────────────────────────────────────────────────
def fetch_arxiv_page(query: str, start: int, max_results: int) -> ET.Element:
    params = {
        "search_query": f"all:{query}",
        "start":        start,
        "max_results":  max_results,
        "sortBy":       "submittedDate",
        "sortOrder":    "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    logger.info("Fetching arXiv: start=%d  query=%r", start, query)
 
    for attempt in range(5):
        resp = requests.get(url, timeout=30)
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)  # 30s, 60s, 90s ...
            logger.warning("Rate limited (429) — waiting %ds before retry %d/5", wait, attempt + 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return ET.fromstring(resp.text)
 
    raise RuntimeError("arXiv API returned 429 after 5 retries — try again in a few minutes")
 
 
def parse_entries(root: ET.Element) -> list[dict]:
    records = []
    for entry in root.findall("atom:entry", NS):
        title      = (entry.findtext("atom:title", "", NS) or "").strip().replace("\n", " ")
        summary    = (entry.findtext("atom:summary", "", NS) or "").strip().replace("\n", " ")
        published  = (entry.findtext("atom:published", "", NS) or "")[:10]  # YYYY-MM-DD
        url        = (entry.findtext("atom:id", "", NS) or "").strip()
 
        # Authors → use the first as a proxy for "organisation" (no news org here)
        authors = entry.findall("atom:author", NS)
        first_author = authors[0].findtext("atom:name", "", NS) if authors else ""
 
        # Categories / subject tags
        cats = [c.get("term", "") for c in entry.findall("atom:category", NS)]
 
        records.append({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SOURCE_URL,
            "title":           title,
            "organisation":    first_author,   # closest proxy available
            "country":         None,           # not available in arXiv metadata
            "date_published":  published,
            "url":             url,
            "summary":         summary[:1000], # cap for DB storage
            "raw_text":        f"Title: {title}\n\nAbstract: {summary}\n\nCategories: {', '.join(cats)}",
        })
    return records
 
 
# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(queries: list[str] | None = None, max_results: int = 100) -> None:
    if queries is None:
        queries = DEFAULT_QUERIES
 
    conn      = get_db()
    attempted = 0
    inserted  = 0
    page_size = 50   # arXiv recommends ≤100 per request; 50 is safe
 
    for query in queries:
        start = 0
        fetched_this_query = 0
 
        while fetched_this_query < max_results:
            batch = min(page_size, max_results - fetched_this_query)
            root  = fetch_arxiv_page(query, start, batch)
 
            entries = parse_entries(root)
            if not entries:
                logger.info("No more results for query %r", query)
                break
 
            for record in entries:
                attempted += 1
                if insert_use_case(conn, record):
                    inserted += 1
 
            fetched_this_query += len(entries)
            start              += len(entries)
 
            # Be polite — arXiv requests a 3-second gap between calls
            time.sleep(3)
 
            if len(entries) < batch:
                break   # fewer results than requested = last page
 
    log_summary(SOURCE_NAME, attempted, inserted)
    conn.close()
 
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape arXiv for AI-in-journalism papers")
    parser.add_argument("--max-results", type=int, default=100,
                        help="Max results per query (default 100)")
    parser.add_argument("--query", type=str, default=None,
                        help="Single custom query (overrides defaults)")
    args = parser.parse_args()
 
    queries = [args.query] if args.query else None
    scrape(queries=queries, max_results=args.max_results)