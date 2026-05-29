"""
scraper_github.py
-----------------
Searches GitHub for repositories representing AI tools built by or for
news organisations, using the GitHub REST Search API.

Each repo is evaluated by a GitHub-specific OpenAI prompt that asks whether
the repository is tied to a specific news organisation use case — not just
generally about journalism or AI.  READMEs are fetched for short-description
repos so the LLM has enough context to decide.

Authentication (REQUIRED):
  Unauthenticated requests allow only 10/min — far too slow.
  Create a free personal access token (no scopes needed for public repos):
    1. Go to github.com/settings/tokens/new
    2 Give it any name, set no scopes (public repo read is default)
    3. Copy the token and set:
          export GITHUB_TOKEN=<your-token>
  With a token: 30 search req/min, 5 000 core req/hour.

Usage:
    python scraper_github.py
    python scraper_github.py --dry-run
"""

import argparse
import base64
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

logger = logging.getLogger("github")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Config ─────────────────────────────────────────────────────────────────────
SEARCH_URL   = "https://api.github.com/search/repositories"
README_URL   = "https://api.github.com/repos/{full_name}/readme"
SOURCE_URL   = "https://github.com/search?q=ai+journalism"
SOURCE_NAME  = "GitHub"
SOURCE_CAT   = "Industry"

BATCH_SIZE             = 100
MAX_RESULTS_PER_QUERY  = 500
DELAY_BETWEEN_PAGES    = 2.5
DELAY_BETWEEN_QUERIES  = 5.0
README_MIN_DESC_LEN    = 120    # fetch README if description shorter than this

SEARCH_QUERIES = [
    # Free-text searches
    "ai journalism",
    "ai newsroom",
    "automated journalism",
    "news automation AI",
    "journalism NLP",
    "fake news detection",
    "fact checking journalism",
    "news summarization AI",
    "news recommendation AI",
    "computational journalism",
    "newsroom automation",
    "media monitoring AI",
    "news article generation",
    "journalist tool AI",

    # Topic-tag searches
    "topic:journalism",
    "topic:newsroom",
    "topic:journalism topic:nlp",
    "topic:journalism topic:machine-learning",
    "topic:journalism topic:deep-learning",
    "topic:journalism topic:data-journalism",
    "topic:journalism topic:ai",
    "topic:newsroom topic:ai",
    "topic:newsroom topic:machine-learning",
]


# ── GitHub-specific LLM filter ─────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a research assistant building a database of AI use cases in journalism.

You are looking at a GitHub repository. Decide whether it represents an AI \
tool or project that was built by, for, or used by a specific news organisation \
(newspaper, broadcaster, news agency, magazine, or media outlet).

To qualify, the repository must:
  1. Involve artificial intelligence, machine learning, or NLP in some way.
  2. Be connected to a specific news organisation — either built by one, \
commissioned by one, or explicitly designed for newsroom use at a named outlet.

Do NOT mark as relevant:
  - Generic NLP or ML libraries with no specific news org connection.
  - Academic or student projects about journalism topics in general.
  - Fake-news datasets or classifiers with no named newsroom involved.
  - Tools described only as "for journalists" without a specific org.

Reply with ONLY a JSON object — no markdown, no explanation outside the object:
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


def is_newsroom_repo(title: str, description: str, readme: str) -> bool:
    """
    Return True if the repo is an AI use case tied to a specific news org.
    On any API error, allow through (conservative default).
    """
    excerpt = "\n".join(filter(None, [
        f"Repository: {title}",
        f"Description: {description}" if description else None,
        f"README excerpt:\n{readme[:1000]}" if readme else None,
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
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        result = bool(data.get("relevant", True))
        logger.debug("LLM → %s | %s", result, data.get("reason", ""))
        return result
    except Exception as exc:
        logger.warning("LLM check failed (%s) — allowing through", exc)
        return True


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _has_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))


def get(url: str, params: dict | None = None) -> dict | None:
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=30)
            if resp.status_code == 403:
                reset = int(resp.headers.get("X-RateLimit-Reset", 0))
                import time as _t
                wait = max(reset - _t.time(), 0) + 5 if reset else 60 * (attempt + 1)
                logger.warning("Rate-limited (403) — sleeping %.0f s", wait)
                time.sleep(wait)
                continue
            if resp.status_code == 422:
                logger.warning("Unprocessable query (422): %s", url)
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(10 * (attempt + 1))
    return None


