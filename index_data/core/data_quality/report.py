from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from config import settings
from core.data_quality.models import DataQualityIssue
from core.data_quality.models import SOURCE_NO_SOURCE


ISSUE_COLUMNS = [
    "scan_batch_id",
    "asset_code",
    "trade_date",
    "source_id",
    "entity_type",
    "entity_id",
    "rule_code",
    "severity",
    "issue_group",
    "field_name",
    "actual_value",
    "expected_value",
    "detail_json",
    "issue_status",
    "detected_at",
]

ISSUE_COLUMN_LABELS = {
    "scan_batch_id": "扫描批次",
    "asset_code": "资产代码",
    "trade_date": "交易日期",
    "source_id": "数据源",
    "entity_type": "主体类型",
    "entity_id": "主体ID",
    "rule_code": "规则编码",
    "severity": "严重级别",
    "issue_group": "问题分组",
    "field_name": "字段名",
    "actual_value": "实际值",
    "expected_value": "期望值",
    "detail_json": "规则细节JSON",
    "issue_status": "问题状态",
    "detected_at": "检出时间",
}

SUMMARY_LABELS = {
    "scan_batch_id": "扫描批次",
    "source_table": "来源表",
    "trigger_type": "触发方式",
    "scan_scope": "扫描范围",
    "started_at": "开始时间",
    "scanned_rows": "扫描行数",
    "issue_count": "问题数量",
    "report_path": "报告路径",
}

SUMMARY_VALUE_LABELS = {
    "dat_market_daily": "行情日线表(dat_market_daily)",
    "MANUAL": "手动",
    "FULL": "全量",
}

RULE_CODE_LABELS = {
    "ASSET_META_MISSING": "资产元数据缺失",
    "ASSET_EXCHANGE_MISSING": "资产交易所缺失",
    "ASSET_EXCHANGE_INVALID": "资产交易所非法",
    "LISTING_DATE_INVALID": "上市日期无效",
    "BAR_BEFORE_LISTING_DATE": "上市日前存在行情",
    "CALENDAR_RECORD_MISSING": "交易日历记录缺失",
    "CALENDAR_COVERAGE_INSUFFICIENT": "交易日历覆盖不足",
    "CALENDAR_INVALID_IS_OPEN": "日历开市标记非法",
    "NON_TRADING_DAY_BAR": "非交易日存在行情",
    "MISSING_TRADING_DAY_BAR": "交易日无行情数据",
    "KEY_FIELD_MISSING": "关键字段缺失",
    "DATE_FORMAT_INVALID": "日期格式无效",
    "PRICE_NON_POSITIVE": "价格非正",
    "HIGH_LOW_INVALID": "最高最低价关系非法",
    "OHLC_RANGE_INVALID": "开收盘价超出高低价范围",
    "ONLY_CLOSE_AVAILABLE": "仅收盘价可用",
    "VOLUME_NEGATIVE": "成交量为负",
    "AMOUNT_NEGATIVE": "成交额为负",
    "VOLUME_AMOUNT_CONFLICT": "成交量成交额冲突",
}


class DataQualityReportWriter:
    def write_market_daily_report(
        self,
        scan_batch_id: str,
        started_at: str,
        scanned_rows: int,
        issues: list[DataQualityIssue],
        report_dir: str | Path | None = None,
    ) -> str:
        target_dir = Path(report_dir) if report_dir else default_report_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        report_path = target_dir / (
            f"data_quality_market_daily_{scan_batch_id}.xlsx"
        )

        issue_rows = [issue.to_report_dict() for issue in issues]
        issues_df = _build_issues_df(issue_rows)
        summary = _build_summary_rows(
            scan_batch_id=scan_batch_id,
            started_at=started_at,
            scanned_rows=scanned_rows,
            issue_count=len(issues),
            report_path=str(report_path),
        )

        with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
            pd.DataFrame(summary).to_excel(
                writer,
                index=False,
                sheet_name="summary",
            )
            _counter_df(
                "规则编码",
                Counter(
                    RULE_CODE_LABELS.get(issue.rule_code, issue.rule_code)
                    for issue in issues
                ),
            ).to_excel(writer, index=False, sheet_name="by_rule")
            _counter_df(
                "严重级别",
                Counter(issue.severity for issue in issues),
            ).to_excel(writer, index=False, sheet_name="by_severity")
            _counter_df(
                "问题分组",
                Counter(issue.issue_group for issue in issues),
            ).to_excel(writer, index=False, sheet_name="by_group")
            _counter_df(
                "资产代码",
                Counter(
                    issue.asset_code or ""
                    for issue in issues
                    if issue.asset_code
                ),
            ).to_excel(writer, index=False, sheet_name="by_asset")
            _counter_df(
                "数据源",
                Counter(
                    issue.source_id or SOURCE_NO_SOURCE
                    for issue in issues
                ),
            ).to_excel(writer, index=False, sheet_name="by_source")
            issues_df.to_excel(writer, index=False, sheet_name="issues")

        return str(report_path)


def default_report_dir() -> Path:
    return Path(settings.PROJECT_ROOT) / "reports" / "data_quality"


def _build_issues_df(issue_rows: list[dict]) -> pd.DataFrame:
    issues_df = pd.DataFrame(issue_rows, columns=ISSUE_COLUMNS)
    if not issues_df.empty:
        issues_df["rule_code"] = issues_df["rule_code"].map(
            lambda value: RULE_CODE_LABELS.get(value, value),
        )
    return issues_df.rename(columns=ISSUE_COLUMN_LABELS)


def _counter_df(column_name: str, counter: Counter) -> pd.DataFrame:
    rows = [
        {column_name: key, "问题数量": count}
        for key, count in sorted(counter.items(), key=lambda item: str(item[0]))
    ]
    return pd.DataFrame(rows, columns=[column_name, "问题数量"])


def _build_summary_rows(
    scan_batch_id: str,
    started_at: str,
    scanned_rows: int,
    issue_count: int,
    report_path: str,
) -> list[dict[str, Any]]:
    raw_rows = [
        {"key": "scan_batch_id", "value": scan_batch_id},
        {"key": "source_table", "value": "dat_market_daily"},
        {"key": "trigger_type", "value": "MANUAL"},
        {"key": "scan_scope", "value": "FULL"},
        {"key": "started_at", "value": started_at},
        {"key": "scanned_rows", "value": scanned_rows},
        {"key": "issue_count", "value": issue_count},
        {"key": "report_path", "value": report_path},
    ]
    return [
        {
            "项目": SUMMARY_LABELS.get(row["key"], row["key"]),
            "值": SUMMARY_VALUE_LABELS.get(row["value"], row["value"]),
        }
        for row in raw_rows
    ]
