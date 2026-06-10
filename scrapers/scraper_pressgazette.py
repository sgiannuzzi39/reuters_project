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
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("pressgazette")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

                                                                                 
BASE_URL    = "https://pressgazette.co.uk"
SUBJECT_URL = "https://pressgazette.co.uk/subject/artificial-intelligence/"
PAGE_URL    = "https://pressgazette.co.uk/subject/artificial-intelligence/page/{page}/"
SOURCE_NAME = "Press Gazette"
SOURCE_CAT  = "Industry"
MAX_PAGES   = 39                                     

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}


                                                                                 
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
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_listing_page(soup: BeautifulSoup) -> list[dict]:
                                                                 
    records = []
    for art in soup.select("article.c-story"):
        title_tag = art.select_one("h3 a, h2 a")
        if not title_tag:
            continue

        href  = title_tag.get("href", "")
        title = title_tag.get_text(strip=True)
        if not href.startswith("http"):
            href = BASE_URL + href

        excerpt_tag = art.select_one(".c-story__standfirst, .c-story__excerpt, p")
        summary = excerpt_tag.get_text(strip=True) if excerpt_tag else ""

        records.append({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SUBJECT_URL,
            "title":           title,
            "url":             href,
            "summary":         summary[:500],
        })
    return records


def fetch_article_detail(url: str) -> dict:
                                                                         
    soup = get_soup(url)
    if not soup:
        return {}

    date_tag = soup.select_one(".c-date__published, .c-date, .meta-item")
    date_pub = _parse_date(date_tag.get_text(strip=True)) if date_tag else None

    author_tag = soup.select_one(".c-author__name a, .c-author__name")
    author = author_tag.get_text(strip=True) if author_tag else None

    body_div = soup.select_one(".c-article-content__container")
    raw_text = body_div.get_text(separator="\n", strip=True) if body_div else ""

    return {
        "date_published": date_pub,
        "organisation":   author,
        "raw_text":       raw_text[:5000],
    }


                                                                                 
def scrape(max_pages: int = MAX_PAGES, dry_run: bool = False) -> None:
    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0
    all_cards = []

                                                      
    for page in range(1, max_pages + 1):
        url  = SUBJECT_URL if page == 1 else PAGE_URL.format(page=page)
        soup = get_soup(url)
        if not soup:
            logger.info("Page %d returned nothing — stopping", page)
            break

        cards = parse_listing_page(soup)
        if not cards:
            logger.info("No articles on page %d — stopping", page)
            break

        logger.info("Page %d/%d — %d cards", page, max_pages, len(cards))
        all_cards.extend(cards)
        time.sleep(1)

    logger.info("Total cards collected: %d", len(all_cards))

    if dry_run:
        for card in all_cards:
            print(f"  {card['url']}")
        return

    for card in all_cards:
        attempted += 1

                                                                    
        if not is_ai_journalism_relevant(card["title"], card.get("summary", "")):
            skipped += 1
            logger.debug("  ✗ card-filtered: %s", card["title"][:80])
            continue

        detail = fetch_article_detail(card["url"])
        record = {**card, **detail}

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + %s", record.get("title", "")[:80])

        time.sleep(1.5)

    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape Press Gazette AI subject page for use cases")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES,
                        help=f"Max listing pages to crawl (default {MAX_PAGES}, ~8 articles each)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List article URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(max_pages=args.max_pages, dry_run=args.dry_run)
