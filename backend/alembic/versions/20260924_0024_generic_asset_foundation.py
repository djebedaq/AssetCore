"""Nullable asset pressure and extensible category capabilities.

Revision ID: 20260924_0024
Revises: 20260923_0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0024"
down_revision = "20260923_0023"
branch_labels = None
depends_on = None

HPWJ_CAPABILITIES = [
    "HAS_PRESSURE", "HAS_PARTS_CATALOG", "HAS_REPAIR_WORKFLOW", "HAS_TRANSFER_WORKFLOW"
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    category_columns = {item["name"] for item in inspector.get_columns("asset_categories")}
    if "capabilities" not in category_columns:
        op.add_column(
            "asset_categories",
            sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
        )
    categories = sa.table(
        "asset_categories", sa.column("id", sa.Integer()),
        sa.column("code", sa.String()), sa.column("capabilities", sa.JSON()),
    )
    bind.execute(
        sa.update(categories).where(categories.c.code == "HPWJ")
        .values(capabilities=HPWJ_CAPABILITIES)
    )
    # Exact code matches only. Existing unmatched legacy labels remain intact.
    bind.execute(sa.text(
        "UPDATE machines SET category_id = (SELECT id FROM asset_categories "
        "WHERE code = machines.category) WHERE category_id IS NULL "
        "AND EXISTS (SELECT 1 FROM asset_categories WHERE code = machines.category)"
    ))
    # For an already linked asset, the referenced category is authoritative.
    bind.execute(sa.text(
        "UPDATE machines SET category = (SELECT code FROM asset_categories "
        "WHERE id = machines.category_id) WHERE category_id IS NOT NULL "
        "AND category <> (SELECT code FROM asset_categories WHERE id = machines.category_id)"
    ))
    pressure_column = next(
        item for item in sa.inspect(bind).get_columns("machines")
        if item["name"] == "pressure_bar"
    )
    if not pressure_column["nullable"]:
        with op.batch_alter_table("machines") as batch:
            batch.alter_column("pressure_bar", existing_type=sa.Integer(),
                               nullable=True, server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM machines WHERE pressure_bar IS NULL")):
        raise RuntimeError("Cannot downgrade: assets with no pressure would require invented values")
    with op.batch_alter_table("machines") as batch:
        batch.alter_column("pressure_bar", existing_type=sa.Integer(),
                           nullable=False)
    op.drop_column("asset_categories", "capabilities")
