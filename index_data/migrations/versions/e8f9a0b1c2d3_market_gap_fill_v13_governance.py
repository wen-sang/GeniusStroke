"""market_gap_fill_v13_governance

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-06-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EXCHANGE_FIX_CODES = (
    "159206",
    "159530",
    "159745",
    "159766",
    "159819",
    "159845",
    "159915",
    "159920",
    "159996",
    "161725",
)
TYPE_FIX_CODES = ("161725", "501018", "501025")


def upgrade() -> None:
    connection = op.get_bind()
    _validate_asset_values(connection)
    _add_quality_counts(connection)
    _rebuild_task_table(connection, include_confirmed=True)
    _rebuild_asset_state_table(connection, v13=True)
    _extend_tickflow_runtime(connection)
    _create_governance_tables(connection)
    _apply_asset_fixes(connection)


def downgrade() -> None:
    connection = op.get_bind()
    confirmed_count = connection.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM dat_market_gap_fill_task
        WHERE status = 'CONFIRMED'
        """
    ).scalar_one()
    if confirmed_count:
        raise RuntimeError(
            "Cannot downgrade market gap fill v1.3 while CONFIRMED tasks exist"
        )

    _revert_asset_fixes(connection)
    _drop_governance_tables(connection)
    _shrink_tickflow_runtime(connection)
    _rebuild_asset_state_table(connection, v13=False)
    _rebuild_task_table(connection, include_confirmed=False)
    _drop_quality_counts(connection)


def _add_quality_counts(connection) -> None:
    columns = _columns(connection, "dat_data_quality_scan_batch")
    for name in ("open_issue_count", "confirmed_issue_count"):
        if name not in columns:
            connection.exec_driver_sql(
                f"""
                ALTER TABLE dat_data_quality_scan_batch
                ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0
                """
            )
    connection.exec_driver_sql(
        """
        UPDATE dat_data_quality_scan_batch
        SET
            open_issue_count = (
                SELECT COUNT(*)
                FROM dat_data_quality_issue issue
                WHERE issue.scan_batch_id =
                    dat_data_quality_scan_batch.scan_batch_id
                  AND issue.issue_status = 'OPEN'
            ),
            confirmed_issue_count = (
                SELECT COUNT(*)
                FROM dat_data_quality_issue issue
                WHERE issue.scan_batch_id =
                    dat_data_quality_scan_batch.scan_batch_id
                  AND issue.issue_status = 'CONFIRMED'
            )
        """
    )


def _drop_quality_counts(connection) -> None:
    columns = _columns(connection, "dat_data_quality_scan_batch")
    for name in ("confirmed_issue_count", "open_issue_count"):
        if name in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE dat_data_quality_scan_batch DROP COLUMN {name}"
            )


def _rebuild_task_table(connection, include_confirmed: bool) -> None:
    allowed = (
        "'PENDING', 'RUNNING', 'FILLED', 'CONFIRMED', 'FAILED', 'SKIPPED'"
        if include_confirmed
        else "'PENDING', 'RUNNING', 'FILLED', 'FAILED', 'SKIPPED'"
    )
    connection.exec_driver_sql(
        "ALTER TABLE dat_market_gap_fill_task RENAME TO "
        "dat_market_gap_fill_task_old"
    )
    connection.exec_driver_sql(
        f"""
        CREATE TABLE dat_market_gap_fill_task (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_code TEXT NOT NULL,
            missing_date TEXT NOT NULL,
            exchange TEXT,
            asset_type TEXT,
            route_source_id TEXT,
            route_source_code TEXT,
            latest_issue_id INTEGER
                REFERENCES dat_data_quality_issue(id),
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
            last_tdx_package_id TEXT,
            last_tickflow_catalog_version TEXT,
            last_tickflow_config_signature TEXT,
            tickflow_retry_after TEXT,
            detail_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            CONSTRAINT ck_market_gap_fill_task_status
                CHECK (status IN ({allowed})),
            CONSTRAINT uq_market_gap_fill_task_asset_date
                UNIQUE (asset_code, missing_date)
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO dat_market_gap_fill_task (
            task_id,
            asset_code,
            missing_date,
            exchange,
            asset_type,
            route_source_id,
            route_source_code,
            latest_issue_id,
            status,
            attempt_count,
            max_attempts,
            next_retry_at,
            run_id,
            claimed_at,
            claim_expires_at,
            filled_source_id,
            filled_at,
            last_error_code,
            last_error_message,
            last_tdx_package_id,
            last_tickflow_catalog_version,
            last_tickflow_config_signature,
            tickflow_retry_after,
            detail_json,
            created_at,
            updated_at
        )
        SELECT
            task_id,
            asset_code,
            missing_date,
            exchange,
            asset_type,
            route_source_id,
            route_source_code,
            latest_issue_id,
            status,
            attempt_count,
            max_attempts,
            next_retry_at,
            run_id,
            claimed_at,
            claim_expires_at,
            filled_source_id,
            filled_at,
            last_error_code,
            last_error_message,
            last_tdx_package_id,
            last_tickflow_catalog_version,
            last_tickflow_config_signature,
            tickflow_retry_after,
            detail_json,
            created_at,
            updated_at
        FROM dat_market_gap_fill_task_old
        """
    )
    connection.exec_driver_sql("DROP TABLE dat_market_gap_fill_task_old")
    connection.exec_driver_sql(
        """
        CREATE INDEX idx_market_gap_fill_task_status_retry
        ON dat_market_gap_fill_task(status, next_retry_at)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX idx_market_gap_fill_task_asset_status
        ON dat_market_gap_fill_task(
            exchange, asset_code, status, missing_date
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX idx_market_gap_fill_task_issue
        ON dat_market_gap_fill_task(latest_issue_id)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX idx_market_gap_fill_task_claim
        ON dat_market_gap_fill_task(run_id, claim_expires_at)
        """
    )


