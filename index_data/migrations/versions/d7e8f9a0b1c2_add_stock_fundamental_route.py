"""add_stock_fundamental_route

Revision ID: d7e8f9a0b1c2
Revises: c3d4e5f6a7b8
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        INSERT INTO sys_data_router (
            asset_type,
            interface,
            source_id,
            priority
        )
        SELECT 'STOCK', 'fundamental', 'lixinren', 100
        WHERE NOT EXISTS (
            SELECT 1
            FROM sys_data_router
            WHERE asset_type = 'STOCK'
              AND interface = 'fundamental'
        )
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        DELETE FROM sys_data_router
        WHERE asset_code IS NULL
          AND asset_type = 'STOCK'
          AND interface = 'fundamental'
          AND source_id = 'lixinren'
          AND priority = 100
        """
    )
