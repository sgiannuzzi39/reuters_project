"""
clean_data.py
-------------
Step 1: Remove cross-source duplicates — same title from multiple scrapers.
        When a use case appears in more than one source, keep the highest-quality
        record (scored by source priority + metadata completeness) and delete the rest.

Step 2: Re-run the LLM relevance filter on arXiv and Semantic Scholar records.
        The scraper-level filter passed some papers with no journalism connection;
        this re-checks every academic record with the same prompt and deletes failures.

Usage:
    python clean_data.py --dry-run     # preview without touching the DB
    python clean_data.py               # apply changes
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scrapers"))
from scraper_base import get_db, is_ai_journalism_relevant, DB_PATH

logger = logging.getLogger("clean")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] — %(message)s")

# Higher score = prefer to keep this source when deduplicating
SOURCE_PRIORITY = {
    "JournalismAI":                                10,
    "Reuters Institute":                           8,
    "Reuters Institute Digital News Report 2025":  8,
    "WAN-IFRA Age of AI in the Newsroom":          8,
    "Google News Initiative":                      7,
    "WAN-IFRA":                                    7,
    "INMA":                                        7,
    "Press Gazette":                               6,
    "Nieman Lab":                                  6,
    "Digiday":                                     6,
    "Journalism.co.uk":                            6,
    "Poynter":                                     6,
    "Columbia Journalism Review":                  6,
    "Editor & Publisher":                          6,
    "Generative AI Newsroom":                      5,
    "arXiv":                                       2,
}

MIN_TITLE_LEN = 15   # ignore very short titles to avoid false dedup matches


def _score(r: dict) -> int:
    score = SOURCE_PRIORITY.get(r["source_name"], 5) * 10
    if r["country"]:        score += 4
    if r["organisation"]:   score += 2
    if r["date_published"]: score += 2
    if r["summary"]:        score += min(5, len(r["summary"]) // 80)
    return score


# ── Step 1: Cross-source deduplication ───────────────────────────────────────
def dedup_cross_source(conn, dry_run: bool) -> int:
    rows = [dict(r) for r in conn.execute("""
        SELECT id, source_name, title, organisation, country,
               date_published, summary, url
        FROM use_cases ORDER BY id
    """).fetchall()]

    by_title: dict[str, list[dict]] = {}
    for r in rows:
        key = (r["title"] or "").strip().lower()
        if len(key) >= MIN_TITLE_LEN:
            by_title.setdefault(key, []).append(r)

    to_delete: list[int] = []
    for title_key, group in by_title.items():
        if len(group) < 2:
            continue
        # Sort best first; keep group[0], delete the rest
        group.sort(key=_score, reverse=True)
        keeper = group[0]
        for dup in group[1:]:
            to_delete.append(dup["id"])
            logger.info(
                "  DUP  keep=[%s] drop=[%s] id=%d  '%s'",
                keeper["source_name"], dup["source_name"],
                dup["id"], (keeper["title"] or "")[:65],
            )

    logger.info("Step 1: %d duplicate records to remove", len(to_delete))
    if not dry_run and to_delete:
        conn.execute(
            "DELETE FROM use_cases WHERE id IN (%s)" % ",".join("?" * len(to_delete)),
            to_delete,
        )
        conn.commit()
    return len(to_delete)


# ── Step 2: LLM re-filter arXiv / Semantic Scholar ───────────────────────────
def refilter_academic(conn, dry_run: bool) -> int:
    rows = [dict(r) for r in conn.execute("""
        SELECT id, title, summary, raw_text, source_name
        FROM use_cases
        WHERE source_name IN ('arXiv', 'Semantic Scholar')
        ORDER BY id
    """).fetchall()]

    logger.info("Step 2: re-checking %d arXiv/Semantic Scholar records with LLM", len(rows))

    to_delete: list[int] = []
    for i, r in enumerate(rows):
        relevant = is_ai_journalism_relevant(
            r["title"] or "",
            r["summary"] or "",
            r["raw_text"] or "",
        )
        verdict = "KEEP" if relevant else "DROP"
        logger.info("  [%d/%d] %s  %s", i + 1, len(rows), verdict, (r["title"] or "")[:75])
        if not relevant:
            to_delete.append(r["id"])

    logger.info("Step 2: %d false-positive records to remove", len(to_delete))
    if not dry_run and to_delete:
        conn.execute(
            "DELETE FROM use_cases WHERE id IN (%s)" % ",".join("?" * len(to_delete)),
            to_delete,
        )
        conn.commit()
    return len(to_delete)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Clean the use_cases database")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying the database")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("DRY RUN — no changes will be written")

    conn = get_db(DB_PATH)
    total_before = conn.execute("SELECT COUNT(*) FROM use_cases").fetchone()[0]
    logger.info("Records before cleaning: %d", total_before)
    logger.info("─" * 60)

    removed_dups = dedup_cross_source(conn, args.dry_run)
    logger.info("─" * 60)
    removed_llm  = refilter_academic(conn, args.dry_run)

    total_after = conn.execute("SELECT COUNT(*) FROM use_cases").fetchone()[0]
    logger.info("─" * 60)
    logger.info("Cross-source duplicates removed : %d", removed_dups)
    logger.info("Academic false positives removed: %d", removed_llm)
    logger.info("Records after cleaning : %d  (was %d)", total_after, total_before)
    conn.close()


if __name__ == "__main__":
    main()
