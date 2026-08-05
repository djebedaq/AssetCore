"""Allow external transfer signers to be stored with three names only.

Revision ID: 20260805_0007
Revises: 20260801_0006
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_0007"
down_revision = "20260801_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("external_signers") as batch:
            batch.alter_column("job_title", existing_type=sa.String(255), nullable=True)
    else:
        op.alter_column("external_signers", "job_title", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("external_signers") as batch:
            batch.alter_column("job_title", existing_type=sa.String(255), nullable=False)
    else:
        op.alter_column("external_signers", "job_title", existing_type=sa.String(255), nullable=False)
