from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.authorization_inventory import build_authorization_inventory  # noqa: E402
from app.main import app  # noqa: E402


def main() -> int:
    inventory = build_authorization_inventory(app)
    print(json.dumps(inventory.summary(), ensure_ascii=False, indent=2))
    return 0 if inventory.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
