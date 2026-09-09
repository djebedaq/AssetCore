"""CI-only isolated production-contract rehearsal; never a real host commissioning."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

from production_deploy import ROOT, Deployment, DeploymentError


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This destructive QA cleanup is restricted to isolated GitHub CI.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    project = "assetcore-prod01-ci-" + uuid.uuid4().hex[:12]
    temporary = ROOT / ".tmp"
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compose-qa-", dir=temporary) as name:
        directory = Path(name)
        env_file = directory / "empty.env"
        env_file.touch()
        password = secrets.token_urlsafe(36)
        # Disposable QA-only values. The private key exists only in this short-lived
        # test process; only the PUBLIC key reaches a container.
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        public_key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        os.environ.update({
            "POSTGRES_PASSWORD": password,
            "DATABASE_URL": f"postgresql+psycopg://assetcore:{password}@db:5432/assetcore",
            "SECRET_KEY": secrets.token_urlsafe(48),
            "SIGNATURE_ENCRYPTION_KEY": secrets.token_urlsafe(48),
            "OWNER_EMAIL": "compose-qa@assetcore.invalid", "OWNER_JOB_TITLE": "CI operator",
            "OWNER_INITIAL_PASSWORD": secrets.token_urlsafe(36),
            "INSTALLATION_ID": project, "LICENSE_PUBLIC_KEY": base64.b64encode(public_key).decode(),
            "LICENSE_ENFORCEMENT_ENABLED": "true", "PRODUCTION_MODE": "true",
            "DEPLOYMENT_ENVIRONMENT": "production", "MIGRATION_STRATEGY": "external",
            "PUBLIC_BASE_URL": "https://assetcore.example.invalid",
            "FRONTEND_ORIGIN": "https://assetcore.example.invalid",
            "ASSETCORE_PORT": "0", "ASSETCORE_BIND_ADDRESS": "127.0.0.1",
            "BACKUP_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        })
        backups = directory / "backups"
        backups.mkdir()
        subprocess.run(["sudo", "chgrp", "10001", str(backups)], check=True, capture_output=True)
        backups.chmod(0o2770)
        subject = Deployment(ROOT, args.sha, env_file, project)
        try:
            subject.initialize()
            print("PASS: explicit empty PostgreSQL prepare and enforced-license readiness")
            subject.restart()
            print("PASS: same-image start without implicit prepare")
            try:
                subject.initialize()
            except DeploymentError:
                print("PASS: initialization refuses existing installation")
            else:
                raise AssertionError("existing installation was reinitialized")
            destination = subject.upgrade(backups, 1)
            record = json.loads((destination / "release.json").read_text())
            assert record["status"] == "runtime_ready"
            assert record["backup_file"].endswith(".acbackup")
            assert record["fully_commissioned"] is False
            print("PASS: real PostgreSQL stop -> encrypted backup -> verify -> prepare -> ready -> shell")
        except DeploymentError as error:
            # DeploymentError contains only a controlled code, never subprocess text.
            raise SystemExit(f"Compose production QA failed safely; stage={subject.stage}; code={error}") from None
        except Exception:
            raise SystemExit(f"Compose production QA failed safely; stage={subject.stage}") from None
        finally:
            # Exact random CI project, never an operator's volume or another stack.
            subject.dc("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
