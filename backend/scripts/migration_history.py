from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_VERSIONS_DIR = BACKEND / "alembic" / "versions"
DEFAULT_MANIFEST = BACKEND / "alembic" / "migration_history_manifest.json"


def normalized_sha256(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def validate_migration_history(
    *,
    versions_dir: Path = DEFAULT_VERSIONS_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != 1:
        raise ValueError("Unsupported migration history manifest format.")
    protected = manifest.get("protected")
    if not isinstance(protected, dict) or not protected:
        raise ValueError("Migration history manifest has no protected entries.")

    actual_files = {
        path.name: path
        for path in versions_dir.glob("*.py")
        if path.is_file() and path.name != "__init__.py"
    }
    missing = sorted(set(protected) - set(actual_files))
    mismatched = sorted(
        name
        for name, expected in protected.items()
        if name in actual_files
        and normalized_sha256(actual_files[name]) != str(expected).casefold()
    )
    unprotected = sorted(set(actual_files) - set(protected))
    return {
        "valid": not missing and not mismatched,
        "algorithm": manifest.get("algorithm"),
        "protected_count": len(protected),
        "missing": missing,
        "mismatched": mismatched,
        "new_unprotected_migrations": unprotected,
    }
