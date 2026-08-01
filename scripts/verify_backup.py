"""Authenticate an AssetCore backup and verify its internal checksum manifest."""

from __future__ import annotations

import argparse
import json
import tarfile
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from .restore_assetcore import _key, _safe_extract, _sha256
except ImportError:  # Direct script execution.
    from restore_assetcore import _key, _safe_extract, _sha256


def verify(backup: Path) -> dict:
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
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    manifest = verify(args.backup)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Backup authentication and checksum verification passed.")


if __name__ == "__main__":
    main()