# ── README fetch ───────────────────────────────────────────────────────────────
def fetch_readme(full_name: str) -> str:
    """Return first 2000 chars of the repo README, decoded from base64."""
    url = README_URL.format(full_name=full_name)
    # Fetch directly — 404 means no README, don't retry it
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code in (404, 403, 422):
            return ""
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return ""
    if not data or data.get("encoding") != "base64":
        return ""
    try:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        lines = [l.strip() for l in content.splitlines()
                 if l.strip() and not l.strip().startswith(("![", "[![", "#!"))]
        return "\n".join(lines)[:2000]
    except Exception:
        return ""


# ── Search ─────────────────────────────────────────────────────────────────────
def search_repos(query: str) -> list[dict]:
    repos = []
    page  = 1

    while len(repos) < MAX_RESULTS_PER_QUERY:
        params = {
            "q":        query,
            "sort":     "stars",
            "order":    "desc",
            "per_page": BATCH_SIZE,
            "page":     page,
        }
        data = get(SEARCH_URL, params)
        if not data:
            break

        items = data.get("items", [])
        if not items:
            break

        total = data.get("total_count", 0)
        repos.extend(items)
        logger.info("  '%s': fetched %d (page %d / ~%d total)",
                    query, len(items), page, total)

        if page * BATCH_SIZE >= min(total, MAX_RESULTS_PER_QUERY, 1000):
            break
        if len(items) < BATCH_SIZE:
            break

        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    return repos


# ── Record builder ─────────────────────────────────────────────────────────────
def _build_record(item: dict, readme: str = "") -> dict:
    full_name   = item.get("full_name", "")
    name        = item.get("name", "")
    description = (item.get("description") or "").strip()
    owner       = (item.get("owner") or {}).get("login", "")
    topics      = item.get("topics") or []
    html_url    = item.get("html_url", "")
    created_at  = (item.get("created_at") or "")[:10]

    parts = [f"Repository: {full_name}"]
    if description:
        parts.append(f"Description: {description}")
    if topics:
        parts.append(f"Topics: {', '.join(topics)}")
    if readme:
        parts.append(f"README:\n{readme}")
    raw_text = "\n".join(parts)

    title   = full_name or name or None
    summary = description[:500] if description else (readme[:300] if readme else None)

    return {
        "title":          title,
        "organisation":   owner or None,
        "date_published": created_at or None,
        "summary":        summary,
        "raw_text":       raw_text[:5000],
        "url":            html_url or None,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def scrape(dry_run: bool = False) -> None:
    if not _has_token():
        logger.warning(
            "No GITHUB_TOKEN set — rate limit is 10 req/min (very slow).\n"
            "Create a free token at github.com/settings/tokens/new (no scopes needed)\n"
            "then: export GITHUB_TOKEN=<token>"
        )

    seen_ids: set[int]    = set()
    all_items: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Query %d/%d: '%s'", i + 1, len(SEARCH_QUERIES), query)
        repos = search_repos(query)
        new = 0
        for repo in repos:
            rid = repo.get("id")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                all_items.append(repo)
                new += 1
        logger.info("  → %d new (total unique: %d)", new, len(all_items))
        time.sleep(DELAY_BETWEEN_QUERIES)

    logger.info("Collected %d unique repos across %d queries",
                len(all_items), len(SEARCH_QUERIES))

    if dry_run:
        for item in all_items:
            desc = (item.get("description") or "")[:80]
            print(f"  [{item.get('full_name', '?')}]  ★{item.get('stargazers_count', 0)}")
            print(f"    {desc}")
        return

    conn      = get_db()
    attempted = 0
    inserted  = 0
    skipped   = 0

    for item in all_items:
        desc   = (item.get("description") or "").strip()
        readme = ""

        # Fetch README when description is short — gives LLM more to judge
        if len(desc) < README_MIN_DESC_LEN:
            readme = fetch_readme(item.get("full_name", ""))
            time.sleep(1.0)

        if not is_newsroom_repo(
            item.get("full_name", ""),
            desc,
            readme,
        ):
            skipped += 1
            logger.debug("  ✗ not a newsroom repo: %s",
                         item.get("full_name", "")[:70])
            time.sleep(0.3)
            continue

        record = _build_record(item, readme)
        if not record.get("title"):
            skipped += 1
            continue

        attempted += 1
        record.update({
            "source_name":     SOURCE_NAME,
            "source_category": SOURCE_CAT,
            "source_url":      SOURCE_URL,
        })

        if insert_use_case(conn, record):
            inserted += 1
            logger.info("  + %s", record.get("title", "")[:80])

        time.sleep(0.5)

    log_summary(SOURCE_NAME, attempted, inserted, filtered=skipped)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Search GitHub for AI-in-journalism repositories")
    parser.add_argument("--dry-run", action="store_true",
                        help="List repos without inserting into the DB")
    args = parser.parse_args()
    scrape(dry_run=args.dry_run)
