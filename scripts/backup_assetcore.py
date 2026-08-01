"""Create an encrypted, checksummed PostgreSQL and document-storage backup."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from .operations_audit import record_operation
except ImportError:  # Direct script execution.
    from operations_audit import record_operation


def _key() -> bytes:
    value = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    try:
        key = base64.b64decode(value, validate=True)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--documents-dir", type=Path)
    parser.add_argument("--actor-user-id", type=int, required=True)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        raise SystemExit("DATABASE_URL must point to PostgreSQL.")
    pg_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir / f"assetcore-{timestamp}.acbackup"
    with tempfile.TemporaryDirectory(prefix="assetcore-backup-") as temp_name:
        temp = Path(temp_name)
        dump = temp / "database.dump"
        result = subprocess.run(
            [os.environ.get("PG_DUMP", "pg_dump"), "--format=custom", "--no-owner", "--no-acl", "--file", str(dump), pg_url],
            check=False,
        )
        if result.returncode != 0 or not dump.is_file():
            raise SystemExit("pg_dump failed; no backup was published.")
        manifest = {
            "format": "assetcore-backup-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "database_sha256": _sha256(dump),
            "documents_included": bool(args.documents_dir),
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        archive = temp / "payload.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(dump, arcname="database.dump")
            bundle.add(manifest_path, arcname="manifest.json")
            if args.documents_dir:
                document_dir = args.documents_dir.resolve()
                if not document_dir.is_dir():
                    raise SystemExit("The configured document-storage directory does not exist.")
                bundle.add(document_dir, arcname="documents")
        nonce = os.urandom(12)
        ciphertext = AESGCM(_key()).encrypt(nonce, archive.read_bytes(), b"AssetCore backup v1")
        target.write_bytes(b"ASSETCORE-BACKUP-1\n" + nonce + ciphertext)
    print(f"Backup created: {target.name}")
    print(f"Encrypted backup SHA-256: {_sha256(target)}")
    record_operation(
        database_url,
        args.actor_user_id,
        "Създаден проверен криптиран backup",
        {
            "backup_format": "assetcore-backup-v1",
            "encrypted_sha256": _sha256(target),
            "documents_included": bool(args.documents_dir),
        },
    )


if __name__ == "__main__":
    main()
