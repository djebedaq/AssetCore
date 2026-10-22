"""Explicit legacy selections without changing any historical selection row."""
import sqlalchemy as sa
from alembic import op

revision = "20261019_0038"
down_revision = "20261019_0037"
branch_labels = None
depends_on = None


def upgrade():
    if "selection_kind" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("studio_activations")}:
        op.add_column("studio_activations", sa.Column("selection_kind", sa.String(12), nullable=False, server_default="STUDIO"))


def downgrade():
    # Historical restore events cannot be silently reinterpreted as activations.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM studio_activations WHERE selection_kind != 'STUDIO'")):
        raise RuntimeError("Studio legacy selection history cannot be discarded")
    op.drop_column("studio_activations", "selection_kind")
