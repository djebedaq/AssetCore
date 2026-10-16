"""Signed synthetic cycles and profile screenshots in a fresh loopback QA database."""

import json
from pathlib import Path

from run_catalog_durable_review_qa import main


def prepare(factory, output, password):
    from app.main import app
    from app.models import AssetCategory, Machine, User
    from app.security import hash_password
    from fastapi.testclient import TestClient
    from test_bulk_transfers import complete_signing, return_payload

    with factory() as db:
        category = AssetCategory(code="QA_TRANSFERS01", name_bg="QA тестови машини",
                                 name_en="QA test machines", name_ru="QA тестовые машины",
                                 capabilities=["HAS_TRANSFER_WORKFLOW"])
        db.add(category)
        db.flush()
        machines = [Machine(inventory_number=f"QA-{number}", name=f"Synthetic QA machine {number}",
                            brand="SYNTHETIC QA", model="QA", status="READY", category=category.code,
                            category_id=category.id, location_id=1) for number in (7, 8, 10, 11, 12)]
        db.add_all(machines)
        db.add(User(email="completion-qa@assetcore.invalid", full_name="QA incomplete",
                    role="mechanic", password_hash=hash_password(password),
                    profile_status="PROFILE_INCOMPLETE", must_change_password=False))
        db.commit()
        ids = [m.id for m in machines]
        category_id = category.id
    with TestClient(app, raise_server_exceptions=True) as client:
        client.headers.update({"X-AssetCore-Auth-Mode": "bearer"})
        login = client.post("/api/auth/login", json={"email": "catalog03a-qa@assetcore.invalid", "password": password})
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        def issue(machine_ids, sign=True):
            response = client.post("/api/transfers/bulk-issue", headers=headers, json={
                "machine_ids": machine_ids, "usage_text": "Synthetic QA task", "location_id": 1,
                "condition_text": "QA verified", "recipient": {"first_name": "QA", "middle_name": "External", "last_name": "Recipient"}})
            assert response.status_code == 201
            if sign:
                complete_signing(client, response)
            return response.json()
        first = issue(ids[:3])
        returned = client.post("/api/transfers/bulk-return", headers=headers,
                               json=return_payload(first["transfers"][0], first["transfers"][2]))
        assert returned.status_code == 200
        complete_signing(client, returned)
        later = issue([ids[0], ids[2]])
        pending = issue([ids[3]], sign=False)
        cancelled = issue([ids[4]], sign=False)
        assert client.post(f"/api/transfer-batches/{cancelled['batch_id']}/cancel", headers=headers,
                           json={"reason": "Synthetic QA cancelled operation"}).status_code == 200
    # No credentials or signing tokens leave process memory.
    (output / "scenario.json").write_text(json.dumps({
        "category_id": category_id, "machine_ids": ids, "first_batch_id": first["batch_id"],
        "later_batch_id": later["batch_id"], "pending_batch_id": pending["batch_id"],
        "first_cycle_ids": [t["transfer_id"] for t in first["transfers"]],
        "later_cycle_ids": [t["transfer_id"] for t in later["transfers"]],
    }), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(scenario="transfers-profile01", prepare=prepare,
                         browser_script=Path(__file__).with_name("transfers_profile01.mjs")))
