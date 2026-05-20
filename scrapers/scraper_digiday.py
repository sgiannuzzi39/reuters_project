"""
scraper_digiday.py
------------------
Scrapes Digiday (digiday.com) for articles about AI in journalism/media.

Digiday's topic and search pages are JavaScript-rendered — plain requests
returns no article cards. Instead this scraper uses the same sitemap approach
as scraper_cjr.py / scraper_poynter.py:
  1. Read all 30 WordPress post sitemaps to collect every article URL.
  2. Filter to URLs whose slug contains AI-related keywords (~456 matches).
  3. Fetch each matched article page (statically rendered).
  4. Run the OpenAI relevance filter before inserting into the DB.

Usage:
    python scraper_digiday.py
    python scraper_digiday.py --dry-run   # list matched URLs without inserting
    python scraper_digiday.py --start 20  # start from sitemap N (skip older ones)
"""

import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dateutil import parser as dateutil_parser

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("digiday")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://digiday.com"
SOURCE_NAME = "Digiday"
SOURCE_CAT  = "Industry"
N_SITEMAPS  = 30   # update if Digiday adds more post sitemaps

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}

AI_SLUG_KEYWORDS = [
    "artificial-intell",
    "machine-learn",
    "generative-ai",
    "chatgpt",
    "large-language",
    "neural-net",
    "natural-language",
    "automated-journalism",
    "automated-news",
    "news-automation",
    "automated-content",
    "algorithm",
    "deepfake",
    "openai",
    "ai-newsroom",
    "ai-journalism",
    "ai-news",
    "journalism-ai",
    "newsroom-ai",
    "robot-report",
    "robo-report",
    "-with-ai",
    "using-ai",
    "ai-tool",
    "ai-in-",
    "ai-for-",
    "ai-era",
    "ai-age",
    "ai-strategy",
    "ai-content",
    "ai-publisher",
    "ai-media",
    "ai-editor",
    "ai-writer",
]


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


def fetch_ai_urls_from_sitemaps(start: int = 1) -> list[tuple[str, str | None]]:
    """Return (url, lastmod) pairs for Digiday articles with AI-related slugs."""
    results = []
    for i in range(start, N_SITEMAPS + 1):
        sitemap_url = f"{BASE_URL}/wp-sitemap-posts-post-{i}.xml"
        resp = get(sitemap_url)
        if not resp:
            logger.warning("  sitemap %d — failed to fetch", i)
            continue
        soup = BeautifulSoup(resp.text, "xml")
        for url_tag in soup.find_all("url"):
            loc     = url_tag.find("loc")
            lastmod = url_tag.find("lastmod")
            if not loc:
                continue
            href = loc.get_text().strip()
            mod  = lastmod.get_text().strip()[:10] if lastmod else None
            if any(kw in href.lower() for kw in AI_SLUG_KEYWORDS):
                results.append((href, mod))

        logger.info("  sitemap %d/%d → %d AI-slug matches so far", i, N_SITEMAPS, len(results))
        time.sleep(0.5)

    return results


def _parse_date(text: str) -> str | None:
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_article_page(url: str, lastmod: str | None = None) -> dict:
    """Fetch a Digiday article and extract metadata + body text."""
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else None

    # First span.date on the page is the article's own publish date
    date_tag = soup.select_one("span.date")
    date_pub = _parse_date(date_tag.get_text(strip=True)) if date_tag else None
    if not date_pub and lastmod:
        date_pub = lastmod

    # .author contains "ByName" — strip the "By" prefix
    author_tag = soup.select_one(".author")
    author = None
    if author_tag:
        raw = author_tag.get_text(strip=True)
        author = raw.removeprefix("By").strip() or None

    # Body: extract substantive paragraphs from the content column
    body_div = soup.select_one(".content-column")
    raw_text = ""
    summary  = ""
    if body_div:
        # Remove paywall gate / newsletter / ad elements
        for el in body_div.select(".digiday-content-gate, .paywall, .sub-prompt, "
                                   ".ad, .newsletter-signup, script, style"):
            el.decompose()
        paras = [p.get_text(strip=True) for p in body_div.find_all("p")
                 if len(p.get_text(strip=True)) > 60]
        raw_text = "\n".join(paras)
        summary  = paras[0] if paras else ""

    return {
        "title":          title,
        "date_published": date_pub,
        "organisation":   author,
        "summary":        summary[:500] if summary else None,
        "raw_text":       raw_text[:5000],
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False, start: int = 1) -> None:
    logger.info("Scanning Digiday sitemaps %d–%d for AI-related article URLs…",
                start, N_SITEMAPS)
    ai_urls = fetch_ai_urls_from_sitemaps(start=start)
    logger.info("Found %d candidate URLs", len(ai_urls))

    if dry_run:
        for url, lastmod in sorted(ai_urls, key=lambda x: x[1] or "", reverse=True):
            print(f"  {lastmod or '?':10s}  {url}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for url, lastmod in ai_urls:
        attempted += 1
        record = parse_article_page(url, lastmod)

        if not record.get("title"):
            skipped += 1
            logger.debug("  ✗ no title: %s", url)
            time.sleep(0.5)
            continue

        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      url,
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
        description="Scrape Digiday for AI-in-journalism/media articles via sitemap")
    parser.add_argument("--dry-run", action="store_true",
                        help="List matched URLs without inserting into the DB")
    parser.add_argument("--start", type=int, default=1,
                        help=f"Start from sitemap N (1–{N_SITEMAPS}); use higher values to skip older content")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run, start=args.start)
