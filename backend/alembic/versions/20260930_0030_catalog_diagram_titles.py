"""Preserve complete Builder diagram captions at the authoring limits.

Revision ID: 20260930_0030
Revises: 20260929_0029
"""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0030"
down_revision = "20260929_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    column = next(item for item in sa.inspect(op.get_bind()).get_columns("catalog_diagrams")
                  if item["name"] == "title")
    if isinstance(column["type"], sa.Text):
        return
    with op.batch_alter_table("catalog_diagrams") as batch:
        batch.alter_column("title", existing_type=sa.String(500), type_=sa.Text(),
                           existing_nullable=False)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM catalog_diagrams WHERE length(title) > 500"
    )):
        raise RuntimeError("Cannot downgrade: a catalog diagram title exceeds 500 characters")
    with op.batch_alter_table("catalog_diagrams") as batch:
        batch.alter_column("title", existing_type=sa.Text(), type_=sa.String(500),
                           existing_nullable=False)
