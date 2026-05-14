from __future__ import annotations

from typing import Dict


class TradeMutationRebuildOrchestrator:
    """交易或资金事实写入后的重算编排。"""

    def __init__(self, current_rebuild_service, history_rebuild_service) -> None:
        self.current_rebuild_service = current_rebuild_service
        self.history_rebuild_service = history_rebuild_service

    def refresh_after_mutation(
        self,
        account_id: int,
        from_date: str,
        live_snapshot_date: str,
        conn,
    ) -> Dict:
        current_summary = self.current_rebuild_service.rebuild_current_state(
            account_id=account_id,
            conn=conn,
        )
        history_result = self.history_rebuild_service.try_rebuild_history(
            account_id=account_id,
            from_date=from_date,
            conn=conn,
        )
        live_snapshot_result = self.history_rebuild_service.sync_live_snapshot(
            account_id=account_id,
            biz_date=live_snapshot_date,
            conn=conn,
        )
        return {
            "current_summary": current_summary,
            "history_result": history_result,
            "live_snapshot_result": live_snapshot_result,
        }
