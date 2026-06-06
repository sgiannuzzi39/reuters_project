"""
scraper_gni.py
--------------
scrapes the google news initiative case studies page.
all story slugs are in the initial html — no js rendering needed.

    python scraper_gni.py
    python scraper_gni.py --dry-run
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

logger = logging.getLogger("gni")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── config ─────────────────────────────────────────────────────────────────────
BASE_URL     = "https://newsinitiative.withgoogle.com"
LISTING_URL  = BASE_URL + "/resources/stories/"
SOURCE_NAME  = "Google News Initiative"
SOURCE_CAT   = "Industry"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_MONTH_YEAR = re.compile(
    r'\b(January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+(20\d{2})\b'
)


# ── helpers ────────────────────────────────────────────────────────────────────
def get(url: str) -> requests.Response | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s — %s", attempt + 1, url, e)
            time.sleep(5 * (attempt + 1))
    return None


def _parse_date(text: str) -> str | None:
    m = _MONTH_YEAR.search(text)
    if not m:
        return None
    try:
        return dateutil_parser.parse(m.group(0)).strftime("%Y-%m")
    except Exception:
        return None


# ── listing page ───────────────────────────────────────────────────────────────
def fetch_story_slugs() -> list[str]:
    """return unique story slugs from the listing page."""
    resp = get(LISTING_URL)
    if not resp:
        logger.error("Could not fetch GNI listing page")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    slug_re = re.compile(r'^/resources/stories/([^/]+)/$')
    slugs = []
    seen = set()
    for a in soup.find_all("a", href=slug_re):
        href = a["href"]
        if href not in seen:
            seen.add(href)
            slugs.append(href)

    logger.info("Found %d unique story slugs on listing page", len(slugs))
    return slugs


# ── story page ─────────────────────────────────────────────────────────────────
def parse_story(slug_path: str) -> dict:
    """fetch a gni story page and return a record dict."""
    url = BASE_URL + slug_path
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    # strip " - Google News Initiative" suffix from og:title
    og_title_el = soup.find("meta", property="og:title")
    og_title = (og_title_el.get("content", "") if og_title_el else "").strip()
    title = re.sub(r'\s*-\s*Google News Initiative\s*$', '', og_title) or None

    # separator helps parse the breadcrumb: "All Case Studies | Month YYYY | Org | ..."
    full_text = soup.get_text(separator=" | ", strip=True)

    # org + date from breadcrumb
    organisation = None
    date_published = _parse_date(full_text)

    m = re.search(
        r'All Case Studies\s*\|\s*'
        r'(?:' + _MONTH_YEAR.pattern + r')\s*\|\s*'
        r'(.+?)\s*\|\s*',
        full_text
    )
    if m:
        organisation = m.group(3).strip() or None   # group 3 = org (after month + year groups)

    # body text from <main>
    main = soup.find("main") or soup.find("article") or soup.body
    paras = []
    if main:
        for p in main.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 60:
                paras.append(txt)

    raw_text = "\n\n".join(paras)
    summary  = paras[0][:500] if paras else (og_title or None)

    return {
        "url":            url,
        "title":          title,
        "organisation":   organisation,
        "date_published": date_published,
        "summary":        summary,
        "raw_text":       raw_text[:5000],
    }


# ── main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    slugs = fetch_story_slugs()
    if not slugs:
        return

    conn      = None if dry_run else get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for i, slug_path in enumerate(slugs):
        logger.info("[%d/%d] %s", i + 1, len(slugs), slug_path)
        record = parse_story(slug_path)

        if not record.get("title"):
            skipped += 1
            logger.debug("  ✗ no title: %s", slug_path)
            time.sleep(1)
            continue

        if dry_run:
            print(f"  [{record.get('title', '?')[:70]}]")
            print(f"    org: {record.get('organisation', '?')}  date: {record.get('date_published', '?')}")
            time.sleep(0.5)
            continue

        attempted += 1
        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      LISTING_URL,
        })

        if not is_ai_journalism_relevant(
            record.get("title", ""),
            record.get("summary", ""),
            record.get("raw_text", ""),
        ):
            skipped += 1
            logger.debug("  ✗ not relevant: %s", record.get("title", "")[:80])
            time.sleep(1)
            continue

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + %s", record.get("title", "")[:80])

        time.sleep(1.5)

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape Google News Initiative case studies for AI use cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="List stories without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
