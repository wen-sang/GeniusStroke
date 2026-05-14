from __future__ import annotations

from typing import Optional

from core.sync_runtime import sync_runtime


class DataSyncAlreadyRunningError(RuntimeError):
    pass


class DataSyncService:
    def trigger_sync(self) -> dict:
        started, task_id = sync_runtime.start_background()
        if not started:
            raise DataSyncAlreadyRunningError("数据更新正在执行中")
        return {
            "success": True,
            "message": "数据更新已启动",
            "task_id": task_id,
        }

    def get_status(self) -> dict:
        return sync_runtime.get_status()

    def iter_logs(
        self,
        limit: int = 200,
        after_seq: int = 0,
    ):
        return sync_runtime.iter_sse_messages(limit=limit, after_seq=after_seq)

    def get_recent_logs(self, limit: Optional[int] = None) -> list[dict]:
        return sync_runtime.get_recent_logs(limit=limit)


data_sync_service = DataSyncService()
