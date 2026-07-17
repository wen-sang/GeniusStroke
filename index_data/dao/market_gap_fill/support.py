# 文件: dao/market_gap_fill/support.py
"""缺口治理共享支撑：issue 状态同步 Mixin 与 JSON / 时间 / SQL / 校验辅助函数。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import json

from utils.validators import ValidationError


class GapIssueSyncMixin:
    @staticmethod
    def _update_gap_issue_status_with_cursor(
        cursor,
        asset_code: str,
        trade_date: str,
        issue_status: str,
    ) -> None:
        cursor.execute(
            """
            UPDATE dat_data_quality_issue
            SET issue_status = ?
            WHERE asset_code = ?
              AND trade_date = ?
              AND rule_code = 'MISSING_TRADING_DAY_BAR'
            """,
            (issue_status, asset_code, trade_date),
        )
        cursor.execute(
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
            WHERE scan_batch_id IN (
                SELECT DISTINCT scan_batch_id
                FROM dat_data_quality_issue
                WHERE asset_code = ?
                  AND trade_date = ?
                  AND rule_code = 'MISSING_TRADING_DAY_BAR'
            )
            """,
            (asset_code, trade_date),
        )

def _json(detail: dict[str, Any] | None) -> str:
    return json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)


def _merge_detail_json(
    existing_json: str | None,
    updates: dict[str, Any] | None,
) -> str:
    try:
        detail = json.loads(existing_json or "{}")
    except (TypeError, json.JSONDecodeError):
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    update_values = dict(updates or {})
    incoming_sources = update_values.pop("source_results", None)
    if isinstance(incoming_sources, dict):
        existing_sources = detail.get("source_results")
        if not isinstance(existing_sources, dict):
            existing_sources = {}
        existing_sources.update(incoming_sources)
        detail["source_results"] = existing_sources
    detail.update(update_values)
    return _json(detail)


def _merge_source_result_json(
    existing_json: str | None,
    source_id: str,
    source_result: dict[str, Any],
) -> str:
    try:
        detail = json.loads(existing_json or "{}")
    except (TypeError, json.JSONDecodeError):
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    source_results = detail.get("source_results")
    if not isinstance(source_results, dict):
        source_results = {}
    source_results[source_id] = source_result
    detail["source_results"] = source_results
    return _json(detail)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _add_minutes(now_text: str, minutes: int) -> str:
    dt = datetime.strptime(now_text, "%Y-%m-%d %H:%M:%S")
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _due_condition_sql() -> str:
    return """
    (
        (
            status = 'PENDING'
            AND (next_retry_at IS NULL OR next_retry_at <= ?)
        )
        OR (
            status = 'FAILED'
            AND attempt_count < max_attempts
            AND (next_retry_at IS NULL OR next_retry_at <= ?)
        )
        OR (
            status = 'RUNNING'
            AND claim_expires_at IS NOT NULL
            AND claim_expires_at <= ?
        )
    )
    """


def select_complete_asset_groups(
    groups: list[dict],
    batch_size: int,
    max_tasks: int,
) -> list[dict]:
    selected = []
    selected_count = 0
    soft_limit = min(batch_size, max_tasks)
    for group in groups:
        task_count = int(group.get("task_count") or 0)
        if task_count <= 0:
            continue
        if selected and selected_count + task_count > soft_limit:
            break
        selected.append(group)
        selected_count += task_count
        if selected_count >= soft_limit:
            break
    return selected


def _validate_market_row(row: dict) -> None:
    required = (
        "asset_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source_id",
        "updated_at",
    )
    if any(row.get(column) is None for column in required):
        raise ValidationError("Incomplete market row")
    open_price = float(row["open"])
    high_price = float(row["high"])
    low_price = float(row["low"])
    close_price = float(row["close"])
    if min(open_price, high_price, low_price, close_price) <= 0:
        raise ValidationError("Market OHLC prices must be positive")
    if high_price < max(open_price, low_price, close_price):
        raise ValidationError("Market high price is invalid")
    if low_price > min(open_price, close_price):
        raise ValidationError("Market low price is invalid")
    if float(row["volume"]) < 0 or float(row["amount"]) < 0:
        raise ValidationError("Market volume/amount must be non-negative")
