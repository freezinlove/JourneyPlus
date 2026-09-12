"""version document normalization by parser version

Revision ID: 0005_document_parser_versions
Revises: 0004_daily_automation
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_document_parser_versions"
down_revision = "0004_daily_automation"
branch_labels = None
depends_on = None


_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
}


def upgrade() -> None:
    old_constraint = next(
        (
            constraint
            for constraint in sa.inspect(op.get_bind()).get_unique_constraints(
                "document_versions"
            )
            if constraint["column_names"] == ["source_item_id", "raw_hash"]
        ),
        None,
    )
    if old_constraint is None:
        raise RuntimeError("document_versions raw hash constraint was not found")
    old_constraint_name = (
        old_constraint["name"]
        or "uq_document_versions_source_item_id_raw_hash"
    )
    with op.batch_alter_table(
        "document_versions", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            old_constraint_name, type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_document_versions_source_item_raw_parser",
            ["source_item_id", "raw_hash", "parser_version"],
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "document_versions", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_document_versions_source_item_raw_parser", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_document_versions_source_item_id_raw_hash",
            ["source_item_id", "raw_hash"],
        )
