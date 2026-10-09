"""Operator tool. Default is read-only; use an explicitly configured installation."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import User  # noqa: E402
from app.registry_correction import apply_correction, preflight  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-fingerprint")
    parser.add_argument("--actor-email")
    parser.add_argument("--reason")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("An explicit DATABASE_URL is required")
    engine = create_engine(url, hide_parameters=True)
    try:
        with Session(engine) as db:
            if args.apply:
                if not all((args.approved_fingerprint, args.actor_email, args.reason)):
                    parser.error("Apply requires fingerprint, actor and reason")
                if engine.dialect.name == "sqlite":
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                actor = db.scalar(select(User).where(User.email == args.actor_email,
                                                     User.is_active.is_(True)))
                if actor is None:
                    raise ValueError("Active authorized operator required")
                report = apply_correction(db, actor,
                    approved_fingerprint=args.approved_fingerprint, reason=args.reason)
                db.commit()
            else:
                report = preflight(db)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 2
    except Exception:
        # Never print driver exceptions, URLs or installation paths.
        print("Correction refused; transaction rolled back. Check preflight and authorization.",
              file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
