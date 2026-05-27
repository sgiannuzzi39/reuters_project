"""
scraper_reutersinstitute_news.py
---------------------------------
Scrapes the Reuters Institute general journalism news feed
(reutersinstitute.politics.ox.ac.uk/news?review_types=45) for articles
about AI use cases in journalism.

This is a separate scraper from scraper_reutersinstitute.py because the
listing page differs: it uses article.review-article cards (not
article.search-result) and paginates via ?review_types=45&page=N.

The feed is broad (~1 285 articles going back to 2013) and covers all
journalism topics.  A title/teaser keyword pre-filter (word-boundary
regex) discards obviously non-AI articles before fetching full pages or
calling the LLM, keeping API usage efficient.  The LLM relevance filter
then makes the final call on borderline cases.

Usage:
    python scraper_reutersinstitute_news.py
    python scraper_reutersinstitute_news.py --dry-run
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

logger = logging.getLogger("reutersinstitute_news")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL     = "https://reutersinstitute.politics.ox.ac.uk"
LISTING_URL  = BASE_URL + "/news?review_types=45"
SOURCE_NAME  = "Reuters Institute"
SOURCE_CAT   = "Academic"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}

# Word-boundary patterns that signal an AI use-case article.
# Using \b ensures "ai" matches standalone "AI" but not "said", "Israel", "failed".
_AI_PATTERN = re.compile(
    r"\b("
    r"a\.?i\b"
    r"|artificial\s+intel"
    r"|generative\s+ai|gen(?:erative)?[-\s]?ai"
    r"|machine\s+learn"
    r"|chatgpt|gpt[-\s]?\d"
    r"|large\s+language\s+model|llm"
    r"|newsbot|robo[-\s]?report|robot\s+journalist"
    r"|deepfake"
    r"|news\s+automat|automat\w*\s+journalism"
    r"|ai[-\s]generated|ai[-\s]powered|ai[-\s]driven"
    r")",
    re.IGNORECASE,
)


def _looks_ai_relevant(title: str, teaser: str) -> bool:
    """Return True if the title or teaser contains an AI keyword."""
    return bool(_AI_PATTERN.search(title or "") or _AI_PATTERN.search(teaser or ""))


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


def _date_from_url(url: str) -> str | None:
    m = re.search(r"/(\d{4})/(\d{2})/", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


# ── Listing page ───────────────────────────────────────────────────────────────
def fetch_listing_page(page: int) -> list[dict]:
    """
    Return partial records from one listing page.

    Card structure (article.review-article.listing-page):
      a.full-block[href]                      → article URL
      .fb-wrap > span                         → title (bare span, not h3)
      .news-date                              → publication date
      .field--name-field-feature-box-body     → teaser paragraph
    """
    url = LISTING_URL if page == 0 else f"{LISTING_URL}&page={page}"
    resp = get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    records = []

    for card in soup.find_all("article", class_="review-article"):
        a = card.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href:
            continue
        full_url = href if href.startswith("http") else BASE_URL + href

        # Title lives in a bare <span> inside .fb-wrap, not in an h3
        title = None
        fb_wrap = card.select_one(".fb-wrap")
        if fb_wrap:
            span = fb_wrap.find("span", recursive=False) or fb_wrap.find("span")
            if span:
                title = span.get_text(strip=True) or None

        date_el = card.select_one(".news-date")
        date_published = _parse_date(date_el.get_text(strip=True)) if date_el else None

        teaser_el = card.select_one(".field--name-field-feature-box-body")
        teaser = teaser_el.get_text(strip=True) if teaser_el else ""

        records.append({
            "url":            full_url,
            "title":          title,
            "date_published": date_published,
            "summary":        teaser[:500] if teaser else None,
        })

    return records


# ── Article page ───────────────────────────────────────────────────────────────
def parse_article(url: str) -> dict:
    """
    Fetch a RISJ article and extract structured metadata.

    Drupal fields (consistent across all RISJ node types):
      .field--name-node-title     → headline
      .field--name-field-sub-     → subtitle / standfirst
      .field--name-field-date     → publication date
      .field--name-field-authors  → author(s)
      .main-container p           → body paragraphs
    """
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    # Title
    title = None
    node_title = soup.select_one(".field--name-node-title")
    if node_title:
        title = node_title.get_text(strip=True) or None
    if not title:
        for h in soup.find_all(["h1", "h2"]):
            t = h.get_text(strip=True)
            if t and t.lower() not in ("breadcrumb", "news"):
                title = t
                break

    # Date
    date_el = soup.select_one(".field--name-field-date") or soup.select_one("time")
    date_published = _parse_date(date_el.get_text(strip=True)) if date_el else None
    if not date_published:
        date_published = _date_from_url(url)

    # Author
    author_el = soup.select_one(".field--name-field-authors")
    author = author_el.get_text(strip=True) if author_el else None

    # Standfirst / subtitle
    sub_el = soup.select_one('[class*="field--name-field-sub-"]')
    summary = sub_el.get_text(strip=True)[:500] if sub_el else None

    # Body paragraphs
    main = soup.select_one(".main-container")
    body_paras = []
    if main:
        for p in main.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 60 and "REUTERS/" not in txt:
                body_paras.append(txt)

    raw_text = "\n\n".join(body_paras)

    if not summary and body_paras:
        summary = body_paras[0][:500]

    return {
        "title":          title,
        "organisation":   author,   # Phase-3 LLM will extract the actual news org
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

    page = 0
    while True:
        logger.info("Fetching listing page %d…", page)
        partial_records = fetch_listing_page(page)

        if not partial_records:
            logger.info("No articles on page %d — stopping", page)
            break

        for partial in partial_records:
            url   = partial["url"]
            title = partial.get("title") or ""
            teaser = partial.get("summary") or ""

            # Cheap pre-filter: skip articles with no AI keywords in title/teaser.
            # This avoids fetching full pages and burning LLM quota on clearly
            # non-AI articles (the majority of this broad feed).
            if not _looks_ai_relevant(title, teaser):
                logger.debug("  – pre-filter skip: %s", title[:70])
                continue

            if dry_run:
                print(f"  [{title[:65]}]  {url}")
                continue

            attempted += 1
            detail = parse_article(url)

            # Merge: prefer non-None values from the article page, but keep
            # listing-card values as fallbacks so a failed article fetch
            # never silently drops the title or date we already have.
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

        page += 1
        if not dry_run:
            time.sleep(2)

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape Reuters Institute news feed for AI-in-journalism articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="List AI-candidate URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
