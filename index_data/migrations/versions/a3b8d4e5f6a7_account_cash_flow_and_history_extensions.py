"""account_cash_flow_and_history_extensions

Revision ID: a3b8d4e5f6a7
Revises: 9f4c2d7b1a6e
Create Date: 2026-03-10 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a3b8d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "9f4c2d7b1a6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(connection, table_name: str, column_name: str) -> bool:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_cash_flow (
            flow_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            biz_date TEXT NOT NULL,
            flow_type TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'IN',
            amount REAL NOT NULL,
            remark TEXT,
            source_type TEXT,
            source_ref_id TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (account_id) REFERENCES sys_account_fund(account_id)
        );
        """
    )

    alter_statements = [
        ("account_cash_flow", "direction", "TEXT DEFAULT 'IN'"),
        ("trade_order", "source_type", "TEXT"),
        ("trade_order", "source_ref_id", "TEXT"),
        ("dat_account_history", "daily_return_rate", "REAL"),
        ("dat_account_history", "cum_realized_pnl", "REAL"),
        ("dat_account_history", "cum_unrealized_pnl", "REAL"),
        ("dat_account_history", "cum_total_pnl", "REAL"),
        ("dat_account_history", "account_xirr", "REAL"),
        ("dat_account_history", "is_data_complete", "INTEGER DEFAULT 0"),
    ]

    for table_name, column_name, column_def in alter_statements:
        if not _has_column(connection, table_name, column_name):
            connection.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
            )

    index_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_cash_flow_account_date ON account_cash_flow(account_id, biz_date)",
        "CREATE INDEX IF NOT EXISTS idx_cash_flow_source ON account_cash_flow(source_type, source_ref_id)",
    ]
    for index_sql in index_sqls:
        connection.exec_driver_sql(index_sql)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "This SQLite migration is not safely reversible because it adds columns."
    )
