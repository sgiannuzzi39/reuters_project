\
\
\
\
\
\
\
\
   

import argparse
import json
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

logger = logging.getLogger("editorandpublisher")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

                                                                                 
BASE_URL       = "https://www.editorandpublisher.com"
LISTING_URL    = "https://www.editorandpublisher.com/casestudies/"
SOURCE_NAME    = "Editor & Publisher"
SOURCE_CAT     = "Industry"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}


                                                                                 
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


def _extract_ld_json(soup: BeautifulSoup) -> dict:
                                                     
    tag = soup.find("script", attrs={"type": "application/ld+json"})
    if not tag:
        return {}
    try:
        return json.loads(tag.get_text())
    except json.JSONDecodeError:
        return {}


def _extract_organisation(soup: BeautifulSoup, body_text: str) -> str | None:
                                                               
    byline = soup.select_one(".byline")
    byline_text = byline.get_text(strip=True) if byline else ""

                                      
    m = re.search(r"Marketing Partner:\s*(.+)", byline_text)
    if m:
        return m.group(1).strip()

                                                 
    m = re.search(r"From:\s*([A-Z][A-Za-z0-9 &\-\.]+?)(?:\s{2,}|\n|An E&P|In a )", body_text)
    if m:
        return m.group(1).strip()

    return None


                                                                                 
def fetch_case_study_urls() -> list[str]:
                                                                     
    resp = get(LISTING_URL)
    if not resp:
        logger.error("Could not fetch listing page: %s", LISTING_URL)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    urls = []
    for item in soup.find_all("div", class_="content-item"):
        a = item.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href or href in ("/", "#"):
            continue
        full_url = href if href.startswith("http") else BASE_URL + href
        if full_url not in urls:
            urls.append(full_url)

    logger.info("Found %d case study URLs on listing page", len(urls))
    return urls


                                                                                 
def parse_article(url: str) -> dict:
                                                                      
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    ld = _extract_ld_json(soup)

    title = ld.get("headline") or (
        soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else None
    )
    summary = ld.get("description") or None
    date_published = ld.get("datePublished") or _parse_date(
        soup.select_one(".byline").get_text(strip=True)
        if soup.select_one(".byline") else ""
    )

    body_div = soup.select_one("div.body.main-body")
    raw_text = body_div.get_text(separator="\n", strip=True) if body_div else ""

    organisation = _extract_organisation(soup, raw_text)

    if not summary and raw_text:
        for line in raw_text.split("\n"):
            if len(line.strip()) > 80:
                summary = line.strip()[:500]
                break

    return {
        "title":          title,
        "organisation":   organisation,
        "date_published": date_published,
        "summary":        summary[:500] if summary else None,
        "raw_text":       raw_text[:5000],
    }


                                                                                 
def scrape(dry_run: bool = False) -> None:
    urls = fetch_case_study_urls()
    if not urls:
        logger.error("No URLs found — aborting")
        return

    if dry_run:
        for url in urls:
            print(f"  {url}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for url in urls:
        attempted += 1
        record = parse_article(url)

        if not record.get("title"):
            skipped += 1
            logger.debug("  ✗ no title: %s", url)
            time.sleep(0.5)
            continue

        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      LISTING_URL,
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

    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape Editor & Publisher case studies for AI use cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="List case study URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
