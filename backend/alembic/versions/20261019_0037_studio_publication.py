"""Explicit Studio activation history; existing versions/files remain unchanged."""
import sqlalchemy as sa
from alembic import op
from app.document_studio.guards import statements

revision = "20261019_0037"
down_revision = "20261019_0036"
branch_labels = None
depends_on = None


def upgrade():
    if "studio_activations" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("studio_activations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("document_type", sa.String(80), nullable=False),
            sa.Column("language", sa.String(2), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("version_id", sa.Integer(), sa.ForeignKey("document_template_versions.id"), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.UniqueConstraint("document_type", "language", "revision", name="uq_studio_activation_revision"))
        op.create_index("ix_studio_activations_document_type", "studio_activations", ["document_type"])
    for statement in statements(op.get_bind().dialect.name):
        op.execute(sa.text(statement))


def downgrade():
    connection = op.get_bind()
    if (connection.scalar(sa.text("SELECT count(*) FROM studio_activations"))
            or connection.scalar(sa.text("SELECT count(*) FROM document_template_versions WHERE " +
                ("layout_contract->>'studio' = '1'" if connection.dialect.name == "postgresql" else "json_extract(layout_contract, '$.studio') = 1")))):
        raise RuntimeError("Studio activation history cannot be discarded")
    for table in ("document_template_versions", "studio_activations", "company_brand_images"):
        for operation in ("update", "delete"):
            name = f"freeze_studio_{table}_{operation}"
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}" + (f" ON {table}" if connection.dialect.name == "postgresql" else "")))
            if connection.dialect.name == "postgresql":
                op.execute(sa.text(f"DROP FUNCTION IF EXISTS {name}()"))
    op.drop_table("studio_activations")
