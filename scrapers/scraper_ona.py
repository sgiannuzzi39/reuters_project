"""
scraper_ona.py
--------------
Scrapes the ONA "AI in the Newsroom" case study series.
https://www.journalists.org/ai-in-the-newsroom-case-studies

There are 10 case studies on the landing page, each with a "Read more" link
to a detail page with the full case study text.

Usage:
    python scraper_ona.py
"""

import logging
import time
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, log_summary

logger = logging.getLogger("ona")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
LANDING_URL = "https://www.journalists.org/ai-in-the-newsroom-case-studies"
BASE_URL    = "https://www.journalists.org"
SOURCE_NAME = "ONA AI in the Newsroom"
SOURCE_CAT  = "Database"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; dissertation-research-bot/1.0; "
        "+https://ox.ac.uk) AppleWebKit/537.36"
    )
}

# Known case studies from the landing page — used as fallback if scraping
# the landing page fails, since there are only 10 and they are fixed.
KNOWN_CASES = [
    {
        "title": "Djinn, an AI-powered Data Journalism Interface",
        "organisation": "iTromsø / Polaris Media",
        "country": "Norway",
        "date_published": "2024-08",
    },
    {
        "title": "How Hearst Newspapers built an AI-powered, Slack-based Tool to Help with Digital Content Production",
        "organisation": "Hearst Newspapers",
        "country": "United States",
        "date_published": "2024-08",
    },
    {
        "title": "Enhancing Fact-Checking with AI at Der Spiegel",
        "organisation": "Der Spiegel",
        "country": "Germany",
        "date_published": "2024-08",
    },
    {
        "title": "Transforming Workflows with AI at Zamaneh Media",
        "organisation": "Zamaneh Media",
        "country": "Netherlands",
        "date_published": "2024-09",
    },
    {
        "title": "Building AI Literacy at Canada's National Public Broadcaster Radio-Canada",
        "organisation": "Radio-Canada",
        "country": "Canada",
        "date_published": "2024-09",
    },
    {
        "title": "How Bayerischer Rundfunk Used Modular Journalism to Personalize Radio News Based on Location",
        "organisation": "Bayerischer Rundfunk",
        "country": "Germany",
        "date_published": "2024-09",
    },
    {
        "title": "Sweden's Aftonbladet Built AI-Driven Editorial Tools and an Election Chatbot",
        "organisation": "Aftonbladet",
        "country": "Sweden",
        "date_published": "2024-10",
    },
    {
        "title": "THE CITY's AI-Powered Coverage Audit and Navigation Tool",
        "organisation": "THE CITY",
        "country": "United States",
        "date_published": "2024-10",
    },
    {
        "title": "Using AI to Analyze Open-Source Intelligence in Ukraine War Reporting",
        "organisation": "BBC World Service",
        "country": "United Kingdom",
        "date_published": "2024-10",
    },
    {
        "title": "How The Times of India Brings Real-Time Personalization to 1,500+ Daily News Stories",
        "organisation": "Times of India",
        "country": "India",
        "date_published": "2024-10",
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.warning("Request failed for %s: %s", url, e)
        return None


def parse_landing_page(soup: BeautifulSoup) -> list[dict]:
    """
    Extract case study titles, summaries, and 'Read more' links
    from the ONA landing page.
    """
    cases = []

    # Each case study is likely in an article or section block
    # Try several selectors
    blocks = (
        soup.select("article") or
        soup.select(".case-study") or
        soup.select(".resource-item") or
        soup.select("section .entry") or
        []
    )

    for block in blocks:
        title_tag = block.find(["h2", "h3", "h4"])
        title     = title_tag.get_text(strip=True) if title_tag else ""

        link_tag  = block.find("a", href=True)
        href      = ""
        if link_tag:
            href = link_tag["href"]
            if href.startswith("/"):
                href = BASE_URL + href

        summary_tag = block.find("p")
        summary     = summary_tag.get_text(strip=True) if summary_tag else ""

        if title or href:
            cases.append({"title": title, "url": href, "summary": summary})

    return cases


def parse_detail_page(url: str) -> dict:
    """Fetch a case study detail page and extract full text + metadata."""
    soup = get_soup(url)
    if not soup:
        return {}

    # Full body text
    body = (
        soup.select_one("main article") or
        soup.select_one(".entry-content") or
        soup.select_one("main") or
        soup.select_one("body")
    )
    raw_text = body.get_text(separator="\n", strip=True) if body else ""

    # Date — look for a time tag or "Date posted" text
    date_pub = None
    time_tag = soup.find("time")
    if time_tag:
        date_pub = time_tag.get("datetime", "")[:10]
    else:
        # Look for "Date posted" followed by a date string
        for tag in soup.find_all(string=lambda t: t and "Date posted" in t):
            parent = tag.find_parent()
            if parent:
                sibling = parent.find_next_sibling()
                if sibling:
                    date_pub = sibling.get_text(strip=True)
                    break

    return {
        "raw_text":      raw_text[:6000],
        "date_published": date_pub,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape() -> None:
    conn      = get_db()
    attempted = 0
    inserted  = 0

    # Try to scrape the landing page for links
    logger.info("Fetching ONA landing page: %s", LANDING_URL)
    soup  = get_soup(LANDING_URL)
    cases = parse_landing_page(soup) if soup else []

    # If landing page scrape found nothing useful, fall back to known list
    if not cases:
        logger.warning("Could not parse landing page — using known case list")
        cases = [{"title": c["title"], "url": "", "summary": ""} for c in KNOWN_CASES]

    # Merge known metadata (org, country) with scraped data where possible
    known_by_title = {c["title"].lower(): c for c in KNOWN_CASES}

    for case in cases:
        attempted += 1
        title   = case.get("title", "")
        url     = case.get("url", "")
        summary = case.get("summary", "")

        # Look up known metadata
        known = known_by_title.get(title.lower(), {})
        org     = known.get("organisation")
        country = known.get("country")

        # Fetch detail page for full text and date
        detail = {}
        if url and url.startswith("http"):
            logger.info("Fetching detail page: %s", url)
            detail = parse_detail_page(url)
            time.sleep(1.5)

        # Build raw_text — combine summary + detail
        raw_text = detail.get("raw_text") or f"Title: {title}\n\nSummary: {summary}"

        record = {
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      LANDING_URL,
            "title":           title or None,
            "organisation":    org,
            "country":         country,
            "date_published":  detail.get("date_published"),
            "url":             url or None,
            "summary":         summary[:500] or None,
            "raw_text":        raw_text,
        }

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + [%s] %s", country or "?", title[:70])

    # If landing page gave us nothing, insert from known list directly
    if attempted == 0 or not cases:
        logger.info("Inserting from known case list directly")
        for known in KNOWN_CASES:
            attempted += 1
            record = {
                "source_name":     SOURCE_NAME,
                "source_category": SOURCE_CAT,
                "source_url":      LANDING_URL,
                "title":           known["title"],
                "organisation":    known["organisation"],
                "country":         known["country"],
                "date_published":  None,
                "url":             None,
                "summary":         None,
                "raw_text":        f"Title: {known['title']}\nOrganisation: {known['organisation']}\nCountry: {known['country']}",
            }
            if insert_use_case(conn, record):
                inserted += 1

    log_summary(SOURCE_NAME, attempted, inserted)
    conn.close()


if __name__ == "__main__":
    scrape()