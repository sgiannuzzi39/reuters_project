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
import warnings
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dateutil import parser as dateutil_parser

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("journalism_co_uk")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

                                                                                 
BASE_URL    = "https://www.journalism.co.uk"
SITEMAP_URL = "https://www.journalism.co.uk/sitemap-posts.xml"
SOURCE_NAME = "Journalism.co.uk"
SOURCE_CAT  = "Industry"

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
    "automated-",
    "automation",
    "algorithm",
    "deepfake",
    "openai",
    "ai-tool",
    "ai-in-",
    "ai-for-",
    "-with-ai",
    "using-ai",
    "ai-newsroom",
    "ai-journalism",
    "ai-news",
    "newsroom-ai",
    "journalist-ai",
    "robot-report",
    "robo-report",
]

                                                         
_NOISE = {"unsubscribe", "sign up", "subscribe", "no spam", "email sent"}


                                                                                 
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


def fetch_ai_urls_from_sitemap() -> list[tuple[str, str | None]]:
                                                                      
    logger.info("Fetching sitemap from %s …", SITEMAP_URL)
    resp = get(SITEMAP_URL)
    if not resp:
        logger.error("Could not fetch sitemap")
        return []

    soup = BeautifulSoup(resp.text, "xml")
    results = []
    for url_tag in soup.find_all("url"):
        loc     = url_tag.find("loc")
        lastmod = url_tag.find("lastmod")
        if not loc:
            continue
        href = loc.get_text().strip()
        mod  = lastmod.get_text().strip()[:10] if lastmod else None
        if any(kw in href.lower() for kw in AI_SLUG_KEYWORDS):
            results.append((href, mod))

    logger.info("Found %d AI-slug matches from %d total sitemap URLs",
                len(results),
                len(soup.find_all("url")))
    return results


def _parse_date(text: str) -> str | None:
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_article_page(url: str, lastmod: str | None = None) -> dict:
                                                                            
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")

    title_tag = soup.select_one("h1")
    title = title_tag.get_text(strip=True) if title_tag else None

                                                           
    time_tag = soup.find("time")
    date_pub  = time_tag.get("datetime", "")[:10] if time_tag else None
    if not date_pub:
        date_pub = _parse_date(time_tag.get_text()) if time_tag else None
    if not date_pub and lastmod:
        date_pub = lastmod

    art = soup.find("article")
    raw_text = ""
    summary  = ""
    if art:
        clean_paras = []
        for p in art.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 50 and not any(n in txt.lower() for n in _NOISE):
                clean_paras.append(txt)
        raw_text = "\n".join(clean_paras)
        summary  = clean_paras[0] if clean_paras else ""

    return {
        "title":          title,
        "date_published": date_pub,
        "organisation":   None,                                                                            
        "summary":        summary[:500] if summary else None,
        "raw_text":       raw_text[:5000],
    }


                                                                                 
def scrape(dry_run: bool = False) -> None:
    ai_urls = fetch_ai_urls_from_sitemap()

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
        description="Scrape Journalism.co.uk for AI-in-journalism articles via sitemap")
    parser.add_argument("--dry-run", action="store_true",
                        help="List matched URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