def _rebuild_asset_state_table(connection, v13: bool) -> None:
    connection.exec_driver_sql(
        "ALTER TABLE dat_market_gap_fill_asset_state RENAME TO "
        "dat_market_gap_fill_asset_state_old"
    )
    if v13:
        connection.exec_driver_sql(
            """
            CREATE TABLE dat_market_gap_fill_asset_state (
                asset_code TEXT PRIMARY KEY,
                target_start_date TEXT,
                earliest_generated_date TEXT,
                tdx_package_id TEXT,
                tdx_exchange TEXT,
                tdx_first_valid_date TEXT,
                tdx_discovery_cursor_date TEXT,
                tdx_discovery_completed_at TEXT,
                tickflow_catalog_signature TEXT,
                tickflow_first_valid_date TEXT,
                tickflow_discovery_status TEXT NOT NULL DEFAULT 'PENDING',
                tickflow_discovery_completed_at TEXT,
                last_discovery_error_code TEXT,
                last_discovery_error_message TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                CONSTRAINT ck_market_gap_fill_asset_state_tickflow_status
                    CHECK (
                        tickflow_discovery_status IN (
                            'NOT_APPLICABLE',
                            'PENDING',
                            'COMPLETED',
                            'FAILED'
                        )
                    )
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO dat_market_gap_fill_asset_state (
                asset_code,
                target_start_date,
                earliest_generated_date,
                tickflow_discovery_status,
                updated_at
            )
            SELECT
                asset.asset_code,
                MIN(market.trade_date),
                NULL,
                CASE
                    WHEN asset.asset_type = 'LOF' THEN 'NOT_APPLICABLE'
                    ELSE 'PENDING'
                END,
                datetime('now', 'localtime')
            FROM sys_asset_meta asset
            LEFT JOIN dat_market_daily market
                ON market.asset_code = asset.asset_code
            WHERE asset.is_active = 1
              AND asset.exchange IN ('SH', 'SZ')
              AND asset.asset_type IN ('STOCK', 'ETF', 'LOF')
            GROUP BY asset.asset_code, asset.asset_type
            """
        )
        connection.exec_driver_sql(
            """
            CREATE INDEX idx_market_gap_fill_asset_discovery
            ON dat_market_gap_fill_asset_state(
                tickflow_discovery_status,
                tdx_discovery_completed_at,
                asset_code
            )
            """
        )
    else:
        connection.exec_driver_sql(
            """
            CREATE TABLE dat_market_gap_fill_asset_state (
                asset_code TEXT PRIMARY KEY,
                target_start_date TEXT NOT NULL,
                earliest_generated_date TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO dat_market_gap_fill_asset_state (
                asset_code,
                target_start_date,
                earliest_generated_date,
                updated_at
            )
            SELECT
                state.asset_code,
                COALESCE(
                    state.target_start_date,
                    asset.listing_date,
                    '2005-01-01'
                ),
                COALESCE(
                    state.target_start_date,
                    asset.listing_date,
                    '2005-01-01'
                ),
                state.updated_at
            FROM dat_market_gap_fill_asset_state_old state
            LEFT JOIN sys_asset_meta asset
                ON asset.asset_code = state.asset_code
            """
        )
    connection.exec_driver_sql(
        "DROP TABLE dat_market_gap_fill_asset_state_old"
    )


