"""Disposable UX QA launcher. All credentials exist only in process memory."""

import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    qa = (root / ".tmp" / ("ux-dashboard-qa-" + uuid.uuid4().hex)).resolve()
    if not qa.is_relative_to(root.resolve()):
        raise RuntimeError("QA path must stay within this checkout")
    qa.mkdir(parents=True, exist_ok=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(
        DATABASE_URL="sqlite:///" + (qa / "qa.db").as_posix(),
        SECRET_KEY=secrets.token_urlsafe(48),
        OWNER_EMAIL="ux-qa@assetcore.invalid",
        ASSETCORE_OWNER_EMAIL="ux-qa@assetcore.invalid",
        ADMIN_EMAIL="ux-qa@assetcore.invalid",
        ADMIN_PASSWORD=password,
        OWNER_INITIAL_PASSWORD="",
        OWNER_FIRST_NAME="QA",
        OWNER_MIDDLE_NAME="UX",
        OWNER_LAST_NAME="Operator",
        OWNER_JOB_TITLE="QA operator",
        SIGNATURE_ENCRYPTION_KEY=secrets.token_urlsafe(48),
        DEPLOYMENT_ENVIRONMENT="test",
        PRODUCTION_MODE="false",
        BEARER_COMPATIBILITY_ENABLED="true",
        PUBLIC_BASE_URL=base_url,
        FRONTEND_ORIGIN=base_url,
        LICENSE_ENFORCEMENT_ENABLED="false",
        QA_EMAIL="ux-qa@assetcore.invalid",
        QA_PASSWORD=password,
        QA_OUTPUT=str(qa),
    )
    os.environ.update(env)
    sys.path.insert(0, str(root / "backend"))
    sys.path.insert(0, str(root / "tests"))
    # Never use an existing installation, database, server, or browser session.
    from app.database import SessionLocal, engine
    from app.main import app
    from app.models import AssetCategory, Machine
    from app.runtime import initialize_runtime
    from catalog_review_helpers import verify_http_revision
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from test_bulk_transfers import complete_signing
    from test_catalog_builder_parts import BASE, source, workspace

    if (
        engine.url.get_backend_name() != "sqlite"
        or Path(engine.url.database).resolve() != qa / "qa.db"
    ):
        raise RuntimeError("Browser QA requires its own newly created SQLite database")
    env["QA_BROWSER_CHANNEL"] = "msedge" if os.name == "nt" else ""

    def run_browser(phase):
        server = None
        env["QA_PHASE"] = phase
        try:
            with (qa / f"{phase}-server.log").open("w", encoding="utf-8") as log:
                server = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--app-dir",
                        "backend",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    cwd=root,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                import httpx

                for _ in range(90):
                    try:
                        if httpx.get(base_url + "/api/ready", timeout=2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError("QA server stopped before readiness")
                    time.sleep(1)
                else:
                    raise RuntimeError("QA readiness timeout")
                result = subprocess.run(
                    ["node", str(root / "tests/browser/ux_dashboard_cli.mjs")],
                    cwd=root,
                    env=env,
                    check=False,
                )
                if result.returncode:
                    raise RuntimeError(
                        "Browser acceptance failed; inspect the isolated QA artifacts"
                    )
        finally:
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)

    initialize_runtime()
    run_browser("empty")
    with SessionLocal() as db:
        caps = ["HAS_TRANSFER_WORKFLOW", "HAS_REPAIR_WORKFLOW", "HAS_PARTS_CATALOG"]
        a = AssetCategory(
            code="QA_UX_A",
            name_bg="QA категория A",
            name_en="QA category A",
            name_ru="QA категория A",
            capabilities=caps,
        )
        b = AssetCategory(
            code="QA_UX_B",
            name_bg="QA категория B — дълго име за проверка",
            name_en="QA category B — long label check",
            name_ru="QA категория B — длинное название",
            capabilities=caps,
        )
        db.add_all([a, b])
        db.flush()
        assets = [
            Machine(
                inventory_number=f"QA-UX-{index}",
                name=f"QA UX asset {index}",
                brand="SYNTHETIC QA",
                model="UX QA",
                category=(a if index <= 3 else b).code,
                category_id=(a if index <= 3 else b).id,
                location_id=1,
                status="READY",
            )
            for index in range(1, 7)
        ]
        db.add_all(assets)
        db.commit()
        ids = [m.id for m in assets]
    with TestClient(app, raise_server_exceptions=True) as client:
        client.headers["X-AssetCore-Auth-Mode"] = "bearer"
        login = client.post(
            "/api/auth/login", json={"email": env["QA_EMAIL"], "password": password}
        )
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}

        def checked(response):
            if response.status_code >= 400:
                raise RuntimeError(
                    "QA setup API failed: " + str(response.status_code) + " " + response.text[:500]
                )
            return response.json()

        issued = client.post(
            "/api/transfers/bulk-issue",
            headers=headers,
            json={
                "machine_ids": ids[:2],
                "usage_text": "Synthetic UX QA only",
                "location_id": 1,
                "condition_text": "Synthetic QA verified state",
                "recipient": {"first_name": "QA", "middle_name": "UX", "last_name": "Recipient"},
            },
        )
        checked(issued)
        complete_signing(client, issued)
        for index in [2, 3]:
            checked(
                client.post(
                    "/api/repair-cases",
                    headers=headers,
                    json={
                        "machine_id": ids[index],
                        "reported_problem": f"Synthetic UX QA repair category {index}",
                        "condition_before": "QA condition",
                    },
                )
            )
        checked(
            client.post(
                "/api/part-requests/multi",
                headers=headers,
                json={
                    "machine_id": ids[4],
                    "reason": "Synthetic UX QA request",
                    "lines": [
                        {
                            "description": "Synthetic UX QA part",
                            "quantity": 1,
                            "unit": "pcs",
                            "is_unknown_part": True,
                            "assembly": "Synthetic UX QA assembly",
                        }
                    ],
                },
            )
        )
        catalog, revision, assembly, _ = workspace(
            client, headers, SessionLocal, include_empty_group=False
        )
        _, spare, scheme, _ = source(client, headers, assembly, marker="SYNTHETIC UX QA")
        part = checked(
            client.post(
                f"{BASE}/assemblies/{assembly}/parts",
                headers=headers,
                json={
                    "position": "1",
                    "part_number": "QA-UX-PART",
                    "name_bg": "QA тестова част",
                    "name_en": "QA test part",
                    "name_ru": "QA тестовая деталь",
                },
            )
        )
        checked(
            client.post(
                f"{BASE}/parts/{part['id']}/source-pages",
                headers=headers,
                json={"visual_page_ids": [spare]},
            )
        )
        hot = checked(
            client.post(
                f"{BASE}/visual-pages/{scheme}/hotspots",
                headers=headers,
                json={"position": "1", "x": 0.2, "y": 0.3, "width": 0.1, "height": 0.1},
            )
        )
        checked(
            client.post(
                f"{BASE}/hotspots/{hot['id']}/verify",
                headers=headers,
                json={"expected_version": hot["version"]},
            )
        )
        # Link the two READY catalog-only QA assets; transfer/repair assets stay in A/B.
        with SessionLocal() as db:
            c = db.scalar(select(AssetCategory).where(AssetCategory.code == "QA_PARTS_CATEGORY"))
            for machine_id in ids[4:]:
                m = db.get(Machine, machine_id)
                m.category_id = c.id
                m.category = c.code
            db.commit()
        for machine_id in ids[4:]:
            checked(client.post(f"{BASE}/catalogs/{catalog}/assets/{machine_id}", headers=headers))
        verify_http_revision(client, headers, revision)
        readiness = checked(
            client.get(f"{BASE}/revisions/{revision}/publication-readiness", headers=headers)
        )
        assert readiness["ready"], readiness
        checked(
            client.post(
                f"{BASE}/revisions/{revision}/publish",
                headers=headers,
                json={
                    "expected_publication_digest": readiness["publication_digest"],
                    "expected_current_published_revision_id": None,
                    "confirmed": True,
                },
            )
        )
    from app.models import User
    from app.security import hash_password

    observer_password = secrets.token_urlsafe(32)
    env["QA_OBSERVER_PASSWORD"] = observer_password
    with SessionLocal() as db:
        observer = db.scalar(select(User).where(User.email == "ux-observer@assetcore.invalid"))
        if observer is None:
            observer = User(
                email="ux-observer@assetcore.invalid",
                full_name="QA UX Observer",
                first_name="QA",
                middle_name="UX",
                last_name="Observer",
                job_title="QA observer",
                profile_status="PROFILE_COMPLETE",
                role="observer",
                is_active=True,
                must_change_password=False,
                password_hash=hash_password(observer_password),
            )
            db.add(observer)
        else:
            observer.password_hash = hash_password(observer_password)
        db.commit()
    run_browser("workflows")
    print(
        "UX Dashboard QA passed; screenshots and qa-results.json are in the new isolated QA directory."
    )


if __name__ == "__main__":
    main()
