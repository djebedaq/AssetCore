"""Many catalogs per machine; keep deactivated bindings as history."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0034"
down_revision = "20261009_0033"
branch_labels = None
depends_on = None


def upgrade():
    # 0025 used an unnamed constraint. Naming convention also handles SQLite
    # reflection; PostgreSQL reports its actual generated constraint name.
    inspector = sa.inspect(op.get_bind())
    constraints = inspector.get_unique_constraints("catalog_asset_bindings")
    unique = next((item for item in constraints if item["column_names"] == ["machine_id"]), None)
    # The initial bootstrap creates current metadata on a new installation.
    if unique is None and {"is_active", "deactivated_at"} <= {
        item["name"] for item in inspector.get_columns("catalog_asset_bindings")
    }:
        return
    if unique is None:
        raise RuntimeError("Unexpected catalog binding schema")
    with op.batch_alter_table(
        "catalog_asset_bindings", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch:
        batch.drop_constraint(
            unique["name"] or "uq_catalog_asset_bindings_machine_id", type_="unique"
        )
        batch.add_column(
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False)
        )
        batch.add_column(sa.Column("deactivated_at", sa.DateTime(), nullable=True))
        batch.create_unique_constraint("uq_catalog_machine_binding", ["catalog_id", "machine_id"])
        batch.create_index("ix_catalog_asset_bindings_machine_id", ["machine_id"])


def downgrade():
    # Never silently discard a second catalog or inactive historical binding.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT machine_id FROM catalog_asset_bindings "
                "GROUP BY machine_id HAVING COUNT(*) > 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Multiple catalog bindings require explicit resolution before downgrade")
    with op.batch_alter_table("catalog_asset_bindings") as batch:
        batch.drop_index("ix_catalog_asset_bindings_machine_id")
        batch.drop_constraint("uq_catalog_machine_binding", type_="unique")
        batch.drop_column("deactivated_at")
        batch.drop_column("is_active")
        batch.create_unique_constraint("uq_catalog_asset_bindings_machine_id", ["machine_id"])
