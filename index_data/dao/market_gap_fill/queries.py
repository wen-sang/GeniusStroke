# 文件: dao/market_gap_fill/queries.py
"""缺口治理状态与统计查询。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


class QueryMixin:
    def list_missing_bar_issues_for_batch(self, scan_batch_id: str) -> list[dict]:
        sql = """
        SELECT
            i.id,
            i.asset_code,
            i.trade_date,
            m.exchange,
            m.asset_type,
            NULL AS route_source_id,
            NULL AS route_source_code
        FROM dat_data_quality_issue i
        JOIN sys_asset_meta m ON m.asset_code = i.asset_code
        WHERE i.scan_batch_id = ?
          AND i.rule_code = 'MISSING_TRADING_DAY_BAR'
        ORDER BY i.asset_code, i.trade_date
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (scan_batch_id,))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def get_asset_state(self, asset_code: str) -> dict:
        sql = """
        SELECT *
        FROM dat_market_gap_fill_asset_state
        WHERE asset_code = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            return self._row_to_dict(cursor, cursor.fetchone())

    def upsert_asset_state(
        self,
        asset_code: str,
        target_start_date: str | None,
        earliest_generated_date: str | None = None,
        **fields: Any,
    ) -> None:
        allowed_fields = {
            "tdx_package_id",
            "tdx_exchange",
            "tdx_first_valid_date",
            "tdx_discovery_cursor_date",
            "tdx_discovery_completed_at",
            "tickflow_catalog_signature",
            "tickflow_first_valid_date",
            "tickflow_discovery_status",
            "tickflow_discovery_completed_at",
            "last_discovery_error_code",
            "last_discovery_error_message",
        }
        invalid = set(fields) - allowed_fields
        if invalid:
            raise ValueError(f"Unsupported asset state fields: {sorted(invalid)}")
        columns = [
            "asset_code",
            "target_start_date",
            "earliest_generated_date",
            *fields,
        ]
        values = [asset_code, target_start_date, earliest_generated_date]
        values.extend(fields[name] for name in fields)
        update_columns = columns[1:]
        sql = f"""
        INSERT INTO dat_market_gap_fill_asset_state (
            {', '.join(columns)},
            updated_at
        )
        VALUES (
            {', '.join('?' for _ in columns)},
            datetime('now', 'localtime')
        )
        ON CONFLICT(asset_code) DO UPDATE SET
            {', '.join(
                f'{name} = excluded.{name}' for name in update_columns
            )},
            updated_at = datetime('now', 'localtime')
        """
        self._execute_update(sql, tuple(values))

    def has_market_row(self, asset_code: str, trade_date: str) -> bool:
        sql = """
        SELECT 1
        FROM dat_market_daily
        WHERE asset_code = ?
          AND trade_date = ?
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            return conn.execute(sql, (asset_code, trade_date)).fetchone() is not None

    def tickflow_catalog_has_asset(self, asset_code: str) -> bool:
        sql = """
        SELECT 1
        FROM dat_external_asset_catalog
        WHERE source_id = 'tickflow'
          AND asset_code = ?
          AND is_active = 1
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            return conn.execute(sql, (asset_code,)).fetchone() is not None

    def get_tickflow_catalog_status(self, asset_code: str) -> str:
        sql = """
        SELECT is_active
        FROM dat_external_asset_catalog
        WHERE source_id = 'tickflow'
          AND asset_code = ?
        ORDER BY is_active DESC
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            row = conn.execute(sql, (asset_code,)).fetchone()
        if row is None:
            return "absent"
        return "active" if int(row[0] or 0) == 1 else "inactive"

    def get_tickflow_catalog_version(self) -> str:
        sql = """
        SELECT COALESCE(MAX(last_synced_at), '')
        FROM dat_external_asset_catalog
        WHERE source_id = 'tickflow'
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            row = conn.execute(sql).fetchone()
        return str(row[0] or "") if row else ""

    def get_market_dates(self, asset_code: str) -> set[str]:
        with self.db_engine.get_connection(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT trade_date
                FROM dat_market_daily
                WHERE asset_code = ?
                """,
                (asset_code,),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def get_market_date_bounds_by_asset(self) -> dict[str, dict]:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    asset_code,
                    MIN(trade_date) AS first_trade_date,
                    MAX(trade_date) AS last_trade_date
                FROM dat_market_daily
                GROUP BY asset_code
                """
            )
            rows = self._rows_to_dicts(cursor, cursor.fetchall())
        return {row["asset_code"]: row for row in rows}

    def list_tasks_for_asset(
        self,
        asset_code: str,
        include_filled: bool = False,
    ) -> list[dict]:
        status_filter = "" if include_filled else "AND status != 'FILLED'"
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT *
                FROM dat_market_gap_fill_task
                WHERE asset_code = ?
                  {status_filter}
                ORDER BY missing_date, task_id
                """,
                (asset_code,),
            )
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def get_task(self, task_id: int) -> dict:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM dat_market_gap_fill_task
                WHERE task_id = ?
                """,
                (task_id,),
            )
            return self._row_to_dict(cursor, cursor.fetchone())

    def get_governance_counts(self) -> dict:
        with self.db_engine.get_connection(readonly=True) as conn:
            task_rows = conn.execute(
                """
                SELECT status, COUNT(*)
                FROM dat_market_gap_fill_task
                GROUP BY status
                """
            ).fetchall()
            discovery_rows = conn.execute(
                """
                SELECT tickflow_discovery_status, COUNT(*)
                FROM dat_market_gap_fill_asset_state
                GROUP BY tickflow_discovery_status
                """
            ).fetchall()
        return {
            "tasks": {str(row[0]): int(row[1]) for row in task_rows},
            "tickflow_assets": {
                str(row[0]): int(row[1]) for row in discovery_rows
            },
        }

    def find_affected_accounts_by_asset_dates(
        self,
        min_filled_date_by_code: dict[str, str],
    ) -> list[dict]:
        if not min_filled_date_by_code:
            return []

        asset_codes = sorted(min_filled_date_by_code)
        placeholders = self._build_placeholders(asset_codes)
        sql = f"""
        WITH affected AS (
            SELECT
                account_id,
                asset_code,
                MIN(substr(trade_time, 1, 10)) AS fact_date
            FROM trade_order
            WHERE status = 1
              AND asset_code IN ({placeholders})
            GROUP BY account_id, asset_code
            UNION ALL
            SELECT
                account_id,
                asset_code,
                MIN(effective_date) AS fact_date
            FROM account_corporate_action
            WHERE status IN ('CONFIRMED', 'APPLIED', 'ACTIVE')
              AND asset_code IN ({placeholders})
            GROUP BY account_id, asset_code
        )
        SELECT account_id, asset_code, MIN(fact_date) AS fact_date
        FROM affected
        GROUP BY account_id, asset_code
        ORDER BY account_id, asset_code
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (*asset_codes, *asset_codes))
            rows = self._rows_to_dicts(cursor, cursor.fetchall())

        result = []
        for row in rows:
            asset_code = row["asset_code"]
            filled_date = min_filled_date_by_code.get(asset_code)
            fact_date = row.get("fact_date")
            if not filled_date or not fact_date:
                continue
            result.append(
                {
                    "account_id": row["account_id"],
                    "asset_code": asset_code,
                    "from_date": max(fact_date, filled_date),
                }
            )
        return result
