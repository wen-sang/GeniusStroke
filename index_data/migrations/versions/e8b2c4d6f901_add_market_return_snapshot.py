"""add_market_return_snapshot

Revision ID: e8b2c4d6f901
Revises: e5a1b2c3d4f8
Create Date: 2026-05-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e8b2c4d6f901"
down_revision: Union[str, Sequence[str], None] = "e5a1b2c3d4f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS dat_market_return_snapshot (
            asset_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            return_22d REAL,
            return_60d REAL,
            return_6m REAL,
            return_1y REAL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (asset_code, trade_date)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_market_return_snapshot_date_code
        ON dat_market_return_snapshot(trade_date, asset_code)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_market_return_snapshot_date_22d
        ON dat_market_return_snapshot(trade_date, return_22d)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_market_return_snapshot_date_60d
        ON dat_market_return_snapshot(trade_date, return_60d)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_market_return_snapshot_date_6m
        ON dat_market_return_snapshot(trade_date, return_6m)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_market_return_snapshot_date_1y
        ON dat_market_return_snapshot(trade_date, return_1y)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_market_date_amount_code
        ON dat_market_daily(trade_date, amount, asset_code)
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_market_date_amount_code")
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_market_return_snapshot_date_1y")
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_market_return_snapshot_date_6m")
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_market_return_snapshot_date_60d")
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_market_return_snapshot_date_22d")
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_market_return_snapshot_date_code")
    connection.exec_driver_sql("DROP TABLE IF EXISTS dat_market_return_snapshot")
