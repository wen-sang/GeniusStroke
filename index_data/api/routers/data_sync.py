from typing import Optional

from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse

from api.error_helpers import raise_client_http_error, raise_internal_http_error
from api.services.data_sync_service import DataSyncAlreadyRunningError, data_sync_service

router = APIRouter(
    prefix="/api/data-sync",
    tags=["数据更新前台化"],
)


@router.post("/trigger")
async def trigger_data_sync(payload: Optional[dict] = Body(default=None)):
    # Accept an optional body for the frontend retry contract; sync flow stays unchanged.
    try:
        return data_sync_service.trigger_sync()
    except DataSyncAlreadyRunningError as exc:
        raise_client_http_error(
            "启动数据更新任务冲突 detail=%s",
            str(exc),
            str(exc),
            status_code=409,
        )
    except Exception:
        raise_internal_http_error("启动数据更新任务失败", "服务内部错误")


@router.get("/status")
async def get_data_sync_status():
    try:
        return data_sync_service.get_status()
    except Exception:
        raise_internal_http_error("读取数据更新状态失败", "服务内部错误")


@router.get("/logs")
async def stream_data_sync_logs(
    limit: int = Query(200, ge=1, le=2000, description="初次连接回放最近日志条数"),
    after_seq: int = Query(0, ge=0, description="仅推送大于该序号的后续事件"),
):
    try:
        stream = data_sync_service.iter_logs(limit=limit, after_seq=after_seq)
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        raise_internal_http_error("读取数据更新日志流失败", "服务内部错误")
