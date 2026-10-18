"""REPORTS-01 acceptance: disposable SQLite database, loopback-only server."""

import json
from pathlib import Path

from run_catalog_durable_review_qa import main


def prepare(factory, qa, password):
    from app.models import User
    from app.security import hash_password
    from reports01_fixtures import reports_fixture

    with factory() as db:
        data = reports_fixture(db)
        db.add(
            User(
                email="reports01-mechanic@assetcore.invalid",
                first_name="Synthetic",
                middle_name="QA",
                last_name="Mechanic",
                full_name="Synthetic QA Mechanic",
                job_title="QA mechanic",
                role="mechanic",
                profile_status="PROFILE_COMPLETE",
                password_hash=hash_password(password),
                must_change_password=False,
            )
        )
        db.commit()
    (qa / "public-fixture.json").write_text(
        json.dumps({**data, "now": data["now"].isoformat()}, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(
        main(
            scenario="reports01",
            browser_script=Path(__file__).with_name("reports01.mjs"),
            prepare=prepare,
        )
    )
