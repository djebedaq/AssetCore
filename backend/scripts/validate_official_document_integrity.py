from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal
from app.official_documents.integrity import validate_official_document_integrity


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only OfficialDocument integrity diagnostic."
    )
    parser.add_argument(
        "--strict-history",
        action="store_true",
        help="Also fail when tolerated malformed historical rows are reported.",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        report = validate_official_document_integrity(db)
        db.rollback()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["valid"] or (
        args.strict_history and report["tolerated_history_count"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
