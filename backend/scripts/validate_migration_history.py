from __future__ import annotations

import argparse
import json
from pathlib import Path

from migration_history import (
    DEFAULT_MANIFEST,
    DEFAULT_VERSIONS_DIR,
    validate_migration_history,
    validate_migration_release,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Alembic migration protection.")
    parser.add_argument(
        "--require-all-protected", action="store_true",
        help="Fail CI/release when any revision is absent from the protected manifest.",
    )
    parser.add_argument("--versions-dir", type=Path, default=DEFAULT_VERSIONS_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    validator = (
        validate_migration_release if args.require_all_protected else validate_migration_history
    )
    report = validator(versions_dir=args.versions_dir, manifest_path=args.manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
