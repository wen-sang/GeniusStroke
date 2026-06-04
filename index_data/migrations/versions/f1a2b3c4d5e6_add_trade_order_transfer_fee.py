"""add_trade_order_transfer_fee

Revision ID: f1a2b3c4d5e6
Revises: c798a3607fe2
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c798a3607fe2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {
        row[1]
        for row in connection.exec_driver_sql("PRAGMA table_info(trade_order)").fetchall()
    }
    if "transfer_fee" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE trade_order ADD COLUMN transfer_fee REAL DEFAULT 0"
        )


def downgrade() -> None:
    connection = op.get_bind()
    columns = {
        row[1]
        for row in connection.exec_driver_sql("PRAGMA table_info(trade_order)").fetchall()
    }
    if "transfer_fee" in columns:
        op.drop_column("trade_order", "transfer_fee")
