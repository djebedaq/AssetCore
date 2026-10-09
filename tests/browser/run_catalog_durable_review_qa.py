"""Disposable local browser QA. No production resource or stored credential."""
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
    qa = root / ".tmp" / ("catalog03a-browser-" + uuid4().hex)
    qa.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(DATABASE_URL="sqlite:///" + (qa / "qa.db").as_posix(),
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
    import fitz
    with fitz.open(stream=multipage_pdf(), filetype="pdf") as pdf:
        # Visible synthetic callouts make the browser hotspot exercise verifiable.
        for index in range(10):
            pdf[0].insert_text((80 + index % 5 * 140, 150 + index // 5 * 140), str(index + 1), fontsize=18)
        (qa / "synthetic.pdf").write_bytes(pdf.tobytes())
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
            result = subprocess.run(["node", str(root / "tests/browser/catalog_durable_review.mjs")], cwd=root, env=env)
        print("Catalog 03A browser QA exit code:", result.returncode)
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
