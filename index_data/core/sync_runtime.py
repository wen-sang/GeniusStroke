from __future__ import annotations

import json
import threading
import time
from collections import deque
from copy import deepcopy
from typing import Any, Callable, Optional

from core.sync_models import (
    TOTAL_SYNC_STEPS,
    SyncCallbacks,
    SyncErrorInfo,
    SyncResult,
    SyncTaskStatus,
    build_task_id,
    format_timestamp,
)
from core.sync_runner import sync_runner
from utils.logger import capture_runtime_logs


class TaskLogBuffer:
    def __init__(self, maxlen: int = 1000):
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._condition = threading.Condition()
        self._seq = 0

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            self._seq += 1
            item = dict(event)
            item["seq"] = self._seq
            self._events.append(item)
            self._condition.notify_all()
            return dict(item)

    def get_recent(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        with self._condition:
            items = list(self._events)
        if limit is None or limit >= len(items):
            return [dict(item) for item in items]
        return [dict(item) for item in items[-limit:]]

    def wait_for_newer_than(
        self,
        after_seq: int = 0,
        timeout: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        with self._condition:
            if not any(item["seq"] > after_seq for item in self._events):
                self._condition.wait(timeout=timeout)
            items = [dict(item) for item in self._events if item["seq"] > after_seq]
        return items

    def clear(self) -> None:
        with self._condition:
            self._events.clear()
            self._seq = 0


class SyncRuntimeManager:
    def __init__(
        self,
        runner=None,
        log_buffer_size: int = 1000,
    ) -> None:
        self._runner = runner or sync_runner
        self._lock = threading.Lock()
        self._last_result: Optional[dict[str, Any]] = None
        self._log_buffer = TaskLogBuffer(maxlen=log_buffer_size)
        self._thread: Optional[threading.Thread] = None
        self._started_epoch: Optional[float] = None
        self._status: dict[str, Any] = self._build_idle_status()

    def start_background(
        self,
        execute_fn: Optional[Callable[[str, SyncCallbacks], SyncResult]] = None,
        task_id: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        with self._lock:
            if self._status["running"]:
                return False, self._status["task_id"]

            resolved_task_id = task_id or build_task_id()
            self._status = {
                "running": True,
                "task_id": resolved_task_id,
                "current_step": 0,
                "total_steps": TOTAL_SYNC_STEPS,
                "step_name": None,
                "step_status": None,
                "progress": None,
                "sub_progress": None,
                "detail": None,
                "elapsed_seconds": 0.0,
                "started_at": format_timestamp(),
                "last_result": self._last_result,
            }
            self._started_epoch = time.time()
            self._log_buffer.clear()

            target = execute_fn or self._execute_runner
            self._thread = threading.Thread(
                target=self._run_in_thread,
                args=(resolved_task_id, target),
                daemon=True,
                name=f"sync-runtime-{resolved_task_id}",
            )
            self._thread.start()
            return True, resolved_task_id

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = deepcopy(self._status)
            snapshot["last_result"] = deepcopy(self._last_result)
            started_epoch = self._started_epoch
        if snapshot["running"] and started_epoch is not None:
            snapshot["elapsed_seconds"] = round(time.time() - started_epoch, 2)
        return snapshot

    def get_recent_logs(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        return self._log_buffer.get_recent(limit=limit)

    def wait_for_logs(self, after_seq: int = 0, timeout: Optional[float] = None) -> list[dict[str, Any]]:
        return self._log_buffer.wait_for_newer_than(after_seq=after_seq, timeout=timeout)

    def iter_sse_messages(
        self,
        limit: int = 200,
        after_seq: int = 0,
        poll_timeout: float = 1.0,
        idle_heartbeat_seconds: float = 15.0,
    ):
        recent_events = self.get_recent_logs(limit=limit)
        last_seq = after_seq
        for event in recent_events:
            if event["seq"] <= after_seq:
                continue
            last_seq = event["seq"]
            yield self._format_sse_message(event)

        idle_started = time.time()
        while True:
            new_events = self.wait_for_logs(after_seq=last_seq, timeout=poll_timeout)
            if new_events:
                idle_started = time.time()
                for event in new_events:
                    last_seq = event["seq"]
                    yield self._format_sse_message(event)
                continue

            yield ": keepalive\n\n"
            if not self.get_status()["running"] and self._last_result is not None:
                break
            if time.time() - idle_started >= idle_heartbeat_seconds:
                idle_started = time.time()

    def _execute_runner(self, task_id: str, callbacks: SyncCallbacks) -> SyncResult:
        return self._runner.run(task_id=task_id, callbacks=callbacks)

    def _run_in_thread(
        self,
        task_id: str,
        execute_fn: Callable[[str, SyncCallbacks], SyncResult],
    ) -> None:
        callbacks = self._build_callbacks()

        def sink(event: dict[str, Any]) -> None:
            event["task_id"] = task_id
            self._log_buffer.append(event)

        with capture_runtime_logs(sink):
            try:
                result = execute_fn(task_id, callbacks)
            except Exception as exc:
                result = SyncResult(
                    task_id=task_id,
                    status=SyncTaskStatus.FAILED,
                    started_at=self._status.get("started_at") or format_timestamp(),
                    finished_at=format_timestamp(),
                    elapsed_seconds=round(time.time() - (self._started_epoch or time.time()), 2),
                    current_step=self._status.get("current_step", 0),
                    total_steps=TOTAL_SYNC_STEPS,
                    failed_step=self._status.get("current_step", 0) or None,
                    summary={},
                    error=SyncErrorInfo(
                        type=type(exc).__name__,
                        message=str(exc),
                        recoverable=False,
                    ),
                )
            self._append_result_event(result)

        with self._lock:
            self._last_result = result.to_dict()
            self._status = self._build_idle_status()
            self._status["last_result"] = deepcopy(self._last_result)
            self._started_epoch = None

    def _build_callbacks(self) -> SyncCallbacks:
        return SyncCallbacks(
            on_step_change=self._handle_step_change,
            on_progress=self._handle_progress,
        )

    def _handle_step_change(self, step_number: int, step_name: str, status: str) -> None:
        with self._lock:
            self._status["current_step"] = step_number
            self._status["step_name"] = step_name
            self._status["step_status"] = status
            task_id = self._status.get("task_id")
            progress = self._status.get("progress")
            sub_progress = self._status.get("sub_progress")
        self._log_buffer.append(
            {
                "event": "step",
                "task_id": task_id,
                "step": step_number,
                "name": step_name,
                "status": status,
                "progress": progress,
                "sub_progress": sub_progress,
            }
        )

    def _handle_progress(
        self,
        step_number: int,
        progress: Optional[int] = None,
        sub_progress: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._status["current_step"] = step_number
            self._status["progress"] = progress
            self._status["sub_progress"] = sub_progress
            self._status["detail"] = detail
            task_id = self._status.get("task_id")
            step_name = self._status.get("step_name")
            step_status = self._status.get("step_status")
        self._log_buffer.append(
            {
                "event": "progress",
                "task_id": task_id,
                "step": step_number,
                "name": step_name,
                "status": step_status,
                "progress": progress,
                "sub_progress": sub_progress,
                "detail": detail,
            }
        )

    def _build_idle_status(self) -> dict[str, Any]:
        return {
            "running": False,
            "task_id": None,
            "current_step": 0,
            "total_steps": TOTAL_SYNC_STEPS,
            "step_name": None,
            "step_status": None,
            "progress": None,
            "sub_progress": None,
            "detail": None,
            "elapsed_seconds": 0.0,
            "started_at": None,
            "last_result": deepcopy(self._last_result),
        }

    def _append_result_event(self, result: SyncResult) -> None:
        event_name = "done" if result.status != SyncTaskStatus.FAILED else "error"
        self._log_buffer.append(
            {
                "event": event_name,
                "status": result.status.value,
                "success": result.success,
                "task_id": result.task_id,
                "failed_step": result.failed_step,
                "summary": deepcopy(result.summary),
                "error": result.error.to_dict() if result.error else None,
                "elapsed_seconds": result.elapsed_seconds,
                "finished_at": result.finished_at,
            }
        )

    @staticmethod
    def _format_sse_message(event: dict[str, Any]) -> str:
        payload = json.dumps(
            dict(event),
            ensure_ascii=False,
        )
        event_name = event.get("event", "log")
        return f"event: {event_name}\ndata: {payload}\n\n"


sync_runtime = SyncRuntimeManager()
