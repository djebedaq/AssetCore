"""Fail-closed, explicitly approved operator correction; no automatic startup writes."""

import hashlib
import json
from collections import Counter

from sqlalchemy import select, text

from .audit import add_audit_log
from .machine_identity import FALCH_500_CORRECTIONS
from .models import AssetCategory, Machine
from .permissions import Permission, ensure_permission


def preflight(db, *, lock=False):
    if lock and db.get_bind().dialect.name == "postgresql":
        # Also excludes concurrent inserts/renumbering during conflict validation.
        db.execute(text("LOCK TABLE machines IN SHARE ROW EXCLUSIVE MODE"))
    rows = list(db.scalars(select(Machine).order_by(Machine.id)
                           .execution_options(populate_existing=True)))
    errors, changes = [], []
    numbers = Counter(row.inventory_number for row in rows)
    if any(count > 1 for count in numbers.values()):
        errors.append("duplicate_inventory_numbers")
    for serial, (old, new) in FALCH_500_CORRECTIONS.items():
        matches = [row for row in rows if row.serial_number == serial]
        if len(matches) != 1:
            errors.append(f"serial_not_unique:{serial}")
            continue
        machine = matches[0]
        category = db.get(AssetCategory, machine.category_id) if machine.category_id else None
        if (machine.brand != "Falch" or machine.model != "Wheel Jet 15-e"
                or machine.pressure_bar != 500 or machine.category != "HPWJ"
                or category is None or category.code != "HPWJ"):
            errors.append(f"identity_mismatch:{serial}")
        if machine.inventory_number not in {old, new}:
            errors.append(f"unexpected_number:{serial}")
        changes.append({"machine_id": machine.id, "serial_number": serial,
                        "old_number": machine.inventory_number, "new_number": new})
    target_ids = {row["machine_id"] for row in changes}
    for change in changes:
        if any(row.inventory_number == change["new_number"] and row.id not in target_ids
               for row in rows):
            errors.append(f"inventory_conflict:{change['new_number']}")
    # Mixed legacy/corrected states are ambiguous and require manual investigation.
    states = {"corrected" if row["old_number"] == row["new_number"] else "legacy"
              for row in changes}
    if len(states) > 1:
        errors.append("mixed_correction_state")
    payload = {"changes": changes, "errors": errors}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {**payload, "fingerprint": fingerprint, "ready": not errors,
            "already_corrected": states == {"corrected"} and not errors}


def apply_correction(db, actor, *, approved_fingerprint, reason):
    ensure_permission(actor, Permission.ASSETS_EDIT)
    if not reason.strip() or not approved_fingerprint:
        raise ValueError("Explicit approval and reason required")
    report = preflight(db, lock=True)
    if not report["ready"] or report["fingerprint"] != approved_fingerprint:
        raise ValueError("Registry changed or preflight failed; no changes applied")
    if report["already_corrected"]:
        return report
    # Ascending order frees each unique destination before the next update.
    for change in report["changes"]:
        machine = db.get(Machine, change["machine_id"])
        old = machine.inventory_number
        machine.inventory_number = change["new_number"]
        if machine.name == f"HPWJ №{old}":
            machine.name = f"HPWJ №{machine.inventory_number}"
        add_audit_log(db, actor, "machine", machine.id, "registry_inventory_correction",
                      {**change, "reason": reason.strip(), "preflight": approved_fingerprint},
                      "ASSETCORE-02")
        db.flush()
    return report
