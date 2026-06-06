"""
scraper_base.py
---------------
shared db schema, connection helpers, and insert logic used by all scrapers.
"""

import json
import os
import sqlite3
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

# ── paths ──────────────────────────────────────────────────────────────────────
ROOT_DIR  = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT_DIR / "data"
LOG_DIR   = ROOT_DIR / "logs"
DB_PATH   = DATA_DIR / "usecases_FINAL.db"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ── logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "scraper.log"),
    ],
)
logger = logging.getLogger("base")


# ── schema ─────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS use_cases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,

    -- provenance
    source_name      TEXT NOT NULL,   -- e.g. "Nieman Lab"
    source_category  TEXT NOT NULL,   -- "Curated" | "Database" | "Industry" | "Academic"
    source_url       TEXT NOT NULL,   -- the url that was scraped
    date_scraped     TEXT NOT NULL,   -- utc timestamp

    -- content
    title            TEXT,            -- headline / case study title
    organisation     TEXT,            -- news org (e.g. "BBC")
    country          TEXT,            -- country of the news org
    date_published   TEXT,            -- yyyy, yyyy-mm, or yyyy-mm-dd
    url              TEXT,            -- canonical link to the article
    summary          TEXT,            -- short description of the use case
    raw_text         TEXT,            -- full text (used as llm input)

    -- llm fields (populated by categorise.py)
    llm_category     TEXT,
    llm_theme        TEXT,
    llm_stage        TEXT,

    -- dedup
    dedup_hash       TEXT UNIQUE      -- sha-256 of (title + organisation + url)
);

CREATE INDEX IF NOT EXISTS idx_source_name     ON use_cases (source_name);
CREATE INDEX IF NOT EXISTS idx_source_category ON use_cases (source_category);
CREATE INDEX IF NOT EXISTS idx_date_published  ON use_cases (date_published);
CREATE INDEX IF NOT EXISTS idx_organisation    ON use_cases (organisation);
CREATE INDEX IF NOT EXISTS idx_llm_category    ON use_cases (llm_category);
"""


# ── connection ─────────────────────────────────────────────────────────────────
def get_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """return a connection in wal mode with schema applied."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # safe for concurrent writes
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ── dedup ──────────────────────────────────────────────────────────────────────
def make_dedup_hash(title: str, organisation: str, url: str) -> str:
    """sha-256 of title+org+url (lowercased). duplicate inserts are silently ignored."""
    raw = "|".join([
        (title        or "").strip().lower(),
        (organisation or "").strip().lower(),
        (url          or "").strip().lower(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


# ── insert ─────────────────────────────────────────────────────────────────────
def insert_use_case(conn: sqlite3.Connection, record: dict) -> bool:
    """insert a record; returns true if new, false if duplicate."""
    dedup_hash = make_dedup_hash(
        record.get("title", ""),
        record.get("organisation", ""),
        record.get("url", ""),
    )

    row = {
        "source_name":     record["source_name"],
        "source_category": record["source_category"],
        "source_url":      record["source_url"],
        "date_scraped":    datetime.now(timezone.utc).isoformat(),
        "title":           record.get("title"),
        "organisation":    record.get("organisation"),
        "country":         record.get("country"),
        "date_published":  record.get("date_published"),
        "url":             record.get("url"),
        "summary":         record.get("summary"),
        "raw_text":        record.get("raw_text"),
        "llm_category":    None,
        "llm_theme":       None,
        "llm_stage":       None,
        "dedup_hash":      dedup_hash,
    }

    sql = """
        INSERT OR IGNORE INTO use_cases (
            source_name, source_category, source_url, date_scraped,
            title, organisation, country, date_published, url,
            summary, raw_text, llm_category, llm_theme, llm_stage,
            dedup_hash
        ) VALUES (
            :source_name, :source_category, :source_url, :date_scraped,
            :title, :organisation, :country, :date_published, :url,
            :summary, :raw_text, :llm_category, :llm_theme, :llm_stage,
            :dedup_hash
        )
    """
    cursor = conn.execute(sql, row)
    conn.commit()
    inserted = cursor.rowcount == 1
    if inserted:
        logger.debug("Inserted: %s", record.get("title", "—"))
    else:
        logger.debug("Duplicate skipped: %s", record.get("title", "—"))
    return inserted


# ── relevance filter ───────────────────────────────────────────────────────────
# called before every insert — gpt-4o-mini checks whether the article describes
# a concrete ai use case by a specific news organisation. needs OPENAI_API_KEY.

_openai_client: OpenAI | None = None

_SYSTEM_PROMPT = """\
You are a research assistant building a database of AI use cases in journalism.

Classify whether the article excerpt describes a CONCRETE AI use case or \
implementation by a news organisation (broadcaster, newspaper, news agency, \
magazine, or media outlet).

A "use case" means a specific organisation has used, tested, piloted, \
implemented, or developed an AI tool or system as part of their editorial \
or operational workflow.

Articles that are general opinion pieces, policy discussions, or broad trend \
analyses WITHOUT a specific implementing organisation do NOT qualify.

Reply with ONLY a JSON object — no markdown, no explanation outside the object:
{"relevant": true,  "reason": "<one sentence>"}
{"relevant": false, "reason": "<one sentence>"}
"""


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. Export it before running a scraper."
            )
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def is_ai_journalism_relevant(title: str, summary: str, raw_text: str = "") -> bool:
    """
    returns true if the article looks like a real newsroom ai use case.
    on any api error, passes through conservatively (returns true).
    """
    excerpt = " ".join([
        title   or "",
        summary or "",
        (raw_text or "")[:500],
    ]).strip()

    if not excerpt:
        return False

    try:
        client = _get_openai_client()
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
        relevant = bool(data.get("relevant", True))
        logger.debug("LLM filter → %s | %s", relevant, data.get("reason", ""))
        return relevant
    except Exception as exc:
        logger.warning("LLM relevance check failed (%s) — allowing article through", exc)
        return True


# ── batch reporting ─────────────────────────────────────────────────────────────
def log_summary(source_name: str, attempted: int, inserted: int,
                filtered: int = 0) -> None:
    duplicates = attempted - inserted - filtered
    logger.info(
        "[%s] Done — %d attempted, %d inserted, %d relevance-filtered, %d duplicates",
        source_name, attempted, inserted, filtered, duplicates,
    )
