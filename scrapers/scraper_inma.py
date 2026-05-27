"""
scraper_inma.py
---------------
Scrapes the INMA Generative AI Initiative blog
(inma.org/blogs/Generative-AI-Initiative/) for AI use-case articles.

All 124 posts are explicitly about GenAI in news media, so the LLM filter
acts as a safety net rather than a heavy filter here.

Pagination uses an offset parameter: index.cfm?start=N (step 32).
Listing cards supply title, date, and author.
Article pages add body text via LD+JSON + div.article-body.

Usage:
    python scraper_inma.py
    python scraper_inma.py --dry-run
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("inma")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://www.inma.org"
BLOG_URL    = BASE_URL + "/blogs/Generative-AI-Initiative/"
SOURCE_NAME = "INMA"
SOURCE_CAT  = "Industry"
PAGE_STEP   = 32   # articles per listing page

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


def _extract_ld_article(soup: BeautifulSoup) -> dict:
    tag = soup.find("script", attrs={"type": "application/ld+json"})
    if not tag:
        return {}
    try:
        data = json.loads(tag.get_text())
        return data if data.get("@type") == "Article" else {}
    except json.JSONDecodeError:
        return {}


# ── Listing pages ──────────────────────────────────────────────────────────────
def fetch_all_listing_urls() -> list[dict]:
    """
    Walk listing pages (start=0, 32, 64, …) and collect all unique post
    partial records.  Stops when a page yields no new URLs.
    """
    seen = set()
    records = []
    start = 0

    while True:
        url = BLOG_URL if start == 0 else f"{BLOG_URL}index.cfm?start={start}"
        resp = get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "lxml")
        new_this_page = 0

        # Iterate cards directly so we always have the card context for metadata.
        # Cards are the column divs that contain a post.cfm link.
        for card in soup.find_all("div", class_=lambda c: c and "card-news" in c):
            a = card.find("a", href=lambda h: h and "/post.cfm/" in h)
            if not a:
                continue
            href = a.get("href", "")
            full_url = href if href.startswith("http") else BASE_URL + href
            if full_url in seen:
                continue
            seen.add(full_url)
            new_this_page += 1

            title_el = card.select_one(".card-title") or card.select_one("h4")
            title = title_el.get_text(strip=True) if title_el else None

            date_el = card.select_one(".post-date")
            date_published = _parse_date(date_el.get_text(strip=True)) if date_el else None

            author_el = card.select_one(".post-author")
            author = author_el.get_text(strip=True).removeprefix("By").strip() if author_el else None

            records.append({
                "url":            full_url,
                "title":          title,
                "date_published": date_published,
                "organisation":   author,
            })

        logger.info("  start=%d — %d new URLs (total %d)", start, new_this_page, len(records))

        if new_this_page == 0:
            break
        start += PAGE_STEP

    return records


# ── Article page ───────────────────────────────────────────────────────────────
def parse_article(url: str) -> dict:
    """Fetch an INMA blog post and extract body text + LD+JSON metadata."""
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    ld = _extract_ld_article(soup)

    # Title: prefer LD+JSON name, fall back to first non-empty h1
    title = ld.get("name") or None
    if not title:
        for h1 in soup.find_all("h1"):
            t = h1.get_text(strip=True)
            if t:
                title = t
                break

    date_published = _parse_date(ld.get("datePublished", "")) or None
    if not date_published:
        date_el = soup.select_one(".post-date")
        date_published = _parse_date(date_el.get_text(strip=True)) if date_el else None

    # Author(s) from LD+JSON list
    authors_raw = ld.get("author", [])
    if isinstance(authors_raw, dict):
        authors_raw = [authors_raw]
    author = ", ".join(a.get("name", "") for a in authors_raw if a.get("name")) or None

    # Body text
    body_div = soup.select_one(".article-body")
    body_paras = []
    if body_div:
        for p in body_div.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 40:
                body_paras.append(txt)

    raw_text = "\n\n".join(body_paras)

    # Summary: first substantive paragraph
    summary = body_paras[0][:500] if body_paras else None

    return {
        "title":          title,
        "organisation":   author,   # INMA staff author; Phase-3 LLM extracts news org
        "date_published": date_published,
        "summary":        summary,
        "raw_text":       raw_text[:5000],
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    logger.info("Collecting all post URLs from listing pages…")
    partial_records = fetch_all_listing_urls()
    logger.info("Found %d unique post URLs", len(partial_records))

    if dry_run:
        for r in partial_records:
            print(f"  [{(r.get('title') or '?')[:60]}]  {r['url']}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for partial in partial_records:
        url = partial["url"]
        attempted += 1

        detail = parse_article(url)
        record = {**partial, **detail}

        if not record.get("title"):
            skipped += 1
            logger.debug("  ✗ no title: %s", url)
            time.sleep(0.5)
            continue

        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      BLOG_URL,
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
        description="Scrape INMA Generative AI Initiative blog for AI use cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="List post URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
