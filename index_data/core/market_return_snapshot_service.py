from typing import Dict, List, Optional

from dao.market_return_snapshot_dao import (
    MARKET_RETURN_WINDOWS,
    market_return_snapshot_dao,
)
from utils.logger import logger


class MarketReturnSnapshotService:
    """按交易日生成行情区间涨幅快照。"""

    def rebuild_for_trade_date(self, trade_date: str) -> dict:
        market_rows = market_return_snapshot_dao.fetch_market_rows_by_date(trade_date)
        if not market_rows:
            logger.warning(
                "[MARKET_RETURN_SNAPSHOT] no market rows for trade_date=%s",
                trade_date,
            )
            return self._build_summary(trade_date, [], 0)

        asset_codes = [row["asset_code"] for row in market_rows]
        close_windows = market_return_snapshot_dao.fetch_recent_close_windows(
            asset_codes=asset_codes,
            trade_date=trade_date,
            max_window=max(MARKET_RETURN_WINDOWS.values()),
        )
        snapshot_rows = [
            self._build_snapshot_row(row, close_windows.get(row["asset_code"], []))
            for row in market_rows
        ]
        upserted = market_return_snapshot_dao.upsert_snapshots(snapshot_rows)
        return self._build_summary(trade_date, snapshot_rows, upserted)

    @staticmethod
    def _build_snapshot_row(row: dict, closes: List[Optional[float]]) -> dict:
        snapshot = {
            "asset_code": row["asset_code"],
            "trade_date": row["trade_date"],
        }
        for field, window in MARKET_RETURN_WINDOWS.items():
            snapshot[field] = MarketReturnSnapshotService._calculate_window_return(
                closes,
                window,
            )
        return snapshot

    @staticmethod
    def _calculate_window_return(
        closes: List[Optional[float]],
        window: int,
    ) -> Optional[float]:
        if len(closes) < window:
            return None
        latest_close = closes[0]
        base_close = closes[window - 1]
        if latest_close is None or base_close is None or base_close <= 0:
            return None
        return latest_close / base_close - 1

    @staticmethod
    def _build_summary(trade_date: str, rows: List[dict], upserted: int) -> Dict[str, object]:
        null_counts = {
            field: sum(1 for row in rows if row.get(field) is None)
            for field in MARKET_RETURN_WINDOWS
        }
        return {
            "trade_date": trade_date,
            "total": len(rows),
            "upserted": upserted,
            "null_counts": null_counts,
        }


market_return_snapshot_service = MarketReturnSnapshotService()
