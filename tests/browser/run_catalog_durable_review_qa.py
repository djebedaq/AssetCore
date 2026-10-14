"""Disposable local browser QA. No production resource or stored credential."""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def main(*, scenario="durable", pdf_path=None, expected_path=None, browser_script=None):
    root = Path(__file__).resolve().parents[2]
    qa = root / ".tmp" / (f"catalog03-{scenario}-browser-" + uuid4().hex)
    qa.mkdir(parents=True)
    runtime_temp = qa / "runtime-temp"
    runtime_temp.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(DATABASE_URL="sqlite:///" + (qa / "qa.db").as_posix(),
        TMPDIR=str(runtime_temp), TMP=str(runtime_temp), TEMP=str(runtime_temp),
        SECRET_KEY=secrets.token_urlsafe(48), SIGNATURE_ENCRYPTION_KEY=secrets.token_urlsafe(48),
        ADMIN_EMAIL="catalog03a-qa@assetcore.invalid", ASSETCORE_OWNER_EMAIL="catalog03a-qa@assetcore.invalid",
        OWNER_EMAIL="catalog03a-qa@assetcore.invalid", ADMIN_PASSWORD=password, OWNER_INITIAL_PASSWORD="",
        OWNER_FIRST_NAME="QA", OWNER_MIDDLE_NAME="Catalog", OWNER_LAST_NAME="Operator", OWNER_JOB_TITLE="QA operator",
        PRODUCTION_MODE="false", DEPLOYMENT_ENVIRONMENT="test", LICENSE_ENFORCEMENT_ENABLED="false",
        BEARER_COMPATIBILITY_ENABLED="true", PUBLIC_BASE_URL=base_url, FRONTEND_ORIGIN=base_url,
        QA_EMAIL="catalog03a-qa@assetcore.invalid", QA_PASSWORD=password, QA_OUTPUT=str(qa))
    os.environ.update(env)
    sys.path[:0] = [str(root / "backend"), str(root / "tests")]
    from app.database import SessionLocal, engine
    from app.models import User
    from app.runtime import initialize_runtime
    from app.security import hash_password
    from sqlalchemy import select
    from test_catalog_multipage_extraction import multipage_pdf
    if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database).resolve() != qa / "qa.db":
        raise RuntimeError("Browser QA requires its newly created disposable database")
    initialize_runtime()
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        owner.password_hash, owner.preferred_language = hash_password(password), "bg"
        owner.must_change_password, owner.profile_status = False, "PROFILE_COMPLETE"
        db.commit()
    if scenario in {"durable", "final-multipage"}:
        import fitz
        with fitz.open(stream=multipage_pdf(count=7 if scenario == "final-multipage" else 2), filetype="pdf") as pdf:
            # Visible synthetic callouts make the browser hotspot exercise verifiable.
            for index in range(10):
                pdf[0].insert_text((80 + index % 5 * 140, 150 + index // 5 * 140), str(index + 1), fontsize=18)
            if scenario == "durable":
                detail = pdf.new_page(width=850, height=650)
                detail.insert_text((60, 70), "Synthetic QA detail scheme", fontsize=18)
                detail.insert_text((150, 150), "1", fontsize=18)
            (qa / "synthetic.pdf").write_bytes(pdf.tobytes())
    elif scenario in {"ux04", "ux05", "ux06"}:
        from catalog_ux04_fixtures import workflow_pdf
        from catalog_ux05_fixtures import publication_pdf
        (qa / "synthetic.pdf").write_bytes(publication_pdf() if scenario in {"ux05", "ux06"} else workflow_pdf())
        from app.models import AssetCategory, Machine
        with SessionLocal() as db:
            category = AssetCategory(code="QA_UX04_ONLY", name_bg="QA UX04", name_en="QA UX04", name_ru="QA UX04", capabilities=["HAS_PARTS_CATALOG"])
            db.add(category)
            db.flush()
            for number in range(1, 7 if scenario == "ux06" else 3):
                db.add(Machine(inventory_number=f"QA_UX04_{number}", name=f"Synthetic QA machine {number}",
                    category=category.code, category_id=category.id,
                    brand="QA_OTHER" if scenario == "ux06" and number == 5 else "QA",
                    model=None if scenario == "ux06" and number == 4 else "QA"))
            db.commit()
        if scenario == "ux06":
            from app.models import CatalogDefinition, CatalogRevision
            from catalog_binding_fixtures import legacy_binding
            with SessionLocal() as db:
                owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
                pending = CatalogDefinition(code="QA_UX06_PENDING", asset_category_id=category.id,
                    name_bg="Synthetic QA pending", name_en="Synthetic QA pending", name_ru="Synthetic QA pending",
                    manufacturer="QA", model_reference="QA", created_by_id=owner.id)
                db.add(pending)
                db.flush()
                db.add(CatalogRevision(catalog_id=pending.id, revision_code="QA-DRAFT", created_by_id=owner.id))
                target = db.scalar(select(Machine).where(Machine.inventory_number == "QA_UX04_6"))
                legacy_binding(db, owner, pending.id, target.id)
    env["QA_BROWSER_CHANNEL"] = "msedge" if os.name == "nt" else ""
    server = None
    try:
        with (qa / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
                "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=root, env=env,
                stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            import httpx
            for _ in range(90):
                try:
                    if httpx.get(base_url + "/api/ready", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if server.poll() is not None:
                    raise RuntimeError("Disposable browser QA server stopped")
                time.sleep(1)
            else:
                raise RuntimeError("Disposable browser QA readiness failed")
            browser_env = env.copy()
            if scenario == "adaptive":
                # The independent expected control is available ONLY to the
                # browser comparator, never the app server or parser worker.
                browser_env.update(QA_PDF=str(pdf_path), QA_EXPECTED=str(expected_path))
            script_name = "catalog_adaptive_extraction.mjs" if scenario == "adaptive" else "catalog_durable_review.mjs"
            result = subprocess.run(["node", str(browser_script or root / "tests/browser" / script_name)], cwd=root, env=browser_env)
        print("Catalog browser QA exit code:", result.returncode)
        return result.returncode
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
