"""Authenticate an AssetCore backup and verify its internal checksum manifest."""

from __future__ import annotations

import argparse
import json
import os
import tarfile
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from .postgres_toolchain import ToolchainError, check_archive_compatibility, check_compatibility
    from .restore_assetcore import _key, _safe_extract, _sha256
except ImportError:  # Direct script execution.
    from postgres_toolchain import ToolchainError, check_archive_compatibility, check_compatibility
    from restore_assetcore import _key, _safe_extract, _sha256


def verify(backup: Path, *, require_postgres_compatible: bool = False) -> dict:
    raw = backup.resolve().read_bytes()
    header = b"ASSETCORE-BACKUP-1\n"
    if not raw.startswith(header) or len(raw) <= len(header) + 12:
        raise SystemExit("Unsupported or damaged backup format.")
    nonce = raw[len(header):len(header) + 12]
    try:
        payload = AESGCM(_key()).decrypt(
            nonce, raw[len(header) + 12:], b"AssetCore backup v1"
        )
    except InvalidTag as exc:
        raise SystemExit("Backup authentication failed.") from exc
    with tempfile.TemporaryDirectory(prefix="assetcore-verify-") as temp_name:
        temp = Path(temp_name)
        archive = temp / "payload.tar.gz"
        archive.write_bytes(payload)
        with tarfile.open(archive, "r:gz") as bundle:
            _safe_extract(bundle, temp / "verified")
        verified = temp / "verified"
        manifest = json.loads((verified / "manifest.json").read_text(encoding="utf-8"))
        dump = verified / "database.dump"
        if manifest.get("format") != "assetcore-backup-v1":
            raise SystemExit("Unsupported backup manifest.")
        if not dump.is_file() or _sha256(dump) != manifest.get("database_sha256"):
            raise SystemExit("Backup checksum verification failed.")
        if require_postgres_compatible:
            try:
                toolchain = check_compatibility(os.environ.get("DATABASE_URL", ""), ("pg_restore", "psql"))
                archive_versions = check_archive_compatibility(dump, manifest)
            except ToolchainError as exc:
                raise SystemExit(f"Backup qualification refused: {exc}.") from None
            return {"format": "assetcore-backup-v1", "postgresql_qualification": {
                "toolchain": toolchain, "archive": archive_versions,
            }}
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--require-postgres-compatible", action="store_true",
                        help="Also require PostgreSQL 16 target/tools and archive producer (read-only)")
    args = parser.parse_args()
    try:
        manifest = verify(args.backup, require_postgres_compatible=args.require_postgres_compatible)
    except Exception:
        raise SystemExit("Backup verification failed.") from None
    # Legacy manifests may contain arbitrary optional metadata. Never echo it at
    # the CLI boundary; the offline verify() API still returns the original v1 data.
    summary = {"format": "assetcore-backup-v1"}
    if args.require_postgres_compatible:
        summary["postgresql_qualification"] = manifest["postgresql_qualification"]
    else:
        summary["database_sha256"] = manifest["database_sha256"]
        summary["documents_included"] = manifest.get("documents_included") is True
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Backup authentication and checksum verification passed.")


if __name__ == "__main__":
    main()
