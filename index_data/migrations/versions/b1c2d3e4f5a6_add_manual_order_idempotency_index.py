"""add_manual_order_idempotency_index

Revision ID: b1c2d3e4f5a6
Revises: a7b9c0d1e2f3
Create Date: 2026-05-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a7b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_order_manual_source_ref
        ON trade_order(account_id, source_ref_id)
        WHERE source_type = 'MANUAL'
          AND source_ref_id IS NOT NULL
          AND status = 1
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP INDEX IF EXISTS uq_trade_order_manual_source_ref")
