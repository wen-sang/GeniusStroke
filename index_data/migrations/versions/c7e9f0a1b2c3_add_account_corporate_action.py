"""add_account_corporate_action

Revision ID: c7e9f0a1b2c3
Revises: b8f6e4d2c1a0
Create Date: 2026-03-28 16:35:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c7e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "b8f6e4d2c1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    raw_connection = connection.connection

    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_corporate_action (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            asset_code TEXT NOT NULL,
            action_type TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            record_date TEXT,
            cash_base_unit TEXT,
            cash_amount REAL,
            ratio_from INTEGER,
            ratio_to INTEGER,
            reinvest_price REAL,
            rounding_policy TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            remark TEXT,
            source_type TEXT NOT NULL DEFAULT 'MANUAL',
            source_ref_id TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (account_id) REFERENCES sys_account_fund(account_id)
        );
        """
    )

    index_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_corp_action_account_date ON account_corporate_action(account_id, effective_date DESC, action_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_corp_action_asset_date ON account_corporate_action(account_id, asset_code, effective_date DESC, action_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_corp_action_status ON account_corporate_action(account_id, status, effective_date DESC)",
    ]
    for index_sql in index_sqls:
        connection.exec_driver_sql(index_sql)


def downgrade() -> None:
    raise NotImplementedError(
        "Corporate action table migration is not safely reversible on SQLite."
    )
