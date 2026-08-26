from __future__ import annotations

import json

from migration_history import validate_migration_history


def main() -> None:
    report = validate_migration_history()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
