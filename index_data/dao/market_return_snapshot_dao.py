from datetime import datetime
from typing import Dict, List, Optional

from dao.base_dao import BaseDAO


MARKET_RETURN_WINDOWS = {
    "return_22d": 22,
    "return_60d": 60,
    "return_6m": 120,
    "return_1y": 250,
}


class MarketReturnSnapshotDAO(BaseDAO):
    """行情区间涨幅快照 DAO。"""

    @property
    def table_name(self) -> str:
        return "dat_market_return_snapshot"

    def fetch_market_rows_by_date(self, trade_date: str) -> List[dict]:
        sql = """
        SELECT
            asset_code,
            trade_date,
            close
        FROM dat_market_daily
        WHERE trade_date = ?
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (trade_date,))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def fetch_recent_close_windows(
        self,
        asset_codes: List[str],
        trade_date: str,
        max_window: int,
    ) -> Dict[str, List[Optional[float]]]:
        if not asset_codes:
            return {}

        placeholders = self._build_placeholders(asset_codes)
        sql = f"""
        SELECT asset_code, close
        FROM (
            SELECT
                asset_code,
                close,
                ROW_NUMBER() OVER (
                    PARTITION BY asset_code
                    ORDER BY trade_date DESC
                ) AS rn
            FROM dat_market_daily
            WHERE asset_code IN ({placeholders})
              AND trade_date <= ?
        )
        WHERE rn <= ?
        ORDER BY asset_code, rn
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (*asset_codes, trade_date, max_window))
            close_windows: Dict[str, List[Optional[float]]] = {}
            for asset_code, close in cursor.fetchall():
                close_windows.setdefault(asset_code, []).append(
                    float(close) if close is not None else None
                )
            return close_windows

    def upsert_snapshots(self, rows: List[dict]) -> int:
        if not rows:
            return 0

        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = [
            (
                row["asset_code"],
                row["trade_date"],
                row.get("return_22d"),
                row.get("return_60d"),
                row.get("return_6m"),
                row.get("return_1y"),
                updated_at,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO dat_market_return_snapshot (
            asset_code,
            trade_date,
            return_22d,
            return_60d,
            return_6m,
            return_1y,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_code, trade_date) DO UPDATE SET
            return_22d = excluded.return_22d,
            return_60d = excluded.return_60d,
            return_6m = excluded.return_6m,
            return_1y = excluded.return_1y,
            updated_at = excluded.updated_at
        """
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, data)
            return cursor.rowcount

    def count_by_date(self, trade_date: str) -> int:
        sql = "SELECT COUNT(*) FROM dat_market_return_snapshot WHERE trade_date = ?"
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (trade_date,))
            row = cursor.fetchone()
            return int(row[0]) if row else 0


market_return_snapshot_dao = MarketReturnSnapshotDAO()
