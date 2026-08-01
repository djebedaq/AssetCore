"""Add the final user roles, protected owner, and password state.

Revision ID: 20260801_0004
Revises: 20260731_0003
Create Date: 2026-08-01
"""

from __future__ import annotations

import json
import warnings

import sqlalchemy as sa
from alembic import op
from app.settings import settings

revision = "20260801_0004"
down_revision = "20260731_0003"
branch_labels = None
depends_on = None

FINAL_ROLES = {"administrator", "director", "mechanic", "observer"}
LEGACY_ROLES = {"admin", "manager", "mechanic", "approver", "viewer"}
ROLE_MIGRATION = {
    "manager": "director",
    "approver": "director",
    "viewer": "observer",
    "mechanic": "mechanic",
}


def _owner_email() -> str:
    configured = settings.assetcore_owner_email
    if not configured:
        warnings.warn(
            "ASSETCORE_OWNER_EMAIL is not configured; ADMIN_EMAIL is used only as "
            "the documented migration fallback.",
            stacklevel=2,
        )
        configured = settings.admin_email
    return configured.strip().casefold()


def _preflight(bind: sa.Connection) -> tuple[int | None, list[dict]]:
    rows = [
        dict(row)
        for row in bind.execute(
            sa.text("SELECT id, email, role FROM users ORDER BY id")
        ).mappings()
    ]
    if not rows:
        return None, rows
    invalid_roles = [row["id"] for row in rows if row["role"] not in LEGACY_ROLES | FINAL_ROLES]
    if invalid_roles:
        raise RuntimeError(
            "Миграцията е прекратена: има потребители с непозната роля. "
            "Коригирайте ролите ръчно и стартирайте отново."
        )
    configured = _owner_email()
    matches = [row for row in rows if row["email"].strip().casefold() == configured]
    if len(matches) != 1:
        raise RuntimeError(
            "Миграцията е прекратена без промени: ASSETCORE_OWNER_EMAIL трябва "
            "да съвпада с точно един съществуващ акаунт."
        )
    return int(matches[0]["id"]), rows


def _column_names(bind: sa.Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("users")}


def _audit_role_change(
    bind: sa.Connection,
    user_id: int,
    old_role: str,
    new_role: str,
    reason: str,
) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO audit_logs "
            "(entity_type, entity_id, action, details, user_id, user_name, "
            "operation_reference, created_at) "
            "VALUES ('user_account', :user_id, :action, :details, NULL, "
            ":user_name, :operation_reference, CURRENT_TIMESTAMP)"
        ),
        {
            "user_id": user_id,
            "action": "Мигрирана потребителска роля",
            "details": json.dumps(
                {
                    "target_user_id": user_id,
                    "old_role": old_role,
                    "new_role": new_role,
                    "reason": reason,
                },
                ensure_ascii=False,
            ),
            "user_name": "Системна миграция",
            "operation_reference": revision,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()
    owner_id, rows = _preflight(bind)
    existing_columns = _column_names(bind)
    additions = [
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_system_owner",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    ]
    missing_columns = [
        column for column in additions if column.name not in existing_columns
    ]
    if bind.dialect.name == "sqlite" and missing_columns:
        with op.batch_alter_table("users") as batch:
            for column in missing_columns:
                batch.add_column(column)
    else:
        for column in missing_columns:
            op.add_column("users", column)

    for row in rows:
        user_id = int(row["id"])
        old_role = str(row["role"])
        if user_id == owner_id:
            new_role = "administrator"
            bind.execute(
                sa.text(
                    "UPDATE users SET role = :role, is_system_owner = true, "
                    "is_active = true, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"role": new_role, "id": user_id},
            )
            reason = "configured_system_owner"
        else:
            new_role = "director" if old_role in {"admin", "administrator"} else ROLE_MIGRATION.get(old_role, old_role)
            bind.execute(
                sa.text(
                    "UPDATE users SET role = :role, is_system_owner = false, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"role": new_role, "id": user_id},
            )
            reason = "additional_legacy_admin_downgraded" if old_role in {"admin", "administrator"} else "legacy_role_mapping"
            if old_role in {"admin", "administrator"}:
                warnings.warn(
                    "An additional legacy administrator was safely migrated to director; "
                    "review the migration audit record.",
                    stacklevel=2,
                )
        _audit_role_change(bind, user_id, old_role, new_role, reason)

    if rows:
        owner_count = bind.execute(
            sa.text("SELECT COUNT(*) FROM users WHERE is_system_owner = true")
        ).scalar_one()
        if owner_count != 1:
            raise RuntimeError(
                "Миграцията е прекратена: не може да се гарантира точно един system owner."
            )

    inspector = sa.inspect(bind)
    index_names = {item["name"] for item in inspector.get_indexes("users")}
    if "uq_users_single_system_owner" not in index_names:
        op.create_index(
            "uq_users_single_system_owner",
            "users",
            ["is_system_owner"],
            unique=True,
            sqlite_where=sa.text("is_system_owner = 1"),
            postgresql_where=sa.text("is_system_owner"),
        )

    check_names = {
        item.get("name") for item in sa.inspect(bind).get_check_constraints("users")
    }
    if "ck_users_final_role" not in check_names or "ck_users_owner_invariants" not in check_names:
        with op.batch_alter_table("users") as batch:
            if "ck_users_final_role" not in check_names:
                batch.create_check_constraint(
                    "ck_users_final_role",
                    "role IN ('administrator', 'director', 'mechanic', 'observer')",
                )
            if "ck_users_owner_invariants" not in check_names:
                batch.create_check_constraint(
                    "ck_users_owner_invariants",
                    "NOT is_system_owner OR (role = 'administrator' AND is_active)",
                )


def downgrade() -> None:
    bind = op.get_bind()
    check_names = {
        item.get("name") for item in sa.inspect(bind).get_check_constraints("users")
    }
    if check_names & {"ck_users_final_role", "ck_users_owner_invariants"}:
        with op.batch_alter_table("users") as batch:
            if "ck_users_owner_invariants" in check_names:
                batch.drop_constraint("ck_users_owner_invariants", type_="check")
            if "ck_users_final_role" in check_names:
                batch.drop_constraint("ck_users_final_role", type_="check")

    index_names = {item["name"] for item in sa.inspect(bind).get_indexes("users")}
    if "uq_users_single_system_owner" in index_names:
        op.drop_index("uq_users_single_system_owner", table_name="users")

    role_downgrade = {
        "administrator": "admin",
        "director": "manager",
        "mechanic": "mechanic",
        "observer": "viewer",
    }
    for current, legacy in role_downgrade.items():
        bind.execute(
            sa.text("UPDATE users SET role = :legacy WHERE role = :current"),
            {"legacy": legacy, "current": current},
        )

    existing_columns = _column_names(bind)
    with op.batch_alter_table("users") as batch:
        for name in (
            "token_version",
            "is_system_owner",
            "must_change_password",
            "password_changed_at",
            "last_login_at",
            "updated_at",
        ):
            if name in existing_columns:
                batch.drop_column(name)
