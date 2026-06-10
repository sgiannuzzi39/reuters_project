\
\
\
\
\
\
\
   

import argparse
import csv
import logging
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_base import get_db, insert_use_case, log_summary

logger = logging.getLogger("journalismai_csv")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

SOURCE_NAME = "JournalismAI"
SOURCE_CAT  = "Database"
SOURCE_URL  = "https://www.journalismai.info/resources/case-studies"


def parse_date(raw: str) -> str | None:
                                                                          
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%B %d, %Y", "%B %Y", "%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime(
                "%Y-%m-%d" if "%d" in fmt else ("%Y-%m" if "%B" in fmt else "%Y")
            )
        except ValueError:
            continue
    return raw                               


def import_csv(csv_path: Path, dry_run: bool = False) -> None:
    conn      = get_db()
    attempted = 0
    inserted  = 0

    with open(csv_path, encoding="utf-8-sig") as f:                            
        reader = csv.DictReader(f)
        for row in reader:
            attempted += 1

            title    = (row.get("Case Study") or "").strip()
            org      = (row.get("Organisation") or "").strip()
            url      = (row.get("URL") or row.get("Alternative URL") or "").strip()
            category = (row.get("Category") or "").strip()
            country  = (row.get("Country") or "").strip()
            date_raw = (row.get("Date") or "").strip()
            tags     = (row.get("Tags") or "").strip()

            date_pub = parse_date(date_raw)

                                        
            raw_text = (
                f"Title: {title}\n"
                f"Organisation: {org}\n"
                f"Country: {country}\n"
                f"Category: {category}\n"
                f"Tags: {tags}\n"
                f"Date: {date_raw}\n"
                f"URL: {url}"
            )

            record = {
                "source_name":     SOURCE_NAME,
                "source_category": SOURCE_CAT,
                "source_url":      SOURCE_URL,
                "title":           title or None,
                "organisation":    org or None,
                "country":         country or None,
                "date_published":  date_pub,
                "url":             url or None,
                "summary":         category,                                               
                "raw_text":        raw_text,
            }

            if dry_run:
                logger.info("DRY RUN — would insert: %s / %s (%s)", org, title[:60], date_pub)
                continue

            if insert_use_case(conn, record):
                inserted += 1
                logger.info("  + [%s] %s", country, title[:70])

    if not dry_run:
        log_summary(SOURCE_NAME, attempted, inserted)
    else:
        logger.info("DRY RUN complete — %d rows would be processed", attempted)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import JournalismAI CSV into database")
    parser.add_argument("csv_path", help="Path to the JournalismAI CSV file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be imported without writing to DB")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"Error: file not found: {csv_path}")
        sys.exit(1)

    import_csv(csv_path, dry_run=args.dry_run)
