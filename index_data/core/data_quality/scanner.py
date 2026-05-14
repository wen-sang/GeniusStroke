from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.data_quality.models import DataQualityIssue
from core.data_quality.models import DataQualityScanResult
from core.data_quality.models import SCAN_SCOPE_FULL
from core.data_quality.models import SOURCE_TABLE_MARKET_DAILY
from core.data_quality.models import TRIGGER_MANUAL
from core.data_quality.report import DataQualityReportWriter
from core.data_quality.rules import calendar_rules
from core.data_quality.rules import meta_rules
from core.data_quality.rules import ohlc_rules
from core.data_quality.rules import volume_amount_rules
from dao.data_quality_dao import data_quality_dao
from utils.logger import logger


class DataQualityScanner:
    def __init__(self, dao=None, report_writer=None):
        self.dao = dao or data_quality_dao
        self.report_writer = report_writer or DataQualityReportWriter()

    def scan_market_daily(
        self,
        report_dir: str | Path | None = None,
        scan_batch_id: str | None = None,
    ) -> dict:
        scan_batch_id = scan_batch_id or self._generate_batch_id()
        started_at = _now_text()
        scanned_rows = 0
        batch_created = False

        try:
            self.dao.create_running_batch(scan_batch_id, started_at)
            batch_created = True

            rows = self.dao.fetch_market_daily_rows()
            calendar_rows = self.dao.fetch_exchange_calendar_rows()
            scanned_rows = len(rows)
            detected_at = _now_text()
            issues = self._run_rules(
                rows=rows,
                calendar_rows=calendar_rows,
                scan_batch_id=scan_batch_id,
                detected_at=detected_at,
            )
            issues = self._dedupe_issues(issues)

            report_path = self.report_writer.write_market_daily_report(
                scan_batch_id=scan_batch_id,
                started_at=started_at,
                scanned_rows=scanned_rows,
                issues=issues,
                report_dir=report_dir,
            )
            finished_at = _now_text()
            issue_count = self.dao.complete_success_batch(
                scan_batch_id=scan_batch_id,
                issues=issues,
                scanned_rows=scanned_rows,
                report_path=report_path,
                finished_at=finished_at,
            )
        except Exception as error:
            if batch_created:
                self._mark_failed(scan_batch_id, scanned_rows, error)
            raise

        logger.info(
            "[DATA_QUALITY] market daily scan finished batch=%s rows=%s "
            "issues=%s report=%s",
            scan_batch_id,
            scanned_rows,
            issue_count,
            report_path,
        )
        result = DataQualityScanResult(
            status="ok",
            scan_batch_id=scan_batch_id,
            source_table=SOURCE_TABLE_MARKET_DAILY,
            trigger_type=TRIGGER_MANUAL,
            scan_scope=SCAN_SCOPE_FULL,
            scanned_rows=scanned_rows,
            issue_count=issue_count,
            report_path=report_path,
        )
        return result.to_dict()

    def _run_rules(
        self,
        rows: list[dict],
        calendar_rows: list[dict],
        scan_batch_id: str,
        detected_at: str,
    ) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        issues.extend(meta_rules.scan(rows, scan_batch_id, detected_at))
        issues.extend(
            calendar_rules.scan(
                rows,
                calendar_rows,
                scan_batch_id,
                detected_at,
            )
        )
        issues.extend(ohlc_rules.scan(rows, scan_batch_id, detected_at))
        issues.extend(volume_amount_rules.scan(rows, scan_batch_id, detected_at))
        return issues

    def _dedupe_issues(
        self,
        issues: list[DataQualityIssue],
    ) -> list[DataQualityIssue]:
        seen = set()
        result = []
        for issue in issues:
            key = (
                issue.scan_batch_id,
                issue.source_table,
                issue.entity_type,
                issue.entity_id or "",
                issue.asset_code or "",
                issue.trade_date or "",
                issue.rule_code,
                issue.field_name or "",
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(issue)
        return result

    def _mark_failed(
        self,
        scan_batch_id: str,
        scanned_rows: int,
        error: Exception,
    ) -> None:
        try:
            self.dao.mark_batch_failed(
                scan_batch_id=scan_batch_id,
                scanned_rows=scanned_rows,
                error_message=str(error),
                finished_at=_now_text(),
            )
        except Exception as failed_error:
            logger.error(
                "[DATA_QUALITY] failed to mark batch=%s FAILED: %s",
                scan_batch_id,
                failed_error,
            )

    @staticmethod
    def _generate_batch_id() -> str:
        return "dq_market_daily_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


data_quality_scanner = DataQualityScanner()
