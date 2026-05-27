"""
scraper_gijn.py
---------------
Scrapes GIJN (Global Investigative Journalism Network) search results for
"artificial intelligence" (gijn.org/?s=artificial+intelligence) for articles
about AI use cases in journalism.

Strategy:
  1. Page through /?s=artificial+intelligence&paged=N, stopping when a page
     returns no article cards.
  2. Collect article URLs + teasers from listing cards (WordPress article elements).
  3. Fetch each article page for structured metadata and body text.
  4. Run the LLM relevance filter before inserting into the DB.

Usage:
    python scraper_gijn.py
    python scraper_gijn.py --dry-run
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("gijn")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://gijn.org"
SEARCH_URL  = BASE_URL + "/?s=artificial+intelligence"
SOURCE_NAME = "GIJN"
SOURCE_CAT  = "Industry"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def get(url: str) -> requests.Response | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.warning("Request failed for %s: %s", url, e)
        return None


def _parse_date(text: str) -> str | None:
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


# ── Listing page ───────────────────────────────────────────────────────────────
def fetch_listing_page(page: int) -> list[dict]:
    """
    Return partial records from one search results page.

    WordPress search result cards are <article> elements.
    Title and URL live in .entry-title > a (or h2 > a / h3 > a).
    The date is in a <time> element with a datetime attribute.
    The excerpt lives in .entry-summary or .excerpt.
    """
    url = SEARCH_URL if page == 1 else f"{SEARCH_URL}&paged={page}"
    resp = get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    records = []

    for article in soup.find_all("article"):
        # Title + URL
        title_el = (article.select_one(".entry-title a") or
                    article.select_one("h2 a") or
                    article.select_one("h3 a"))
        if not title_el:
            continue
        article_url = title_el.get("href", "").strip()
        title = title_el.get_text(strip=True) or None
        if not article_url:
            continue

        # Date
        time_el = article.find("time")
        date_published = None
        if time_el:
            date_published = (_parse_date(time_el.get("datetime", "")) or
                              _parse_date(time_el.get_text(strip=True)))

        # Teaser / excerpt
        excerpt_el = (article.select_one(".entry-summary") or
                      article.select_one(".excerpt") or
                      article.select_one("p"))
        teaser = excerpt_el.get_text(strip=True) if excerpt_el else ""

        records.append({
            "url":            article_url,
            "title":          title,
            "date_published": date_published,
            "summary":        teaser[:500] if teaser else None,
        })

    return records


# ── Article page ───────────────────────────────────────────────────────────────
def parse_article(url: str) -> dict:
    """Fetch a GIJN article and extract structured metadata + body text."""
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    # Title
    title = None
    for sel in [".entry-title", "h1.post-title", "h1"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t:
                title = t
                break

    # Date
    time_el = soup.find("time")
    date_published = None
    if time_el:
        date_published = (_parse_date(time_el.get("datetime", "")) or
                          _parse_date(time_el.get_text(strip=True)))

    # Author
    author_el = (soup.select_one(".author") or
                 soup.select_one('[rel="author"]') or
                 soup.select_one(".byline"))
    author = author_el.get_text(strip=True) if author_el else None

    # Body text
    content_el = (soup.select_one(".entry-content") or
                  soup.select_one(".post-content") or
                  soup.select_one("article"))
    body_paras = []
    if content_el:
        for p in content_el.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 60:
                body_paras.append(txt)

    raw_text = "\n\n".join(body_paras)
    summary = body_paras[0][:500] if body_paras else None

    return {
        "title":          title,
        "organisation":   author,
        "date_published": date_published,
        "summary":        summary,
        "raw_text":       raw_text[:5000],
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    conn      = None if dry_run else get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    page = 1
    while True:
        logger.info("Fetching search results page %d…", page)
        partial_records = fetch_listing_page(page)

        if not partial_records:
            logger.info("No results on page %d — stopping", page)
            break

        for partial in partial_records:
            url   = partial["url"]
            title = partial.get("title") or ""

            if dry_run:
                print(f"  [{title[:65]}]  {url}")
                continue

            attempted += 1
            detail = parse_article(url)

            record = {**partial}
            for k, v in detail.items():
                if v is not None:
                    record[k] = v

            if not record.get("title"):
                skipped += 1
                logger.debug("  ✗ no title: %s", url)
                time.sleep(0.5)
                continue

            record.update({
                "source_name":     SOURCE_NAME,
                "source_category": SOURCE_CAT,
                "source_url":      SEARCH_URL,
                "url":             url,
            })

            if not is_ai_journalism_relevant(
                record.get("title", ""),
                record.get("summary", ""),
                record.get("raw_text", ""),
            ):
                skipped += 1
                logger.debug("  ✗ not relevant: %s", record.get("title", "")[:80])
                time.sleep(0.5)
                continue

            if insert_use_case(conn, record):
                inserted += 1
                logger.info("  + %s", record.get("title", "")[:80])

            time.sleep(1.5)

        page += 1
        if not dry_run:
            time.sleep(2)

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape GIJN AI search results for journalism use cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="List article URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
