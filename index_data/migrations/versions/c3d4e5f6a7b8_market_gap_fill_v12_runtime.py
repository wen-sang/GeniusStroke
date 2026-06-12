"""market_gap_fill_v12_runtime

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-11 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(dat_market_gap_fill_task)"
        ).fetchall()
    }
    additions = {
        "last_tdx_package_id": "TEXT",
        "last_tickflow_catalog_version": "TEXT",
        "last_tickflow_config_signature": "TEXT",
        "tickflow_retry_after": "TEXT",
    }
    for name, column_type in additions.items():
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE dat_market_gap_fill_task "
                f"ADD COLUMN {name} {column_type}"
            )

    connection.connection.executescript(
        """
        DROP INDEX IF EXISTS idx_market_gap_fill_task_asset_status;
        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_task_asset_status
        ON dat_market_gap_fill_task(
            exchange, asset_code, status, missing_date
        );

        CREATE TABLE IF NOT EXISTS dat_market_gap_fill_repair_task (
            repair_id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_code TEXT NOT NULL UNIQUE,
            from_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            generation INTEGER NOT NULL DEFAULT 1,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempt_sync_id TEXT,
            run_id TEXT,
            claimed_at TEXT,
            claim_expires_at TEXT,
            last_failed_stage TEXT,
            last_error_code TEXT,
            last_error_message TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            CONSTRAINT ck_market_gap_fill_repair_task_status
                CHECK (status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED'))
        );

        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_repair_status_sync
        ON dat_market_gap_fill_repair_task(status, last_attempt_sync_id);

        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_repair_claim
        ON dat_market_gap_fill_repair_task(run_id, claim_expires_at);

        CREATE TABLE IF NOT EXISTS dat_tickflow_gap_fill_runtime (
            runtime_id INTEGER PRIMARY KEY,
            last_request_started_at TEXT,
            breaker_state TEXT NOT NULL DEFAULT 'CLOSED',
            breaker_reason TEXT,
            breaker_until TEXT,
            breaker_config_signature TEXT,
            consecutive_error_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            CONSTRAINT ck_tickflow_gap_fill_runtime_singleton
                CHECK (runtime_id = 1),
            CONSTRAINT ck_tickflow_gap_fill_runtime_breaker_state
                CHECK (breaker_state IN ('CLOSED', 'OPEN'))
        );

        INSERT OR IGNORE INTO dat_tickflow_gap_fill_runtime(runtime_id)
        VALUES (1);

        INSERT INTO dat_market_gap_fill_repair_task (
            asset_code,
            from_date,
            status,
            generation
        )
        SELECT
            asset_code,
            MIN(missing_date),
            'PENDING',
            1
        FROM dat_market_gap_fill_task
        WHERE status = 'FILLED'
        GROUP BY asset_code
        ON CONFLICT(asset_code) DO UPDATE SET
            from_date = MIN(
                dat_market_gap_fill_repair_task.from_date,
                excluded.from_date
            ),
            status = 'PENDING',
            completed_at = NULL,
            updated_at = datetime('now', 'localtime');
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.connection.executescript(
        """
        DROP INDEX IF EXISTS idx_market_gap_fill_repair_claim;
        DROP INDEX IF EXISTS idx_market_gap_fill_repair_status_sync;
        DROP TABLE IF EXISTS dat_tickflow_gap_fill_runtime;
        DROP TABLE IF EXISTS dat_market_gap_fill_repair_task;

        DROP INDEX IF EXISTS idx_market_gap_fill_task_asset_status;
        CREATE INDEX IF NOT EXISTS idx_market_gap_fill_task_asset_status
        ON dat_market_gap_fill_task(asset_code, status);
        """
    )
    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(dat_market_gap_fill_task)"
        ).fetchall()
    }
    for name in (
        "tickflow_retry_after",
        "last_tickflow_config_signature",
        "last_tickflow_catalog_version",
        "last_tdx_package_id",
    ):
        if name in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE dat_market_gap_fill_task DROP COLUMN {name}"
            )