def _extend_tickflow_runtime(connection) -> None:
    columns = _columns(connection, "dat_tickflow_gap_fill_runtime")
    for name in (
        "discovery_run_id",
        "discovery_claimed_at",
        "discovery_expires_at",
    ):
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE dat_tickflow_gap_fill_runtime "
                f"ADD COLUMN {name} TEXT"
            )


def _shrink_tickflow_runtime(connection) -> None:
    columns = _columns(connection, "dat_tickflow_gap_fill_runtime")
    for name in (
        "discovery_expires_at",
        "discovery_claimed_at",
        "discovery_run_id",
    ):
        if name in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE dat_tickflow_gap_fill_runtime DROP COLUMN {name}"
            )


def _create_governance_tables(connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE dat_asset_meta_reconcile_log (
            reconcile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            asset_code TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            evidence_code TEXT NOT NULL,
            tdx_package_id TEXT,
            tickflow_catalog_signature TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            CONSTRAINT uq_asset_meta_reconcile_change
                UNIQUE (
                    run_id,
                    asset_code,
                    field_name,
                    old_value,
                    new_value
                )
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX idx_asset_meta_reconcile_asset_created
        ON dat_asset_meta_reconcile_log(asset_code, created_at)
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE dat_market_gap_fill_audit_apply (
            apply_id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id TEXT NOT NULL,
            report_schema_version INTEGER NOT NULL,
            report_hash TEXT NOT NULL,
            scope_fingerprint TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            summary_json TEXT NOT NULL DEFAULT '{}',
            CONSTRAINT uq_market_gap_fill_audit_apply
                UNIQUE (audit_id, report_hash)
        )
        """
    )


def _drop_governance_tables(connection) -> None:
    connection.exec_driver_sql(
        "DROP INDEX IF EXISTS idx_asset_meta_reconcile_asset_created"
    )
    connection.exec_driver_sql(
        "DROP TABLE IF EXISTS dat_market_gap_fill_audit_apply"
    )
    connection.exec_driver_sql(
        "DROP TABLE IF EXISTS dat_asset_meta_reconcile_log"
    )


def _validate_asset_values(connection) -> None:
    _validate_values(
        connection,
        EXCHANGE_FIX_CODES,
        field_name="exchange",
        old_value="SH",
        new_value="SZ",
    )
    _validate_values(
        connection,
        TYPE_FIX_CODES,
        field_name="asset_type",
        old_value="ETF",
        new_value="LOF",
    )


def _validate_values(
    connection,
    asset_codes: tuple[str, ...],
    field_name: str,
    old_value: str,
    new_value: str,
) -> None:
    placeholders = ", ".join("?" for _ in asset_codes)
    rows = connection.exec_driver_sql(
        f"""
        SELECT asset_code, {field_name}
        FROM sys_asset_meta
        WHERE asset_code IN ({placeholders})
        """,
        asset_codes,
    ).fetchall()
    values = {row[0]: row[1] for row in rows}
    for asset_code in asset_codes:
        value = values.get(asset_code)
        if asset_code not in values:
            continue
        if value not in {old_value, new_value}:
            raise RuntimeError(
                f"Unexpected {field_name} for {asset_code}: {value!r}"
            )


def _apply_asset_fixes(connection) -> None:
    for asset_code in EXCHANGE_FIX_CODES:
        old_value = connection.exec_driver_sql(
            "SELECT exchange FROM sys_asset_meta WHERE asset_code = ?",
            (asset_code,),
        ).scalar_one_or_none()
        if old_value is None:
            continue
        if old_value == "SH":
            connection.exec_driver_sql(
                "UPDATE sys_asset_meta SET exchange = 'SZ' "
                "WHERE asset_code = ? AND exchange = 'SH'",
                (asset_code,),
            )
            _insert_reconcile_log(
                connection, asset_code, "exchange", "SH", "SZ"
            )
        connection.exec_driver_sql(
            """
            UPDATE dat_market_gap_fill_task
            SET exchange = 'SZ',
                updated_at = datetime('now', 'localtime')
            WHERE asset_code = ?
              AND status != 'FILLED'
            """,
            (asset_code,),
        )

    for asset_code in TYPE_FIX_CODES:
        old_value = connection.exec_driver_sql(
            "SELECT asset_type FROM sys_asset_meta WHERE asset_code = ?",
            (asset_code,),
        ).scalar_one_or_none()
        if old_value is None:
            continue
        if old_value == "ETF":
            connection.exec_driver_sql(
                "UPDATE sys_asset_meta SET asset_type = 'LOF' "
                "WHERE asset_code = ? AND asset_type = 'ETF'",
                (asset_code,),
            )
            _insert_reconcile_log(
                connection, asset_code, "asset_type", "ETF", "LOF"
            )
        connection.exec_driver_sql(
            """
            UPDATE sys_data_router
            SET asset_type = 'LOF'
            WHERE asset_code = ?
              AND asset_type = 'ETF'
            """,
            (asset_code,),
        )
        connection.exec_driver_sql(
            """
            UPDATE dat_market_gap_fill_task
            SET asset_type = 'LOF',
                updated_at = datetime('now', 'localtime')
            WHERE asset_code = ?
              AND status != 'FILLED'
            """,
            (asset_code,),
        )
        connection.exec_driver_sql(
            """
            UPDATE dat_market_gap_fill_asset_state
            SET tickflow_discovery_status = 'NOT_APPLICABLE',
                updated_at = datetime('now', 'localtime')
            WHERE asset_code = ?
            """,
            (asset_code,),
        )


def _revert_asset_fixes(connection) -> None:
    changed_types = {
        row[0]
        for row in connection.exec_driver_sql(
            """
            SELECT asset_code
            FROM dat_asset_meta_reconcile_log
            WHERE run_id = 'migration_v13'
              AND field_name = 'asset_type'
              AND old_value = 'ETF'
              AND new_value = 'LOF'
            """
        ).fetchall()
    }
    for asset_code in changed_types:
        connection.exec_driver_sql(
            "UPDATE sys_asset_meta SET asset_type = 'ETF' "
            "WHERE asset_code = ? AND asset_type = 'LOF'",
            (asset_code,),
        )
        connection.exec_driver_sql(
            "UPDATE sys_data_router SET asset_type = 'ETF' "
            "WHERE asset_code = ? AND asset_type = 'LOF'",
            (asset_code,),
        )
        connection.exec_driver_sql(
            "UPDATE dat_market_gap_fill_task SET asset_type = 'ETF' "
            "WHERE asset_code = ? AND status != 'FILLED'",
            (asset_code,),
        )
    changed_exchanges = {
        row[0]
        for row in connection.exec_driver_sql(
            """
            SELECT asset_code
            FROM dat_asset_meta_reconcile_log
            WHERE run_id = 'migration_v13'
              AND field_name = 'exchange'
              AND old_value = 'SH'
              AND new_value = 'SZ'
            """
        ).fetchall()
    }
    for asset_code in changed_exchanges:
        connection.exec_driver_sql(
            "UPDATE sys_asset_meta SET exchange = 'SH' "
            "WHERE asset_code = ? AND exchange = 'SZ'",
            (asset_code,),
        )
        connection.exec_driver_sql(
            "UPDATE dat_market_gap_fill_task SET exchange = 'SH' "
            "WHERE asset_code = ? AND status != 'FILLED'",
            (asset_code,),
        )


def _insert_reconcile_log(
    connection,
    asset_code: str,
    field_name: str,
    old_value: str,
    new_value: str,
) -> None:
    connection.exec_driver_sql(
        """
        INSERT OR IGNORE INTO dat_asset_meta_reconcile_log (
            run_id,
            asset_code,
            field_name,
            old_value,
            new_value,
            evidence_code
        )
        VALUES (
            'migration_v13',
            ?,
            ?,
            ?,
            ?,
            'APPROVED_V13_DATA_FIX'
        )
        """,
        (asset_code, field_name, old_value, new_value),
    )


def _columns(connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.exec_driver_sql(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }
