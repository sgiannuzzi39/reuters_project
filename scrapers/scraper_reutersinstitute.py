"""
scraper_reutersinstitute.py
----------------------------
scrapes the risj ai & journalism taxonomy page (/taxonomy/term/296?page=N).
all drupal node types share the same field selectors so one parser handles all.

    python scraper_reutersinstitute.py
    python scraper_reutersinstitute.py --dry-run
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

logger = logging.getLogger("reutersinstitute")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── config ─────────────────────────────────────────────────────────────────────
BASE_URL      = "https://reutersinstitute.politics.ox.ac.uk"
TAXONOMY_URL  = BASE_URL + "/taxonomy/term/296"
SOURCE_NAME   = "Reuters Institute"
SOURCE_CAT    = "Academic"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}


# ── helpers ────────────────────────────────────────────────────────────────────
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


def _date_from_url(url: str) -> str | None:
    """extract yyyy-mm from a url like /2026/05/slug."""
    m = re.search(r"/(\d{4})/(\d{2})/", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


# ── listing page ───────────────────────────────────────────────────────────────
def fetch_listing_page(page: int) -> list[dict]:
    """return partial records from one taxonomy listing page."""
    url = TAXONOMY_URL if page == 0 else f"{TAXONOMY_URL}?page={page}"
    resp = get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    records = []

    for article in soup.find_all("article", class_="search-result"):
        a = article.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href:
            continue
        full_url = href if href.startswith("http") else BASE_URL + href

        title_el = article.select_one("h3")
        title = title_el.get_text(strip=True) if title_el else None

        body_el = article.select_one(".fb--body")
        teaser = body_el.get_text(strip=True) if body_el else ""

        records.append({
            "url":     full_url,
            "title":   title,
            "summary": teaser[:500] if teaser else None,
        })

    return records


# ── article page ───────────────────────────────────────────────────────────────
def parse_article(url: str) -> dict:
    """fetch a risj page and extract metadata."""
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    # ── title ─────────────────────────────────────────────────────────────────
    title = None
    node_title = soup.select_one(".field--name-node-title")
    if node_title:
        title = node_title.get_text(strip=True)
    if not title:
        for h in soup.find_all(["h1", "h2"]):
            t = h.get_text(strip=True)
            if t and t.lower() not in ("breadcrumb", "news"):
                title = t
                break

    # ── date ──────────────────────────────────────────────────────────────────
    date_el = soup.select_one(".field--name-field-date") or soup.select_one("time")
    date_published = _parse_date(date_el.get_text(strip=True)) if date_el else None
    if not date_published:
        date_published = _date_from_url(url)

    # ── author ────────────────────────────────────────────────────────────────
    author_el = soup.select_one(".field--name-field-authors")
    author = author_el.get_text(strip=True) if author_el else None

    # ── summary ───────────────────────────────────────────────────────────────
    sub_el = soup.select_one('[class*="field--name-field-sub-"]')
    summary = sub_el.get_text(strip=True)[:500] if sub_el else None

    # ── body text ─────────────────────────────────────────────────────────────
    main = soup.select_one(".main-container")
    body_paras = []
    if main:
        for p in main.find_all("p"):
            txt = p.get_text(strip=True)
            # skip captions (short lines with REUTERS/ credit)
            if len(txt) > 60 and "REUTERS/" not in txt:
                body_paras.append(txt)

    raw_text = "\n\n".join(body_paras)

    # fall back to first body paragraph if no standfirst
    if not summary and body_paras:
        summary = body_paras[0][:500]

    return {
        "title":          title,
        "organisation":   author,   # phase 3 llm extracts the actual news org
        "date_published": date_published,
        "summary":        summary,
        "raw_text":       raw_text[:5000],
    }


# ── main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    conn      = None if dry_run else get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    page = 0
    while True:
        logger.info("Fetching listing page %d…", page)
        partial_records = fetch_listing_page(page)

        if not partial_records:
            logger.info("No results on page %d — stopping", page)
            break

        for partial in partial_records:
            url = partial["url"]

            if dry_run:
                print(f"  [{partial.get('title','?')[:60]}]  {url}")
                continue

            attempted += 1
            detail = parse_article(url)
            record = {**partial, **detail}

            if not record.get("title"):
                skipped += 1
                logger.debug("  ✗ no title: %s", url)
                time.sleep(0.5)
                continue

            # prefer article-page summary; fall back to listing teaser
            if not record.get("summary") and partial.get("summary"):
                record["summary"] = partial["summary"]

            record.update({
                "source_name":     SOURCE_NAME,
                "source_category": SOURCE_CAT,
                "source_url":      TAXONOMY_URL,
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
        description="Scrape Reuters Institute AI & Journalism taxonomy for use cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="List article URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
