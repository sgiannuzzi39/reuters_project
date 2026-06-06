"""
scraper_niemanlab.py
--------------------
scrapes niemanlab.org via search pagination.

    python scraper_niemanlab.py
    python scraper_niemanlab.py --max-pages 10 --query "artificial intelligence"
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("niemanlab")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://www.niemanlab.org"
# pagination format discovered by inspecting next-page links
SEARCH_URL  = "https://www.niemanlab.org/page/{page}/?s={query}"
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


# ── helpers ─────────────────────────────────────────────────────────────────────
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


def _parse_date(text: str) -> str | None:
    """parse nieman lab date strings like 'Feb.  27, 2023, 12:45 p.m.' → '2023-02-27'."""
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_article_page(url: str) -> dict:
    """fetch a nieman lab page and extract metadata + text."""
    soup = get_soup(url)
    if not soup:
        return {}

    # ── "what we're reading" template (/reading/ urls) ─────────────────────
    wwr = soup.select_one(".wwr-full-item")
    if wwr:
        # external article url
        ext_link = wwr.select_one(".wwr-full-link")
        ext_url  = ext_link.get("href") if ext_link else url

        # flag text format: "Publication / Authors / Date"
        flag_tag = wwr.select_one(".wwr-full-flag")
        organisation = None
        date_pub = None
        if flag_tag:
            # remove the inner span (contains date) to get just "Pub / Authors"
            flag_span = flag_tag.find("span")
            date_text = flag_span.get_text(strip=True).lstrip("/").strip() if flag_span else ""
            date_pub  = _parse_date(date_text)
            if flag_span:
                flag_span.decompose()
            flag_text    = flag_tag.get_text(strip=True)
            organisation = flag_text.split("/")[0].strip() or None

        deck_tag = wwr.select_one(".wwr-full-deck")
        summary  = deck_tag.get_text(strip=True) if deck_tag else ""
        # strip "— LO" editor-initials suffix
        summary  = summary.rsplit("—", 1)[0].strip().strip('"').strip("'")

        return {
            "url":           ext_url,
            "date_published": date_pub,
            "organisation":  organisation,
            "summary":       summary[:500] if summary else None,
            "raw_text":      summary[:5000],
        }

    # ── original nieman lab article template (/YYYY/MM/ urls) ──────────────
    date_tag = soup.select_one(".simple-bylinedate")
    date_pub = _parse_date(date_tag.get_text(strip=True)) if date_tag else None

    author_tag = soup.select_one(".bylineauthorname")
    author = author_tag.get_text(strip=True) if author_tag else None

    deck_tag  = soup.select_one(".simple-post-deck")
    deck      = deck_tag.get_text(strip=True) if deck_tag else ""

    body_div  = soup.select_one(".simple-body")
    body_text = body_div.get_text(separator="\n", strip=True) if body_div else ""

    raw_text = "\n\n".join(filter(None, [deck, body_text]))

    return {
        "date_published": date_pub,
        "organisation":   author,   # phase 3 llm extracts the actual news org
        "summary":        deck[:500] if deck else None,
        "raw_text":       raw_text[:5000],
    }


def parse_search_results(soup: BeautifulSoup, query: str) -> list[dict]:
    """parse a nieman lab search results page and return partial records."""
    records = []

    # card class found by inspecting the live page
    cards = soup.select("div.simple-loop-article")

    for card in cards:
        link_tag = card.select_one(".simple-loop-headline a")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        if not href.startswith("http"):
            href = BASE_URL + href

        if any(x in href for x in ["/tag/", "/category/", "/author/", "/page/"]):
            continue

        title = link_tag.get_text(strip=True)

        # date visible on the card
        date_tag = card.select_one(".simple-loop-date")
        card_date = _parse_date(date_tag.get_text(strip=True)) if date_tag else None

        records.append({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SEARCH_URL.format(query=query, page=1),
            "title":           title,
            "url":             href,
            "summary":         "",
            "date_published":  card_date,
        })

    return records


# ── main ───────────────────────────────────────────────────────────────────────
def scrape(queries: list[str] | None = None, max_pages: int = 5) -> None:
    if queries is None:
        queries = DEFAULT_QUERIES

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for query in queries:
        logger.info("Searching Nieman Lab for: %r", query)
        query_enc = query.replace(" ", "+")

        for page in range(1, max_pages + 1):
            # page 1 doesn't use /page/1/ — that returns a 404
            if page == 1:
                url = f"{BASE_URL}/?s={query_enc}"
            else:
                url = SEARCH_URL.format(query=query_enc, page=page)
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

                detail = parse_article_page(partial["url"])
                record = {**partial, **detail}

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

            time.sleep(2)

    logger.info("[Nieman Lab] %d relevance-filtered out", skipped)
    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
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
