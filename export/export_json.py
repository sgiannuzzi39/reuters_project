"""
export_json.py
--------------
Exports the SQLite database to JSON files for:
  1. LLM categorisation (Phase 3) — one record per line (JSONL)
  2. Visualisation / front-end (Phase 4/5) — clean JSON array

Usage:
    python export_json.py
    python export_json.py --uncategorised-only   # only rows not yet categorised
    python export_json.py --format jsonl         # JSONL for LLM batch processing
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scrapers"))
from scrapers.scraper_base import get_db, DATA_DIR

EXPORT_DIR = Path(__file__).parent.parent / "export"
EXPORT_DIR.mkdir(exist_ok=True)


def export(
    uncategorised_only: bool = False,
    fmt: str = "json",           # "json" | "jsonl"
    include_raw: bool = False,   # raw_text can be large; exclude by default for viz
) -> None:

    conn  = get_db()
    ts    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # ── Query ──────────────────────────────────────────────────────────────────
    where = "WHERE llm_category IS NULL" if uncategorised_only else ""
    cols  = """
        id, source_name, source_category, source_url, date_scraped,
        title, organisation, country, date_published, url, summary,
        llm_category, llm_theme, llm_stage
    """
    if include_raw:
        cols += ", raw_text"

    rows = conn.execute(f"SELECT {cols} FROM use_cases {where} ORDER BY date_published").fetchall()
    conn.close()

    records = [dict(r) for r in rows]

    # ── Write ──────────────────────────────────────────────────────────────────
    if fmt == "jsonl":
        out_path = EXPORT_DIR / f"use_cases_{ts}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    else:
        out_path = EXPORT_DIR / f"use_cases_{ts}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {"exported_at": ts, "total": len(records), "records": records},
                f,
                ensure_ascii=False,
                indent=2,
            )

    print(f"Exported {len(records)} records → {out_path}")

    # ── Also write a 'latest' symlink / copy for convenience ──────────────────
    latest_path = EXPORT_DIR / f"use_cases_latest.{fmt}"
    with open(latest_path, "w", encoding="utf-8") as f:
        if fmt == "jsonl":
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        else:
            json.dump(
                {"exported_at": ts, "total": len(records), "records": records},
                f,
                ensure_ascii=False,
                indent=2,
            )
    print(f"Also written to: {latest_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export use_cases DB to JSON/JSONL")
    parser.add_argument("--uncategorised-only", action="store_true",
                        help="Only export rows without LLM categories")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--include-raw", action="store_true",
                        help="Include raw_text field (large)")
    args = parser.parse_args()

    export(
        uncategorised_only=args.uncategorised_only,
        fmt=args.format,
        include_raw=args.include_raw,
    )
