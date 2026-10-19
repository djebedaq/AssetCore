"""Single-installation identity and authoring workspaces; no data migration."""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0036"
down_revision = "20261015_0035"
branch_labels = None
depends_on = None


def upgrade():
    # Baseline revision 0001 also supports a fresh install via current metadata.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "company_profiles" not in existing:
        op.create_table("company_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("identity", sa.JSON(), nullable=False),
            sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("id = 1", name="ck_company_profile_singleton"),
            sa.CheckConstraint("revision > 0", name="ck_company_profile_revision"))
    if "company_brand_images" not in existing:
        op.create_table("company_brand_images",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("purpose", sa.String(20), nullable=False),
            sa.Column("filename", sa.String(120), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False))
    if "document_editor_drafts" not in existing:
        op.create_table("document_editor_drafts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("template_id", sa.Integer(), sa.ForeignKey("document_templates.id"), nullable=False),
            sa.Column("base_version_id", sa.Integer(), sa.ForeignKey("document_template_versions.id")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("language", sa.String(2), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("layout", sa.JSON(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("revision > 0", name="ck_editor_draft_revision"))
        op.create_index("ix_document_editor_drafts_template_id", "document_editor_drafts", ["template_id"])


def downgrade():
    connection = op.get_bind()
    names = ("document_editor_drafts", "company_profiles", "company_brand_images")
    existing = set(sa.inspect(connection).get_table_names())
    for name in names:
        if name in existing and connection.scalar(sa.select(sa.func.count()).select_from(sa.table(name))):
            raise RuntimeError("Document Studio history cannot be discarded by downgrade")
    for name in names:
        if name in existing:
            op.drop_table(name)
