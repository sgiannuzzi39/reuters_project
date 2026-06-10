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
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, is_ai_journalism_relevant, log_summary

logger = logging.getLogger("generativeainewsroom")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

                                                                                 
BASE_URL    = "https://generative-ai-newsroom.com"
SITEMAP_URL = BASE_URL + "/sitemap/sitemap.xml"
FEED_URL    = BASE_URL + "/feed/tagged/{tag}"
SOURCE_NAME = "Generative AI Newsroom"
SOURCE_CAT  = "Academic"

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


def _canonical_url(url: str) -> str:
                                                                          
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query=""))


def _parse_date(text: str) -> str | None:
    try:
        return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _body_from_encoded(html: str) -> tuple[str, str]:
                                                                      
    soup = BeautifulSoup(html, "html.parser")
    paras = []
    for tag in soup.find_all(["p", "h2", "h3", "h4", "li"]):
        txt = tag.get_text(strip=True)
        if len(txt) > 40:
            paras.append(txt)

    raw_text = "\n\n".join(paras)
    summary = paras[0][:500] if paras else None
    return summary, raw_text[:5000]


                                                                                 
def fetch_tag_slugs() -> list[str]:
                                                             
    resp = get(SITEMAP_URL)
    if not resp:
        logger.error("Could not fetch sitemap")
        return []

    soup = BeautifulSoup(resp.text, "xml")
    slugs = []
    for loc in soup.find_all("loc"):
        url = loc.get_text(strip=True)
        m = re.match(r"https://generative-ai-newsroom\.com/tagged/(.+)$", url)
        if m:
            slugs.append(m.group(1))

    logger.info("Found %d tag slugs in sitemap", len(slugs))
    return slugs


                                                                                 
def fetch_tag_feed(tag: str) -> list[dict]:
                                                          
    url = FEED_URL.format(tag=tag)
    resp = get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "xml")
    records = []

    for item in soup.find_all("item"):
        link_el = item.find("link")
                                                                      
        raw_url = (link_el.get_text(strip=True)
                   if link_el and link_el.get_text(strip=True)
                   else (link_el.next_sibling or "").strip()
                   if link_el else "")
        if not raw_url:
            continue
                                                                        
        article_url = _canonical_url(raw_url)

        title_el = item.find("title")
        title = title_el.get_text(strip=True) if title_el else None

        creator_el = item.find("creator")                                          
        author = creator_el.get_text(strip=True) if creator_el else None

        pub_el = item.find("pubDate")
        date_published = _parse_date(pub_el.get_text(strip=True)) if pub_el else None

        tags = [c.get_text(strip=True) for c in item.find_all("category")]

        encoded_el = item.find("encoded")                   
        summary, raw_text = ("", "") if not encoded_el else _body_from_encoded(
            encoded_el.get_text())

        records.append({
            "url":            article_url,
            "title":          title,
            "organisation":   author,
            "date_published": date_published,
            "tags":           tags,
            "summary":        summary,
            "raw_text":       raw_text,
        })

    return records


                                                                                 
def scrape(dry_run: bool = False) -> None:
    tag_slugs = fetch_tag_slugs()
    if not tag_slugs:
        logger.error("No tags found — aborting")
        return

                                                  
    seen_urls: set[str] = set()
    all_records: list[dict] = []

    for i, tag in enumerate(tag_slugs):
        logger.info("Fetching feed for tag '%s' (%d/%d)…", tag, i + 1, len(tag_slugs))
        items = fetch_tag_feed(tag)
        new = 0
        for item in items:
            url = item["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                all_records.append(item)
                new += 1
        logger.info("  %d new (total unique: %d)", new, len(all_records))
        time.sleep(0.5)

    logger.info("Collected %d unique articles from %d tag feeds", len(all_records), len(tag_slugs))

    if dry_run:
        for r in all_records:
            tags_str = ", ".join(r.get("tags") or [])
            print(f"  [{(r.get('title') or '?')[:60]}]  {r['url']}")
            print(f"    tags: {tags_str[:80]}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for record in all_records:
        if not record.get("title"):
            skipped += 1
            logger.debug("  ✗ no title: %s", record.get("url", ""))
            continue

        attempted += 1
        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      BASE_URL + "/all?topic=generative-ai-use-cases",
        })

        if not is_ai_journalism_relevant(
            record.get("title", ""),
            record.get("summary", ""),
            record.get("raw_text", ""),
        ):
            skipped += 1
            logger.debug("  ✗ not relevant: %s", record.get("title", "")[:80])
            time.sleep(0.3)
            continue

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + %s", record.get("title", "")[:80])

        time.sleep(1.0)

    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape Generative AI Newsroom via tag RSS feeds")
    parser.add_argument("--dry-run", action="store_true",
                        help="List articles without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
