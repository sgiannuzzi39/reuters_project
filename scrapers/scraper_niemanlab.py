"""
scraper_niemanlab.py
--------------------
Scrapes Nieman Lab (niemanlab.org) for articles about AI in journalism.
Uses search-based HTML scraping with requests + BeautifulSoup.

Usage:
    python scraper_niemanlab.py
    python scraper_niemanlab.py --max-pages 10 --query "artificial intelligence"
"""

import argparse
import logging
import time

import requests
from bs4 import BeautifulSoup

from scraper_base import get_db, insert_use_case, log_summary

logger = logging.getLogger("niemanlab")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://www.niemanlab.org"
SEARCH_URL  = "https://www.niemanlab.org/?s={query}&paged={page}"
SOURCE_NAME = "Nieman Lab"
SOURCE_CAT  = "Industry"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}

DEFAULT_QUERIES = [
    "artificial intelligence",
    "AI newsroom",
    "machine learning journalism",
    "automated journalism",
    "generative AI news",
]


# ── Helpers ─────────────────────────────────────────────────────────────────────
def get_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.warning("Request failed for %s: %s", url, e)
        return None


def parse_article_page(url: str) -> dict:
    """Fetch a single article and extract full text + metadata."""
    soup = get_soup(url)
    if not soup:
        return {}

    # Published date — Nieman Lab uses <time> with datetime attr
    time_tag  = soup.find("time")
    date_pub  = time_tag.get("datetime", "")[:10] if time_tag else None

    # Author — used as a proxy; not the news org
    author_tag = soup.select_one(".post-author a, .byline a, .author a")
    author     = author_tag.get_text(strip=True) if author_tag else None

    # Body text
    body_div = soup.select_one(".article-body, .entry-content, #content article")
    raw_text = body_div.get_text(separator="\n", strip=True) if body_div else ""

    # Try to extract the news organisation from the text (rough heuristic)
    # LLM will do this properly in Phase 3; we just grab the first 1000 chars here
    return {
        "date_published": date_pub,
        "organisation":   author,          # Phase 3 LLM will refine this
        "raw_text":       raw_text[:5000], # cap at 5 000 chars
    }


def parse_search_results(soup: BeautifulSoup, query: str) -> list[dict]:
    """Parse a search results page and return a list of partial records."""
    records = []

    # Nieman Lab search results are article cards
    articles = soup.select("article, .post-item, .search-result")
    if not articles:
        # Fallback: any <h2> with a link inside the main content
        articles = soup.select("main h2, .entry-title")

    for art in articles:
        link_tag = art.find("a", href=True) if art.name != "a" else art
        if not link_tag:
            continue

        href  = link_tag["href"]
        if not href.startswith("http"):
            href = BASE_URL + href

        # Skip tag/category pages
        if any(x in href for x in ["/tag/", "/category/", "/author/"]):
            continue

        title_tag = art.find(["h2", "h3", "h1"])
        title     = title_tag.get_text(strip=True) if title_tag else link_tag.get_text(strip=True)

        excerpt_tag = art.select_one("p, .excerpt, .entry-summary")
        summary     = excerpt_tag.get_text(strip=True) if excerpt_tag else ""

        records.append({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SEARCH_URL.format(query=query, page=1),
            "title":           title,
            "url":             href,
            "summary":         summary[:500],
        })

    return records


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(queries: list[str] | None = None, max_pages: int = 5) -> None:
    if queries is None:
        queries = DEFAULT_QUERIES

    conn      = get_db()
    attempted = 0
    inserted  = 0

    for query in queries:
        logger.info("Searching Nieman Lab for: %r", query)
        query_enc = query.replace(" ", "+")

        for page in range(1, max_pages + 1):
            url  = SEARCH_URL.format(query=query_enc, page=page)
            soup = get_soup(url)

            if not soup:
                logger.info("No page found at %s — stopping for this query", url)
                break

            partial_records = parse_search_results(soup, query_enc)
            if not partial_records:
                logger.info("No articles on page %d for %r — stopping", page, query)
                break

            for partial in partial_records:
                attempted += 1

                # Fetch the full article for richer text
                detail = parse_article_page(partial["url"])
                record = {**partial, **detail}  # detail fields override partial where set

                if insert_use_case(conn, record):
                    inserted += 1
                    logger.info("  + %s", record.get("title", "")[:80])

                time.sleep(1.5)   # polite delay between article fetches

            time.sleep(2)         # delay between pages

    log_summary(SOURCE_NAME, attempted, inserted)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Nieman Lab for AI-in-journalism articles")
    parser.add_argument("--max-pages", type=int, default=5,
                        help="Max search result pages per query (default 5)")
    parser.add_argument("--query", type=str, default=None,
                        help="Single custom query (overrides defaults)")
    args = parser.parse_args()

    queries = [args.query] if args.query else None
    scrape(queries=queries, max_pages=args.max_pages)
