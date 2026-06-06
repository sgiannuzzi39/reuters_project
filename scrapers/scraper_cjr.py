"""
scraper_cjr.py
--------------
scrapes cjr.org via wordpress sitemaps (search/tag pages are js-rendered).
filters slugs by ai keywords, then fetches each matched article.

    python scraper_cjr.py
    python scraper_cjr.py --dry-run
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

logger = logging.getLogger("cjr")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://www.cjr.org"
SOURCE_NAME = "Columbia Journalism Review"
SOURCE_CAT  = "Industry"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}

# post sitemaps (12 pages × 2000 articles) plus tow center reports
SITEMAPS = (
    [f"{BASE_URL}/wp-sitemap-posts-post-{i}.xml" for i in range(1, 13)]
    + [f"{BASE_URL}/wp-sitemap-posts-tow_center_reports-1.xml"]
)

# slug fragments checked against the full url path
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
    "llm-",
    "-llm",
    "ai-journalism",
    "ai-newsroom",
    "ai-news",
    "journalism-ai",
    "newsroom-ai",
]


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


def fetch_ai_urls_from_sitemaps() -> list[tuple[str, str]]:
    """return (url, lastmod) pairs for cjr articles with ai-related slugs."""
    results = []
    for sitemap_url in SITEMAPS:
        resp = get(sitemap_url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "xml")
        for url_tag in soup.find_all("url"):
            loc     = url_tag.find("loc")
            lastmod = url_tag.find("lastmod")
            if not loc:
                continue
            href    = loc.get_text().strip()
            mod     = lastmod.get_text().strip()[:10] if lastmod else None
            if any(kw in href.lower() for kw in AI_SLUG_KEYWORDS):
                results.append((href, mod))

        logger.info("  %s → %d AI-slug matches so far", sitemap_url.split("/")[-1], len(results))
        time.sleep(1)

    return results


def _parse_date(text: str) -> str | None:
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_article_page(url: str, lastmod: str | None = None) -> dict:
    """fetch a cjr article page and extract metadata + body text."""
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else None

    date_tag = soup.select_one(".date")
    date_pub = _parse_date(date_tag.get_text(strip=True)) if date_tag else None
    # fall back to sitemap lastmod if the page has no visible date
    if not date_pub and lastmod:
        date_pub = lastmod

    author_tag = soup.select_one(".author")
    author = author_tag.get_text(strip=True).lstrip("By").strip() if author_tag else None

    body_div = soup.select_one(".entry-content")
    raw_text = body_div.get_text(separator="\n", strip=True) if body_div else ""

    # first non-empty paragraph as summary
    summary = ""
    if body_div:
        for p in body_div.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 80:
                summary = txt
                break

    return {
        "title":          title,
        "date_published": date_pub,
        "organisation":   author,
        "summary":        summary[:500] if summary else None,
        "raw_text":       raw_text[:5000],
    }


# ── main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    logger.info("Scanning CJR sitemaps for AI-related article URLs…")
    ai_urls = fetch_ai_urls_from_sitemaps()
    logger.info("Found %d candidate URLs", len(ai_urls))

    if dry_run:
        for url, lastmod in ai_urls:
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
            logger.debug("  ✗ no title extracted: %s", url)
            skipped += 1
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

    logger.info("[CJR] %d relevance-filtered or no-title out", skipped)
    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape CJR for AI-in-journalism articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="List matched URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
