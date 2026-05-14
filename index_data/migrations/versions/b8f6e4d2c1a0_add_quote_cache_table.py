"""add_quote_cache_table

Revision ID: b8f6e4d2c1a0
Revises: 9f4c2d7b1a6e
Create Date: 2026-03-13 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8f6e4d2c1a0"
down_revision: Union[str, Sequence[str], None] = "a3b8d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dat_realtime_quote_cache (
            asset_code TEXT PRIMARY KEY,
            asset_name TEXT,
            price REAL,
            high REAL,
            low REAL,
            volume REAL,
            amount REAL,
            amplitude REAL,
            change_pct REAL,
            change_amt REAL,
            turnover REAL,
            quote_date TEXT,
            source TEXT,
            is_realtime INTEGER DEFAULT 0,
            refreshed_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_quote_cache_refreshed_at ON dat_realtime_quote_cache(refreshed_at)"
    )


def downgrade() -> None:
    raise NotImplementedError("Quote cache table migration is not safely reversible on SQLite.")
