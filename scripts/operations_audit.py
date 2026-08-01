"""Write a minimal operational audit event without exposing connection secrets."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import create_engine, text


def record_operation(database_url: str, actor_user_id: int, action: str, details: dict) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            actor = connection.execute(
                text("SELECT id, full_name FROM users WHERE id = :id AND is_active = true"),
                {"id": actor_user_id},
            ).mappings().first()
            if actor is None:
                raise SystemExit("Active audit actor was not found; the operation is not recorded.")
            connection.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(entity_type, entity_id, action, details, user_id, user_name, operation_reference, created_at) "
                    "VALUES ('system_operation', NULL, :action, :details, :user_id, :user_name, :correlation_id, CURRENT_TIMESTAMP)"
                ),
                {
                    "action": action,
                    "details": json.dumps(details, ensure_ascii=False, sort_keys=True),
                    "user_id": actor["id"],
                    "user_name": actor["full_name"],
                    "correlation_id": str(uuid.uuid4()),
                },
            )
    finally:
        engine.dispose()
