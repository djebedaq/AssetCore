from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, User


def add_audit_log(
    db: Session,
    user: User,
    entity_type: str,
    entity_id: int | None,
    action: str,
    details: dict[str, Any] | str | None = None,
    operation_reference: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=(
            json.dumps(details, ensure_ascii=False, default=str)
            if isinstance(details, dict)
            else details
        ),
        user_id=user.id,
        user_name=user.full_name,
        operation_reference=operation_reference,
    )
    db.add(entry)
    return entry
