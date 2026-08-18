from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.catalog.validation import validate_catalog_v2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = validate_catalog_v2()
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
