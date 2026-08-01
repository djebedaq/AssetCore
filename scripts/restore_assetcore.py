"""Verify and restore an encrypted AssetCore backup with explicit confirmation."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from .operations_audit import record_operation
except ImportError:  # Direct script execution.
    from operations_audit import record_operation


def _key() -> bytes:
    try:
        key = base64.b64decode(os.environ.get("BACKUP_ENCRYPTION_KEY", ""), validate=True)
    except ValueError as exc:
        raise SystemExit("BACKUP_ENCRYPTION_KEY must be Base64.") from exc
    if len(key) != 32:
        raise SystemExit("BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(bundle: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in bundle.getmembers():
        target = (destination / member.name).resolve()
        if destination != target and destination not in target.parents:
            raise SystemExit("The backup contains an unsafe path.")
    bundle.extractall(destination, filter="data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--confirm", required=True, help="Must equal RESTORE_ASSETCORE")
    parser.add_argument("--documents-staging", type=Path)
    parser.add_argument("--actor-user-id", type=int, required=True)
    args = parser.parse_args()
    if args.confirm != "RESTORE_ASSETCORE":
        raise SystemExit("Restore cancelled: explicit confirmation is missing.")
    if args.documents_staging:
        staging = args.documents_staging.resolve()
        if staging.exists() and any(staging.iterdir()):
            raise SystemExit("Document staging directory must be empty.")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        raise SystemExit("DATABASE_URL must point to PostgreSQL.")
    pg_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    raw = args.backup.resolve().read_bytes()
    header = b"ASSETCORE-BACKUP-1\n"
    if not raw.startswith(header) or len(raw) <= len(header) + 12:
        raise SystemExit("Unsupported or damaged backup format.")
    nonce = raw[len(header):len(header) + 12]
    try:
        payload = AESGCM(_key()).decrypt(nonce, raw[len(header) + 12:], b"AssetCore backup v1")
    except InvalidTag as exc:
        raise SystemExit("Backup authentication failed; nothing was restored.") from exc
    with tempfile.TemporaryDirectory(prefix="assetcore-restore-") as temp_name:
        temp = Path(temp_name)
        archive = temp / "payload.tar.gz"
        archive.write_bytes(payload)
        with tarfile.open(archive, "r:gz") as bundle:
            _safe_extract(bundle, temp / "verified")
        verified = temp / "verified"
        manifest = json.loads((verified / "manifest.json").read_text(encoding="utf-8"))
        dump = verified / "database.dump"
        if manifest.get("format") != "assetcore-backup-v1" or _sha256(dump) != manifest.get("database_sha256"):
            raise SystemExit("Backup checksum verification failed; nothing was restored.")
        result = subprocess.run(
            [os.environ.get("PG_RESTORE", "pg_restore"), "--clean", "--if-exists", "--exit-on-error", "--no-owner", "--no-acl", "--dbname", pg_url, str(dump)],
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit("pg_restore failed; inspect PostgreSQL before retrying.")
        documents = verified / "documents"
        if documents.is_dir() and args.documents_staging:
            staging = args.documents_staging.resolve()
            staging.mkdir(parents=True, exist_ok=True)
            shutil.copytree(documents, staging, dirs_exist_ok=True)
    print("Database restore completed after authenticated checksum verification.")
    record_operation(
        database_url,
        args.actor_user_id,
        "Възстановен проверен криптиран backup",
        {
            "backup_format": "assetcore-backup-v1",
            "backup_sha256": _sha256(args.backup.resolve()),
            "documents_staged": bool(args.documents_staging),
        },
    )


if __name__ == "__main__":
    main()
