"""corporate_action_v2_state_model

Revision ID: d4f7a9c2b1e3
Revises: c7e9f0a1b2c3
Create Date: 2026-03-30 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4f7a9c2b1e3"
down_revision: Union[str, Sequence[str], None] = "c7e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(connection, table_name: str, column_name: str) -> bool:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)


def _ensure_column(connection, table_name: str, column_name: str, column_sql: str) -> None:
    if _has_column(connection, table_name, column_name):
        return
    connection.exec_driver_sql(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
    )


def upgrade() -> None:
    connection = op.get_bind()

    _ensure_column(connection, "account_corporate_action", "confirmed_at", "TEXT")
    _ensure_column(connection, "account_corporate_action", "last_check_at", "TEXT")
    _ensure_column(connection, "account_corporate_action", "last_error_message", "TEXT")
    _ensure_column(connection, "trade_order", "order_type", "TEXT")
    _ensure_column(connection, "account_cash_flow", "status", "TEXT DEFAULT 'ACTIVE'")

    connection.exec_driver_sql(
        """
        UPDATE account_corporate_action
        SET status = CASE
            WHEN status = 'ACTIVE' THEN 'CONFIRMED'
            ELSE status
        END
        WHERE status IN ('ACTIVE', 'CANCELLED')
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE account_corporate_action
        SET confirmed_at = COALESCE(confirmed_at, updated_at, created_at, datetime('now', 'localtime'))
        WHERE status = 'CONFIRMED' AND (confirmed_at IS NULL OR confirmed_at = '')
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE trade_order
        SET order_type = CASE
            WHEN COALESCE(source_type, '') = 'CORPORATE_ACTION' AND side = 'BUY' THEN 'DIVIDEND_REINVEST_BUY'
            WHEN COALESCE(source_type, '') = 'CORPORATE_ACTION' AND side = 'ADJUST' THEN 'SPLIT_ADJUST'
            WHEN side = 'BUY' THEN 'MANUAL_BUY'
            WHEN side = 'SELL' THEN 'MANUAL_SELL'
            ELSE order_type
        END
        WHERE order_type IS NULL OR order_type = ''
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE account_cash_flow
        SET status = 'ACTIVE'
        WHERE status IS NULL OR status = ''
        """
    )

    index_sqls = [
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_order_corp_source_order_type ON trade_order(source_ref_id, order_type) WHERE source_type = 'CORPORATE_ACTION' AND source_ref_id IS NOT NULL AND status = 1",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_flow_corp_source_flow_type ON account_cash_flow(source_ref_id, flow_type) WHERE source_type = 'CORPORATE_ACTION' AND source_ref_id IS NOT NULL AND status = 'ACTIVE'",
    ]
    for index_sql in index_sqls:
        connection.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError(
        "Corporate action v2 state-model migration is not safely reversible on SQLite."
    )
