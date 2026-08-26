"""Add durable browser sessions and authentication throttling.

Revision ID: 20260826_0021
Revises: 20260826_0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260826_0021"
down_revision = "20260826_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 adopts pre-Alembic databases through current metadata.
    # Fresh installations can therefore already contain these new tables when
    # they reach 0021; existing installations at 0020 do not. Keep both paths
    # safe without altering any published historical migration.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
            sa.Column("user_token_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_reason", sa.String(length=80), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        )
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
        op.create_index("ix_auth_sessions_created_at", "auth_sessions", ["created_at"])
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
        op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"])

    if "authentication_throttles" not in tables:
        op.create_table(
            "authentication_throttles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scope", sa.String(length=50), nullable=False),
            sa.Column("key_hash", sa.String(length=64), nullable=False),
            sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("window_started_at", sa.DateTime(), nullable=False),
            sa.Column("blocked_until", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "failure_count >= 0", name="ck_authentication_throttle_failures"
            ),
            sa.UniqueConstraint(
                "scope", "key_hash", name="uq_authentication_throttle_scope_key"
            ),
        )
        op.create_index(
            "ix_authentication_throttles_scope",
            "authentication_throttles",
            ["scope"],
        )
        op.create_index(
            "ix_authentication_throttles_blocked_until",
            "authentication_throttles",
            ["blocked_until"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "authentication_throttles" in tables:
        op.drop_table("authentication_throttles")
    if "auth_sessions" in tables:
        op.drop_table("auth_sessions")
