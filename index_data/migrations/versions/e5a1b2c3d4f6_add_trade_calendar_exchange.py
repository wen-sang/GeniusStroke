"""add_trade_calendar_exchange

Revision ID: e5a1b2c3d4f6
Revises: d4f7a9c2b1e3
Create Date: 2026-04-30 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5a1b2c3d4f6"
down_revision: Union[str, Sequence[str], None] = "d4f7a9c2b1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS trade_calendar_exchange (
            exchange TEXT NOT NULL,
            calendar_date TEXT NOT NULL,
            is_open INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (exchange, calendar_date),
            CONSTRAINT ck_trade_calendar_exchange_exchange
                CHECK (exchange IN ('SH', 'SZ', 'HK')),
            CONSTRAINT ck_trade_calendar_exchange_is_open
                CHECK (is_open IN (0, 1))
        );
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_trade_calendar_exchange_open_date
        ON trade_calendar_exchange(exchange, is_open, calendar_date)
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "DROP INDEX IF EXISTS idx_trade_calendar_exchange_open_date"
    )
    connection.exec_driver_sql("DROP TABLE IF EXISTS trade_calendar_exchange")
