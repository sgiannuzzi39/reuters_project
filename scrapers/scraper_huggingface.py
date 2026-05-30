"""
scraper_huggingface.py
----------------------
Scrapes the JournalistsonHF HuggingFace organisation for AI tools and spaces
built by or for news organisations.

The organisation's activity page (huggingface.co/organizations/JournalistsonHF/
activity/all) is a JS-rendered social feed — too noisy and hard to paginate.
Instead this scraper uses the HuggingFace Hub REST API to:

  1. Fetch all ~400 members of the JournalistsonHF org.
  2. Fetch every Space created by each member.
  3. Include the org's own Spaces directly.
  4. For each Space, fetch the README for richer context.
  5. Run a HuggingFace-specific OpenAI prompt that asks whether the Space
     represents an AI tool used by or built for a specific news organisation
     or journalist workflow.

No API key required — the Hub API is public for non-gated content.

Usage:
    python scraper_huggingface.py
    python scraper_huggingface.py --dry-run
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, log_summary
from openai import OpenAI

logger = logging.getLogger("huggingface")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
HF_API       = "https://huggingface.co/api"
ORG          = "JournalistsonHF"
SOURCE_URL   = f"https://huggingface.co/organizations/{ORG}/activity/all"
SOURCE_NAME  = "HuggingFace (JournalistsonHF)"
SOURCE_CAT   = "Industry"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dissertation-research-bot/1.0)"}
DELAY   = 0.5   # seconds between API calls


# ── HuggingFace-specific LLM filter ───────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a research assistant building a database of AI use cases in journalism.

You are looking at a HuggingFace Space (an interactive AI demo or tool).
Decide whether it represents an AI tool that was built by, for, or is being
used by journalists or news organisations in their editorial or reporting work.

To qualify, the Space must:
  1. Use or demonstrate artificial intelligence in some meaningful way.
  2. Be clearly useful for journalism, newsroom workflows, or reporting tasks
     (e.g. transcription, fact-checking, image verification, data analysis,
     automated writing, source discovery, translation for news, etc.)
     — OR — be explicitly created by a journalist or news organisation for
     professional use.

Do NOT mark as relevant:
  - Generic AI demos with no journalism connection.
  - Tools described only as "for anyone" with no news/journalism context.
  - Research tools with no clear newsroom application.

Reply with ONLY a JSON object:
{"relevant": true,  "reason": "<one sentence>"}
{"relevant": false, "reason": "<one sentence>"}
"""

_openai_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY is not set.")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def is_journalism_space(space_id: str, title: str, description: str, readme: str) -> bool:
    excerpt = "\n".join(filter(None, [
        f"Space: {space_id}",
        f"Title: {title}" if title else None,
        f"Description: {description}" if description else None,
        f"README:\n{readme[:1200]}" if readme else None,
    ]))
    if not excerpt.strip():
        return False
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": excerpt},
            ],
            temperature=0,
            max_tokens=80,
        )
        raw  = response.choices[0].message.content.strip()
        data = json.loads(raw)
        result = bool(data.get("relevant", True))
        logger.debug("LLM → %s | %s", result, data.get("reason", ""))
        return result
    except Exception as exc:
        logger.warning("LLM check failed (%s) — allowing through", exc)
        return True


# ── API helpers ────────────────────────────────────────────────────────────────
def get_json(url: str, params: dict | None = None) -> list | dict | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(5 * (attempt + 1))
    return None


def fetch_readme(space_id: str) -> str:
    """Fetch raw README.md for a space — returns empty string if not found."""
    url = f"https://huggingface.co/spaces/{space_id}/raw/main/README.md"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        # Strip YAML front matter and markdown image lines
        lines = []
        in_frontmatter = False
        front_count = 0
        for line in resp.text.splitlines():
            stripped = line.strip()
            if stripped == "---":
                front_count += 1
                in_frontmatter = front_count < 2
                continue
            if in_frontmatter:
                continue
            if stripped.startswith(("![", "[![")):
                continue
            if stripped:
                lines.append(stripped)
        return "\n".join(lines)[:2000]
    except requests.RequestException:
        return ""


