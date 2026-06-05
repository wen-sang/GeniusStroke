"""add_market_gap_fill_tables

Revision ID: a9c4e5f6b7d8
Revises: f1a2b3c4d5e6
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a9c4e5f6b7d8"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    raw_connection = connection.connection
    raw_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dat_market_gap_fill_task (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_code TEXT NOT NULL,
            missing_date TEXT NOT NULL,
            exchange TEXT,
            asset_type TEXT,
            route_source_id TEXT,
            route_source_code TEXT,
            latest_issue_id INTEGER,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            next_retry_at TEXT,
            run_id TEXT,
            claimed_at TEXT,
            claim_expires_at TEXT,
            filled_source_id TEXT,
            filled_at TEXT,
            last_error_code TEXT,
            last_error_message TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            CONSTRAINT fk_market_gap_fill_task_issue
                FOREIGN KEY (latest_issue_id)
                REFERENCES dat_data_quality_issue(id),
            CONSTRAINT ck_market_gap_fill_task_status
                CHECK (status IN (
                    'PENDING', 'RUNNING', 'FILLED', 'FAILED', 'SKIPPED'
                )),
            CONSTRAINT uq_market_gap_fill_task_asset_date
                UNIQUE (asset_code, missing_date)
        );

        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_task_status_retry
        ON dat_market_gap_fill_task(status, next_retry_at);

        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_task_asset_status
        ON dat_market_gap_fill_task(asset_code, status);

        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_task_issue
        ON dat_market_gap_fill_task(latest_issue_id);

        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_task_claim
        ON dat_market_gap_fill_task(run_id, claim_expires_at);

        CREATE TABLE IF NOT EXISTS dat_market_gap_fill_asset_state (
            asset_code TEXT PRIMARY KEY,
            target_start_date TEXT NOT NULL,
            earliest_generated_date TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    index_names = [
        "idx_market_gap_fill_task_claim",
        "idx_market_gap_fill_task_issue",
        "idx_market_gap_fill_task_asset_status",
        "idx_market_gap_fill_task_status_retry",
    ]
    for index_name in index_names:
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")
    connection.exec_driver_sql("DROP TABLE IF EXISTS dat_market_gap_fill_asset_state")
    connection.exec_driver_sql("DROP TABLE IF EXISTS dat_market_gap_fill_task")
