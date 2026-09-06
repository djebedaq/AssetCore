"""Allowlisted operational timeline projections, not general audit serialization."""

import math
import re

# Free operational descriptions remain readable, but encoded payloads, credentials
# and absolute internal paths must not become a second download/security channel.
_PRIVATE_TEXT = re.compile(
    r"data:[^\s,]*[;,]|\bBearer\s+|[A-Za-z]:[\\/]|(?:^|\s)/(?:app|tmp|var|home|srv|etc)/"
    r"|\\\\[^\s]+|[A-Za-z0-9+/=_-]{160,}"
    r"|\b(?:password|secret|token|api_key|private_key|encryption_key"
    r"|csrf(?:_token)?|signature(?:_image|_bytes|_data)?)\s*[:=]",
    re.IGNORECASE,
)


def operational_text(value: object) -> str | None:
    if not isinstance(value, str) or _PRIVATE_TEXT.search(value):
        return None
    return value[:4000]


def exact_id(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def project(data: object, *keys: str) -> dict:
    if not isinstance(data, dict):
        return {}
    result = {}
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            value = operational_text(value)
        if value is None or type(value) in {str, int, bool}:
            if key in data:
                result[key] = value
        elif type(value) is float and math.isfinite(value):
            result[key] = value
    return result


PART_FIELDS = ("catalog_part_id", "part_number", "quantity", "unit", "source")
_STAGE_FIELDS = (
    "diagnosis_minutes",
    "repair_minutes",
    "testing_minutes",
    "inspection_complete",
    "cleaning_complete",
    "test_required",
    "test_passed",
    "test_pressure_bar",
    "leaks_detected",
    "wizard_stage",
)
REPAIR_DETAILS = {
    "ACCEPTED": ("condition_before", "reported_problem"),
    "RETURN_DIRECTED_TO_REPAIR": (
        "transfer_id",
        "return_document_id",
        "return_operation_batch_id",
        "condition",
        "result",
        "missing_equipment",
        "damage",
        "contamination",
        "notes",
    ),
    "INSPECTION": _STAGE_FIELDS,
    "CLEANING": _STAGE_FIELDS,
    "DIAGNOSIS": _STAGE_FIELDS,
    "APPROVAL": (),
    "PARTS": (),
    "REPAIR_ACTION": _STAGE_FIELDS,
    "TEST": _STAGE_FIELDS,
    "STATUS_CHANGE": _STAGE_FIELDS,
    "COMPLETED": _STAGE_FIELDS,
    "PARTICIPANT_ADDED": ("participant_id", "role_in_repair", "minutes_worked"),
    "PARTICIPANT_REMOVED": ("participant_id",),
    "PART_ADDED": PART_FIELDS,
    "ATTACHMENT_ADDED": ("stage",),
    "DOCUMENT_GENERATED": (),
    "NOTE": _STAGE_FIELDS,
}

ASSET_DETAILS = {
    "MACHINE_CREATED": ("inventory_number",),
    "MACHINE_UPDATED": (),
    "CUSTOM_FIELDS_UPDATED": (),
    "ATTACHMENT_ADDED": ("attachment_id", "filename", "kind"),
    "IMPORTED": ("source",),
    "LOCATION_CHANGED": (),
    "MACHINE_LOCATION_CHANGED": (),
}


def asset_details(event) -> dict:
    details = project(event.details, *ASSET_DETAILS.get(event.event_type, ()))
    details.update(
        {
            "previous_location_id": event.previous_location_id,
            "new_location_id": event.new_location_id,
        }
    )
    if event.event_type == "CUSTOM_FIELDS_UPDATED" and isinstance(event.details, dict):
        identifiers = event.details.get("field_ids")
        if isinstance(identifiers, list):
            details["field_ids"] = sorted(
                {value for value in identifiers if type(value) is int and value > 0}
            )
    if event.event_type in {"MACHINE_UPDATED", "CUSTOM_FIELDS_UPDATED", "IMPORTED"}:
        data = event.details if isinstance(event.details, dict) else {}
        fields = data.get("changed_fields", data.get("fields"))
        # Names only, no arbitrary custom-field values or nested import records.
        if isinstance(fields, list):
            allowed = {
                "inventory_number",
                "name",
                "brand",
                "model",
                "serial_number",
                "pressure_bar",
                "status",
                "location_id",
                "category_id",
                "category",
                "is_active",
                "notes",
            }
            details["changed_fields"] = sorted(
                {v for v in fields if isinstance(v, str) and v in allowed}
            )
    return details