# ── Data fetchers ──────────────────────────────────────────────────────────────
def fetch_org_members() -> list[str]:
    """Return list of member usernames for the org."""
    data = get_json(f"{HF_API}/organizations/{ORG}/members")
    if not isinstance(data, list):
        return []
    usernames = [m["user"] for m in data if m.get("user")]
    logger.info("Org has %d members", len(usernames))
    return usernames


def fetch_spaces_for_author(author: str) -> list[dict]:
    """Return all public Spaces for a given author."""
    data = get_json(f"{HF_API}/spaces",
                    params={"author": author, "limit": 100, "full": "true"})
    return data if isinstance(data, list) else []


def _parse_space(space: dict) -> dict:
    space_id    = space.get("id", "")
    card        = space.get("cardData") or {}
    title       = card.get("title") or space_id.split("/")[-1]
    description = card.get("short_description") or ""
    tags        = card.get("tags") or space.get("tags") or []
    created_at  = (space.get("createdAt") or "")[:10]
    url         = f"https://huggingface.co/spaces/{space_id}"
    likes       = space.get("likes", 0)

    return {
        "_space_id":   space_id,
        "_description": description,
        "_tags":       tags,
        "_likes":      likes,
        "title":       title or space_id,
        "organisation": None,   # not stored — member usernames are personal data
        "date_published": created_at or None,
        "url":         url,
        "summary":     description[:500] if description else None,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    # 1. Org's own spaces
    logger.info("Fetching %s org spaces…", ORG)
    org_spaces = fetch_spaces_for_author(ORG)
    logger.info("  %d org spaces", len(org_spaces))

    # 2. All member spaces
    members = fetch_org_members()
    member_spaces: list[dict] = []
    seen_ids: set[str] = {s.get("id", "") for s in org_spaces}

    for i, username in enumerate(members):
        spaces = fetch_spaces_for_author(username)
        new = 0
        for s in spaces:
            sid = s.get("id", "")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                member_spaces.append(s)
                new += 1
        if new:
            logger.info("  [%d/%d] member: %d new spaces", i + 1, len(members), new)
        time.sleep(DELAY)

    all_spaces = org_spaces + member_spaces
    logger.info("Total unique spaces to evaluate: %d", len(all_spaces))

    if dry_run:
        for s in all_spaces:
            r = _parse_space(s)
            print(f"  [{r['_space_id']}]  ★{r['_likes']}")
            print(f"    {r['_description'][:80]}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for space in all_spaces:
        parsed = _parse_space(space)
        space_id    = parsed.pop("_space_id")
        description = parsed.pop("_description")
        tags        = parsed.pop("_tags")
        parsed.pop("_likes")

        # Fetch README for richer LLM context
        readme = fetch_readme(space_id)
        time.sleep(DELAY)

        # Build raw_text
        parts = [f"Space: {space_id}"]
        if description:
            parts.append(f"Description: {description}")
        if tags:
            parts.append(f"Tags: {', '.join(str(t) for t in tags)}")
        if readme:
            parts.append(f"README:\n{readme}")
        raw_text = "\n".join(parts)[:5000]

        parsed["raw_text"] = raw_text
        if not parsed.get("summary") and readme:
            parsed["summary"] = readme[:500]

        if not is_journalism_space(
            space_id,
            parsed.get("title", ""),
            description,
            readme,
        ):
            skipped += 1
            logger.debug("  ✗ not journalism: %s", space_id)
            time.sleep(0.3)
            continue

        attempted += 1
        parsed.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SOURCE_URL,
        })

        if insert_use_case(conn, parsed):
            inserted += 1
            logger.info("  + %s", space_id)

        time.sleep(0.5)

    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape JournalistsonHF spaces for journalism AI use cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="List spaces without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
