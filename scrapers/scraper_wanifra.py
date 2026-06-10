\
\
\
\
\
\
\
\
\
   

import argparse
import html
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

logger = logging.getLogger("wanifra")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

                                                                                 
BASE_URL       = "https://wan-ifra.org"
CATEGORY_URL   = "https://wan-ifra.org/category/media-innovation/page/{page}/"
SOURCE_NAME    = "WAN-IFRA"
SOURCE_CAT     = "Industry"
DEFAULT_MAX_PAGES = 500

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


def _extract_ld_article(soup: BeautifulSoup) -> dict:
                                                                         
    tag = soup.find("script", attrs={"type": "application/ld+json"})
    if not tag:
        return {}
    try:
        data = json.loads(tag.get_text())
    except json.JSONDecodeError:
        return {}
    graph = data if isinstance(data, dict) else {}
                                                              
    if "@graph" in graph:
        for node in graph["@graph"]:
            if node.get("@type") == "Article":
                return node
    if graph.get("@type") == "Article":
        return graph
    return {}


def _extract_organisation(keywords: list[str], author: str) -> str | None:
                                                                                     
    generic = {
        "ai", "artificial intelligence", "machine learning", "generative ai",
        "chatgpt", "openai", "wan-ifra", "wan-ifra ai catalyst",
        "ai in media", "ai transformation", "media innovation",
    }
    for kw in keywords:
        if kw.lower() in generic:
            continue
                                                              
        if any(c.isupper() for c in kw) and (" " in kw or len(kw) > 6):
            return kw
    return None


                                                                                 
def fetch_listing_page(page: int) -> list[dict]:
                                                                            
    url = CATEGORY_URL.format(page=page)
    resp = get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    records = []

    for post in soup.find_all("div", class_="post"):
        a = post.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href:
            continue

        h1 = post.select_one("h1")
        title = h1.get_text(strip=True) if h1 else None

        p_tag = post.select_one("p")
        teaser = p_tag.get_text(strip=True) if p_tag else ""

        records.append({
            "url":     href,
            "title":   title,
            "summary": teaser[:500] if teaser else None,
        })

    return records


                                                                                 
def parse_article(url: str) -> dict:
                                                                    
    resp = get(url)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    ld = _extract_ld_article(soup)

                                                                           
    raw_headline = ld.get("headline", "")
    title = html.unescape(raw_headline) if raw_headline else None
    if not title:
        h1s = soup.find_all("h1")
                                                                            
        for h1 in h1s:
            t = h1.get_text(strip=True)
            if t and t.lower() != "news":
                title = t
                break

    date_published = _parse_date(ld.get("datePublished", ""))

    author_info = ld.get("author", {})
    author = author_info.get("name") if isinstance(author_info, dict) else None

    keywords = ld.get("keywords") or []

    organisation = _extract_organisation(keywords, author or "")

                                                                           
    content_div = soup.select_one("div.content")
    body_paras = []
    if content_div:
        paras = content_div.find_all("p")
        for p in paras[1:]:                          
            txt = p.get_text(strip=True)
            if txt:
                body_paras.append(txt)

    raw_text = "\n\n".join(body_paras)

    return {
        "title":          title,
        "organisation":   organisation,
        "date_published": date_published,
        "raw_text":       raw_text[:5000],
    }


                                                                                 
def scrape(max_pages: int = DEFAULT_MAX_PAGES, dry_run: bool = False) -> None:
    conn      = None if dry_run else get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for page in range(1, max_pages + 1):
        logger.info("Fetching listing page %d/%d…", page, max_pages)
        partial_records = fetch_listing_page(page)

        if not partial_records:
            logger.info("No posts on page %d — reached end of category, stopping", page)
            break

        for partial in partial_records:
            url = partial["url"]

            if dry_run:
                print(f"  {url}")
                continue

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
                "source_url":      CATEGORY_URL.format(page=page),
                "url":             url,
            })

                                                                                   
            if not record.get("summary") and partial.get("summary"):
                record["summary"] = partial["summary"]

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

        if not dry_run:
            time.sleep(2)

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape WAN-IFRA media-innovation category for AI use cases")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                        help=f"Max listing pages to fetch (default {DEFAULT_MAX_PAGES})")
    parser.add_argument("--dry-run", action="store_true",
                        help="List article URLs without inserting into the DB")
    args = parser.parse_args()
    scrape(max_pages=args.max_pages, dry_run=args.dry_run)
