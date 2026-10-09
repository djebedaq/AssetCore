"""Real browser acceptance on a newly created development database only."""

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def main():
    root = Path(__file__).resolve().parents[2]
    retry = os.environ.get("ASSETCORE_BROWSER_QA_RETRY_DIR")
    qa = Path(retry).resolve() if retry else root / ".tmp" / ("registry02-browser-" + uuid4().hex)
    if qa.parent != (root / ".tmp").resolve() or not qa.name.startswith("registry02-browser-"):
        raise RuntimeError("Retry must identify this launcher's disposable QA directory")
    qa.mkdir(exist_ok=bool(retry))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(DATABASE_URL="sqlite:///" + (qa / "qa.db").as_posix(),
        SECRET_KEY=secrets.token_urlsafe(48), SIGNATURE_ENCRYPTION_KEY=secrets.token_urlsafe(48),
        ADMIN_EMAIL="registry-qa@assetcore.invalid", ASSETCORE_OWNER_EMAIL="registry-qa@assetcore.invalid",
        OWNER_EMAIL="registry-qa@assetcore.invalid", ADMIN_PASSWORD=password, OWNER_INITIAL_PASSWORD="",
        OWNER_FIRST_NAME="QA", OWNER_MIDDLE_NAME="Registry", OWNER_LAST_NAME="Operator", OWNER_JOB_TITLE="QA operator",
        PRODUCTION_MODE="false", DEPLOYMENT_ENVIRONMENT="test", LICENSE_ENFORCEMENT_ENABLED="false",
        BEARER_COMPATIBILITY_ENABLED="true", PUBLIC_BASE_URL=base_url, FRONTEND_ORIGIN=base_url,
        QA_EMAIL="registry-qa@assetcore.invalid", QA_PASSWORD=password, QA_OUTPUT=str(qa))
    os.environ.update(env)
    sys.path.insert(0, str(root / "backend"))
    sys.path.insert(0, str(root / "tests"))
    from app.database import SessionLocal, engine
    from app.models import (
        AssetCategory,
        CatalogReferenceAssociation,
        Machine,
        OfficialDocument,
        User,
    )
    from app.runtime import initialize_runtime
    from app.security import hash_password
    from sqlalchemy import select
    from test_official_document_registry import _seed_registry_scenario

    if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database).resolve() != qa / "qa.db":
        raise RuntimeError("Browser QA requires the new disposable database")
    initialize_runtime()
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        owner.password_hash = hash_password(password)
        owner.preferred_language = "bg"
        owner.must_change_password = False
        owner.profile_status = "PROFILE_COMPLETE"
        category = AssetCategory(code="QA_QR", name_bg="QA категория за QR печат", name_en="QA QR print category",
            name_ru="QA категория печати QR", capabilities=[])
        existing_category = db.scalar(select(AssetCategory).where(AssetCategory.code == "QA_QR"))
        if existing_category is not None:
            category = existing_category
        else:
            db.add(category)
            db.flush()
        db.add_all([Machine(inventory_number=f"QA-QR-{index}", name=f"QA QR label {index}", brand="SYNTHETIC QA",
            model="QR acceptance only", category=category.code, category_id=category.id) for index in range(1, 28) if not db.scalar(select(Machine.id).where(Machine.inventory_number == f"QA-QR-{index}"))])
        db.commit()
        machine_ids = dict(db.execute(select(Machine.inventory_number, Machine.id)).all())
    with SessionLocal() as db:
        has_scenario = db.scalar(select(OfficialDocument.id).where(OfficialDocument.document_number == "TR-REG-009"))
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        from app.catalog.references import revoke
        for association_id in list(db.scalars(select(CatalogReferenceAssociation.id).where(CatalogReferenceAssociation.revoked_at.is_(None)))):
            revoke(db, owner, association_id, "Disposable browser QA replay")
    if not has_scenario:
        _seed_registry_scenario(SessionLocal, machine_ids, actor_email=env["QA_EMAIL"])
    env["PLAYWRIGHT_MODULE"] = os.environ.get("PLAYWRIGHT_MODULE", "playwright")
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
                    raise RuntimeError("QA server stopped")
                time.sleep(1)
            else:
                raise RuntimeError("QA readiness failed")
            result = subprocess.run(["node", str(root / "tests/browser/registry_catalog_02.mjs")], env=env, cwd=root)
        print("Registry/catalog browser QA exit code:", result.returncode)
        return result.returncode
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
