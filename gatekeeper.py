\
\
\
\
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
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

from openai import OpenAI, RateLimitError

ROOT_DIR    = Path(__file__).resolve().parent
DB_PATH     = ROOT_DIR / "data" / "usecases_FINAL.db"
PROMPT_PATH = ROOT_DIR / "gatekeeper_prompt.md"
LOG_DIR     = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

RAW_TEXT_LIMIT = 1200

VALID_STAGES = {
    "access_and_observation",
    "selection_and_filtering",
    "processing_and_editing",
    "publishing_and_distribution",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "gatekeeper.log"),
    ],
)
logger = logging.getLogger("gatekeeper")


                                                                                 

def ensure_columns(conn: sqlite3.Connection) -> None:
                                                         
    new_cols = {
        "gatekeeping_stage":            "TEXT",
        "gatekeeping_stage_reasoning":  "TEXT",
        "gatekeeping_low_confidence":   "INTEGER DEFAULT 0",
    }
    existing = {row[1] for row in conn.execute("PRAGMA table_info(use_cases)").fetchall()}
    for col, typedef in new_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE use_cases ADD COLUMN {col} {typedef}")
            logger.info("added column: %s", col)
    conn.commit()


                                                                                 

def build_user_message(title: str, raw_text: str | None) -> str:
    parts = [f"Title: {title or '(no title)'}"]
    if raw_text:
        truncated = raw_text[:RAW_TEXT_LIMIT]
        if len(raw_text) > RAW_TEXT_LIMIT:
            truncated += "…"
        parts.append(f"Raw Text: {truncated}")
    return "\n".join(parts)


                                                                                 

def classify(client: OpenAI, system_prompt: str, user_message: str, retries: int = 4) -> dict:
                                                  
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0,
                max_tokens=350,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            return json.loads(raw)
        except RateLimitError:
            wait = 2 ** (attempt + 2)                      
            logger.warning("rate limited — retrying in %ds (attempt %d/%d)", wait, attempt + 1, retries)
            time.sleep(wait)
        except json.JSONDecodeError as exc:
            logger.warning("json parse error on attempt %d: %s", attempt + 1, exc)
            if attempt == retries - 1:
                raise
            time.sleep(2)
    raise RuntimeError("exhausted retries")


def validate(result: dict) -> list[str]:
                                                       
    errors = []
    if result.get("gatekeeping_stage") not in VALID_STAGES:
        errors.append(f"invalid gatekeeping_stage: {result.get('gatekeeping_stage')!r}")
    return errors


                                                                                 

def run(dry_run: bool, limit: int | None, rerun: bool, rerun_low: bool) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    if rerun:
        where = ""
    elif rerun_low:
        where = "WHERE gatekeeping_low_confidence = 1"
    else:
        where = "WHERE gatekeeping_stage IS NULL"
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(f"""
        SELECT id, title, raw_text FROM use_cases
        {where} ORDER BY id {limit_clause}
    """).fetchall()

    total = len(rows)
    if total == 0:
        logger.info("no records to classify — all done.")
        conn.close()
        return

    logger.info(
        "%d record%s to classify%s",
        total, "s" if total != 1 else "",
        " (dry run — no writes)" if dry_run else "",
    )

    if dry_run:
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        for i, row in enumerate(rows[:3], 1):
            msg = build_user_message(row["title"] or "", row["raw_text"] or "")
            print(f"\n{'─'*60}")
            print(f"record {i}  id={row['id']}")
            print(msg[:400] + ("…" if len(msg) > 400 else ""))
        if total > 3:
            print(f"\n… ({total - 3} more records not shown)")
        conn.close()
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not set.")
        sys.exit(1)

    client        = OpenAI(api_key=api_key)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    classified = skipped = low = 0

    for i, row in enumerate(rows, 1):
        rec_id   = row["id"]
        title    = row["title"] or ""
        raw_text = row["raw_text"] or ""

        logger.info("[%d/%d] id=%-4d  %s", i, total, rec_id, title[:72])

        user_msg = build_user_message(title, raw_text)

        try:
            result = classify(client, system_prompt, user_msg)
        except Exception as exc:
            logger.error("  failed id=%d: %s", rec_id, exc)
            skipped += 1
            continue

        errors = validate(result)
        if errors:
            logger.warning("  invalid id=%d — %s  (skipping)", rec_id, "; ".join(errors))
            skipped += 1
            continue

        is_low = bool(result.get("low_confidence", False))
        if is_low:
            low += 1
            logger.info("  ↳ low_confidence flagged")

        conn.execute("""
            UPDATE use_cases SET
                gatekeeping_stage            = :gatekeeping_stage,
                gatekeeping_stage_reasoning  = :gatekeeping_stage_reasoning,
                gatekeeping_low_confidence   = :gatekeeping_low_confidence
            WHERE id = :id
        """, {
            "gatekeeping_stage":           result["gatekeeping_stage"],
            "gatekeeping_stage_reasoning": result.get("gatekeeping_stage_reasoning", ""),
            "gatekeeping_low_confidence":  1 if is_low else 0,
            "id":                          rec_id,
        })
        conn.commit()
        classified += 1

        time.sleep(0.3)                                                        

    conn.close()
    logger.info(
        "─── complete: %d classified, %d low-confidence, %d skipped (of %d total)",
        classified, low, skipped, total,
    )
    if low:
        logger.info("re-run with --rerun-low to retry the %d uncertain records.", low)


                                                                                 

def main():
    parser = argparse.ArgumentParser(
        description="classify use cases with GPT-4o-mini using gatekeeper_prompt.md"
    )
    parser.add_argument("--dry-run",   action="store_true", help="print prompts without calling the api")
    parser.add_argument("--limit",     type=int, default=None, metavar="N", help="process at most N records")
    parser.add_argument("--rerun-low", action="store_true", help="re-run records flagged as low-confidence")
    parser.add_argument("--rerun",     action="store_true", help="re-run all already classified records")
    args = parser.parse_args()

    run(dry_run=args.dry_run, limit=args.limit, rerun=args.rerun, rerun_low=args.rerun_low)


if __name__ == "__main__":
    main()
