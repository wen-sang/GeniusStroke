from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from config.constants import Exchange
from core.data_quality.models import DataQualityIssue
from core.data_quality.models import SOURCE_MULTIPLE
from core.data_quality.models import SOURCE_NO_SOURCE


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def date_parse_error(value: Any) -> str | None:
    if is_missing(value):
        return None
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        return "format_mismatch"
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return "invalid_date"
    if parsed.strftime("%Y-%m-%d") != value:
        return "invalid_date"
    return None


def is_valid_date(value: Any) -> bool:
    return not is_missing(value) and date_parse_error(value) is None


def source_distribution(rows: list[dict]) -> dict[str, int]:
    counter = Counter(_source_key(row.get("source_id")) for row in rows)
    return dict(sorted(counter.items(), key=lambda item: item[0]))


def resolve_source_id(rows: list[dict]) -> str | None:
    distribution = source_distribution(rows)
    if not distribution:
        return None
    if len(distribution) == 1:
        source_id = next(iter(distribution))
        return None if source_id == SOURCE_NO_SOURCE else source_id
    return SOURCE_MULTIPLE


def market_entity_id(row: dict) -> str:
    asset_code = row.get("asset_code")
    trade_date = row.get("trade_date")
    if not is_missing(asset_code) and not is_missing(trade_date):
        return f"{asset_code}|{trade_date}"
    return f"rowid:{row.get('market_row_id')}"


def issue(
    scan_batch_id: str,
    detected_at: str,
    entity_type: str,
    entity_id: str,
    rule_code: str,
    severity: str,
    issue_group: str,
    field_name: str | None,
    actual_value: Any,
    expected_value: Any,
    detail_json: dict[str, Any],
    asset_code: str | None = None,
    trade_date: str | None = None,
    source_id: str | None = None,
) -> DataQualityIssue:
    return DataQualityIssue(
        scan_batch_id=scan_batch_id,
        entity_type=entity_type,
        entity_id=entity_id,
        rule_code=rule_code,
        severity=severity,
        issue_group=issue_group,
        field_name=field_name,
        actual_value=actual_value,
        expected_value=expected_value,
        detail_json=detail_json or {},
        detected_at=detected_at,
        asset_code=asset_code,
        trade_date=trade_date,
        source_id=source_id,
    )


def affected_detail(rows: list[dict]) -> dict[str, Any]:
    dates = [
        row.get("trade_date")
        for row in rows
        if not is_missing(row.get("trade_date"))
    ]
    return {
        "affected_rows": len(rows),
        "min_trade_date": min(dates) if dates else None,
        "max_trade_date": max(dates) if dates else None,
        "source_distribution": source_distribution(rows),
    }


def valid_exchange(value: Any) -> bool:
    return not is_missing(value) and str(value).strip() in Exchange.VALID


def _source_key(source_id: Any) -> str:
    if is_missing(source_id):
        return SOURCE_NO_SOURCE
    return str(source_id)
