from __future__ import annotations

from config.constants import AssetType
from core.data_quality.models import EntityType
from core.data_quality.models import IssueGroup
from core.data_quality.models import IssueSeverity
from core.data_quality.rules.common import is_missing
from core.data_quality.rules.common import issue
from core.data_quality.rules.common import market_entity_id


def scan(
    rows: list[dict],
    scan_batch_id: str,
    detected_at: str,
) -> list:
    issues = []
    for row in rows:
        volume = _number(row.get("volume"))
        amount = _number(row.get("amount"))

        if volume is not None and volume < 0:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.MARKET_ROW,
                    market_entity_id(row),
                    "VOLUME_NEGATIVE",
                    IssueSeverity.ERROR,
                    IssueGroup.VOLUME_AMOUNT,
                    "volume",
                    row.get("volume"),
                    ">= 0",
                    {"volume": row.get("volume")},
                    asset_code=row.get("asset_code"),
                    trade_date=row.get("trade_date"),
                    source_id=row.get("source_id"),
                )
            )

        if amount is not None and amount < 0:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.MARKET_ROW,
                    market_entity_id(row),
                    "AMOUNT_NEGATIVE",
                    IssueSeverity.ERROR,
                    IssueGroup.VOLUME_AMOUNT,
                    "amount",
                    row.get("amount"),
                    ">= 0",
                    {"amount": row.get("amount")},
                    asset_code=row.get("asset_code"),
                    trade_date=row.get("trade_date"),
                    source_id=row.get("source_id"),
                )
            )

        conflict_type = _volume_amount_conflict_type(row, volume, amount)
        if conflict_type:
            issues.append(
                issue(
                    scan_batch_id,
                    detected_at,
                    EntityType.MARKET_ROW,
                    market_entity_id(row),
                    "VOLUME_AMOUNT_CONFLICT",
                    IssueSeverity.WARN,
                    IssueGroup.VOLUME_AMOUNT,
                    "volume_amount",
                    f"volume={row.get('volume')}, amount={row.get('amount')}",
                    "volume and amount should be directionally consistent",
                    {
                        "volume": row.get("volume"),
                        "amount": row.get("amount"),
                        "asset_type": row.get("asset_type"),
                        "conflict_type": conflict_type,
                    },
                    asset_code=row.get("asset_code"),
                    trade_date=row.get("trade_date"),
                    source_id=row.get("source_id"),
                )
            )
    return issues


def _volume_amount_conflict_type(row: dict, volume, amount) -> str | None:
    if str(row.get("asset_type") or "").strip() == AssetType.INDEX:
        return None
    if volume is None or amount is None:
        return None
    if volume == 0 and amount > 0:
        return "zero_volume_nonzero_amount"
    if volume > 0 and amount == 0:
        return "nonzero_volume_zero_amount"
    return None


def _number(value):
    if is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
