"""
采集后账户资产更新服务

在行情/净值采集与指标计算完成后，按"受影响账户"更新当前资产快照，
并按需尝试增量更新历史资产。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set

from dao.account_history_dao import account_history_dao
from dao.market_dao import market_dao
from dao.meta_dao import meta_dao
from dao.position_dao import position_dao
from utils.logger import logger, write_console_lines

from dao.trade_dao import trade_dao
from .history_rebuild_service import account_history_rebuild_service
from .rebuild_service import account_rebuild_service

# 控制台输出分隔线
_LINE_FULL = "=" * 70
_LINE_HALF = "-" * 70


def _fmt_amount(value: float, show_sign: bool = False) -> str:
    """格式化金额：千分位 + 两位小数，可选符号前缀。"""
    if value is None:
        return "N/A"
    sign = ("+" if value >= 0 else "") if show_sign else ""
    return f"{sign}{value:,.2f}"


def _get_account_name(account_id: int) -> str:
    """查询账户名称，查不到则降级返回 ID 字符串。"""
    try:
        account = trade_dao.get_account(account_id)
        if account and account.get("account_name"):
            return account["account_name"]
    except Exception:
        pass
    return f"账户#{account_id}"


def _get_daily_return(account_id: int, trade_date: str) -> Optional[float]:
    """从历史表中取指定日期的当日盈亏额。"""
    try:
        rows = account_history_dao.get_history(
            account_id, start_date=trade_date, end_date=trade_date
        )
        if rows:
            return rows[0].get("daily_return")
    except Exception:
        pass
    return None


def _fmt_codes_with_names(codes: List[str], max_count: int = 3) -> str:
    """格式化显示代码及其名称，例如: 000001(平安银行), ..."""
    if not codes:
        return ""
    
    display_list = []
    for code in codes[:max_count]:
        try:
            meta = meta_dao.get_asset_meta(code)
            name = meta.get("asset_name", "未知") if meta else "未知"
            display_list.append(f"{code}({name})")
        except Exception:
            display_list.append(code)
            
    suffix = " ..." if len(codes) > max_count else ""
    return ", ".join(display_list) + suffix


def _fmt_missing_quotes(missing_quotes: List[object]) -> str:
    """格式化缺失行情列表，兼容字符串和字典结构。"""
    if not missing_quotes:
        return "无"

    formatted: List[str] = []
    for item in missing_quotes:
        if isinstance(item, dict):
            asset_code = item.get("asset_code", "?")
            trade_date = item.get("trade_date")
            formatted.append(f"{asset_code}@{trade_date}" if trade_date else str(asset_code))
        else:
            formatted.append(str(item))
    return ", ".join(formatted)


class PostMarketAssetRefreshService:
    """采集后账户资产更新编排服务。"""

    def _build_summary(
        self,
        target_date: Optional[str],
        updated_code_set: Set[str],
        failed_codes: List[str],
        empty_codes: List[str],
    ) -> Dict[str, object]:
        return {
            "target_date": target_date or "",
            "updated_code_count": len(updated_code_set),
            "failed_code_count": len(set(failed_codes)),
            "empty_code_count": len(set(empty_codes)),
            "affected_account_count": 0,
            "current_refresh_skipped": 0,
            "current_refresh_success": 0,
            "current_refresh_failed": 0,
            "history_refresh_success": 0,
            "history_refresh_skipped": 0,
            "history_refresh_failed": 0,
            "confirm_scanned": 0,
            "confirm_success": 0,
            "confirm_failed": 0,
            "skipped_accounts": [],
            "skipped_account_details": [],
            "missing_quotes_summary": [],
        }

    def _emit_lines(self, *lines: str) -> None:
        write_console_lines(*lines)

    @staticmethod
    def _report_progress(
        callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]],
        progress: Optional[int],
        sub_progress: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        if callback:
            callback(progress, sub_progress, detail)

    def _emit_overview(
        self,
        target_date: str,
        updated_code_set: Set[str],
        failed_codes: List[str],
        empty_codes: List[str],
        affected_accounts: List[int],
    ) -> None:
        empty_set = set(empty_codes)
        empty_desc = f" ({_fmt_codes_with_names(sorted(empty_set))})" if empty_set else ""
        failed_set = set(failed_codes)
        failed_desc = f" ({_fmt_codes_with_names(sorted(failed_set))})" if failed_set else ""

        self._emit_lines(
            _LINE_FULL,
            f"  数据更新日期: {target_date}",
            "  行情更新判定 (根据本次采集结果):",
            f"     成功更新: {len(updated_code_set)} 只标的",
            f"     数据为空: {len(empty_set)} 只标的{empty_desc}",
            f"     更新失败: {len(failed_set)} 只标的{failed_desc}",
            f"     影响账户: {len(affected_accounts)} 个 (将触发更新)",
        )

    def _run_corporate_action_confirm(self, target_date: str, updated_codes: Set[str], summary: Dict[str, object]) -> None:
        from core.corporate_action.confirm_service import corporate_action_confirm_service

        result = corporate_action_confirm_service.confirm_pending_actions(
            target_date=target_date,
            asset_codes=sorted(updated_codes),
        )
        summary["confirm_scanned"] = int(result.get("scanned") or 0)
        summary["confirm_success"] = int(result.get("confirmed") or 0)
        summary["confirm_failed"] = int(result.get("failed") or 0)
        self._emit_lines(
            f"  企业事件自动确认: 扫描 {summary['confirm_scanned']} | 成功 {summary['confirm_success']} | 失败 {summary['confirm_failed']}"
        )

    def _emit_account_header(self, account_name: str, account_id: int) -> None:
        self._emit_lines(
            _LINE_HALF,
            f"  正在更新账户: {account_name} (ID: {account_id})",
        )

    def _record_skipped_account(
        self,
        summary: Dict[str, object],
        account_id: int,
        reason: str,
        missing_codes: Optional[List[str]] = None,
    ) -> None:
        detail = {"account_id": account_id, "reason": reason}
        if missing_codes is not None:
            detail["missing_codes"] = missing_codes
        summary["skipped_accounts"].append(account_id)
        summary["skipped_account_details"].append(detail)

    def _emit_current_refresh_success(
        self,
        current_summary: Dict[str, object],
        daily_return: Optional[float],
    ) -> None:
        lines = [
            "   当日资产计算: 成功",
            f"      持仓标的总数: {int(current_summary.get('position_count', 0))} 只",
            f"      现金余留 (元): {_fmt_amount(current_summary.get('cash_balance', 0))}",
            f"      累计入金 (元): {_fmt_amount(current_summary.get('total_deposit', 0))}",
            f"      累计出金 (元): {_fmt_amount(current_summary.get('total_withdraw', 0))}",
            f"      累计盈亏 (元): {_fmt_amount(current_summary.get('acc_profit', 0), show_sign=True)}",
        ]
        if daily_return is not None:
            lines.append(f"      当日盈亏 (元): {_fmt_amount(daily_return, show_sign=True)}")
        else:
            lines.append("      当日盈亏 (元): 暂无记录")
        self._emit_lines(*lines)

    def _emit_history_no_fact_date(self) -> None:
        self._emit_lines("   历史资产重算: 跳过 (无历史事实日期)")

    def _emit_refresh_summary(
        self,
        summary: Dict[str, object],
        failed_codes: List[str],
        empty_codes: List[str],
    ) -> None:
        failed_set = set(failed_codes)
        empty_set = set(empty_codes)
        lines = [
            _LINE_FULL,
            "  资产更新步骤完成总结:",
            f"     数据更新日期: {summary['target_date']}",
            f"     影响账户总数: {summary['affected_account_count']} 个",
            (
                f"     当日账单更新: "
                f"成功 {summary['current_refresh_success']} | "
                f"跳过 {summary['current_refresh_skipped']} | "
                f"失败 {summary['current_refresh_failed']}"
            ),
            (
                f"     历史账单重算: "
                f"成功 {summary['history_refresh_success']} | "
                f"跳过 {summary['history_refresh_skipped']} | "
                f"失败 {summary['history_refresh_failed']}"
            ),
        ]
        if summary["failed_code_count"] > 0 or summary["empty_code_count"] > 0:
            lines.append("     数据异常提醒:")
            if summary["empty_code_count"] > 0:
                lines.append(f"        数据为空: {_fmt_codes_with_names(sorted(empty_set))}")
            if summary["failed_code_count"] > 0:
                lines.append(f"        更新失败: {_fmt_codes_with_names(sorted(failed_set))}")
        lines.append(_LINE_FULL)
        self._emit_lines(*lines)

    def refresh_after_market_update(
        self,
        target_date: Optional[str],
        updated_codes: List[str],
        failed_codes: Optional[List[str]] = None,
        empty_codes: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ) -> Dict[str, object]:
        failed_codes = failed_codes or []
        empty_codes = empty_codes or []
        updated_code_set = set(updated_codes or [])
        summary = self._build_summary(target_date, updated_code_set, failed_codes, empty_codes)
        self._report_progress(progress_callback, 5, None, "准备资产刷新")

        if not target_date:
            logger.info("[POST_MARKET_ASSET_REFRESH] 跳过：本次无有效 target_date")
            self._report_progress(progress_callback, 100, "0/0", "无有效 target_date")
            return summary

        # 企业事件确认以“最新可用行情日”为准，不应依赖本次是否恰好产生新成功更新代码。
        # 否则在复制生产库到测试库、或行情已对齐但补录企业事件的场景下，PENDING 事件会永远跳过确认。
        self._report_progress(progress_callback, 15, None, "企业事件自动确认")
        self._run_corporate_action_confirm(target_date=target_date, updated_codes=updated_code_set, summary=summary)

        if not updated_code_set:
            logger.info(
                "[POST_MARKET_ASSET_REFRESH] 跳过：本次无成功更新代码 target_date=%s failed=%s empty=%s",
                target_date,
                len(set(failed_codes)),
                len(set(empty_codes)),
            )
            self._report_progress(progress_callback, 100, "0/0", "无成功更新代码")
            return summary

        holding_map = position_dao.get_active_account_holding_codes()
        affected_accounts = self._resolve_affected_accounts(holding_map, updated_code_set)
        summary["affected_account_count"] = len(affected_accounts)
        total_accounts = len(affected_accounts)

        self._emit_overview(
            target_date=target_date,
            updated_code_set=updated_code_set,
            failed_codes=failed_codes,
            empty_codes=empty_codes,
            affected_accounts=affected_accounts,
        )
        self._report_progress(progress_callback, 20, f"0/{total_accounts}", "扫描受影响账户")

        # 保留内部日志，便于后台排查
        logger.debug(
            "[POST_MARKET_ASSET_REFRESH] 开始 target_date=%s updated=%s failed=%s empty=%s affected_accounts=%s",
            target_date,
            len(updated_code_set),
            len(set(failed_codes)),
            len(set(empty_codes)),
            len(affected_accounts),
        )

        if total_accounts == 0:
            self._report_progress(progress_callback, 100, "0/0", "无受影响账户")

        for index, account_id in enumerate(sorted(affected_accounts), start=1):
            hold_codes = sorted(set(holding_map.get(account_id, [])))
            matched_codes = sorted(updated_code_set.intersection(hold_codes))

            account_name = _get_account_name(account_id)
            self._emit_account_header(account_name, account_id)

            try:
                if not matched_codes:
                    self._record_skipped_account(summary, account_id, "no_matched_codes")
                    self._emit_lines("   当日资产计算: 跳过 (持仓与本次更新标的无交集)")
                    logger.debug(
                        "[POST_MARKET_ASSET_REFRESH][SKIP] account_id=%s reason=no_matched_codes",
                        account_id,
                    )
                    continue

                missing_snapshot_codes = self._get_missing_snapshot_codes(hold_codes, target_date)
                if missing_snapshot_codes:
                    summary["current_refresh_skipped"] += 1
                    self._record_skipped_account(
                        summary,
                        account_id,
                        "incomplete_snapshot_quotes",
                        missing_codes=missing_snapshot_codes,
                    )
                    self._emit_lines(
                        f"   当日资产计算: 跳过 (持仓行情不完整，缺失: {', '.join(missing_snapshot_codes)})"
                    )
                    logger.warning(
                        "[POST_MARKET_ASSET_REFRESH][SKIP] account_id=%s reason=incomplete_snapshot_quotes target_date=%s matched_codes=%s missing_codes=%s",
                        account_id,
                        target_date,
                        ",".join(matched_codes),
                        ",".join(missing_snapshot_codes),
                    )
                    continue

                try:
                    # 目标日口径仅用于日志展示，不允许覆盖当前缓存。
                    current_summary = account_rebuild_service.preview_current_state(
                        account_id=account_id,
                        as_of_date=target_date,
                    )
                    # 当前缓存必须按“全量事实 + 最新可用行情”刷新，避免把 target_date 口径写回实时状态。
                    account_rebuild_service.rebuild_current_state(account_id=account_id)
                    summary["current_refresh_success"] += 1

                    logger.debug(
                        "[POST_MARKET_ASSET_REFRESH][ACCOUNT] account_id=%s current=success matched_codes=%s summary=%s",
                        account_id,
                        ",".join(matched_codes),
                        current_summary,
                    )
                except Exception as exc:
                    summary["current_refresh_failed"] += 1
                    self._emit_lines(f"   当日资产计算: 失败 ({exc})")
                    logger.error(
                        "[POST_MARKET_ASSET_REFRESH][ACCOUNT] account_id=%s current=failed matched_codes=%s detail=%s",
                        account_id,
                        ",".join(matched_codes),
                        exc,
                        exc_info=True,
                    )
                    continue

                from_date = self._resolve_history_from_date(account_id)
                if not from_date:
                    summary["history_refresh_skipped"] += 1
                    daily_return = _get_daily_return(account_id, target_date)
                    self._emit_current_refresh_success(current_summary, daily_return)
                    self._emit_history_no_fact_date()
                    logger.debug(
                        "[POST_MARKET_ASSET_REFRESH][SKIP] account_id=%s history=no_fact_date matched_codes=%s",
                        account_id,
                        ",".join(matched_codes),
                    )
                    continue

                history_result = account_history_rebuild_service.try_rebuild_history(
                    account_id=account_id,
                    from_date=from_date,
                )
                daily_return = _get_daily_return(account_id, target_date)
                self._emit_current_refresh_success(current_summary, daily_return)
                self._apply_history_result(summary, account_id, from_date, matched_codes, history_result)
            finally:
                account_progress = min(100, 20 + round((index / total_accounts) * 80))
                self._report_progress(
                    progress_callback,
                    account_progress,
                    f"{index}/{total_accounts}",
                    f"资产刷新: {account_name}",
                )

        self._emit_refresh_summary(summary, failed_codes, empty_codes)
        self._report_progress(progress_callback, 100, f"{total_accounts}/{total_accounts}", "资产刷新完成")

        logger.info("[POST_MARKET_ASSET_REFRESH] 完成 summary=%s", summary)
        return summary

    def _resolve_affected_accounts(
        self,
        holding_map: Dict[int, List[str]],
        updated_codes: Set[str],
    ) -> List[int]:
        affected_accounts: List[int] = []
        for account_id, hold_codes in holding_map.items():
            if updated_codes.intersection(hold_codes):
                affected_accounts.append(account_id)
        return affected_accounts

    def _resolve_history_from_date(self, account_id: int) -> Optional[str]:
        # 历史补算起点只能依赖正式收盘历史，不能被 live snapshot 顶到未来日期。
        latest_history = account_history_dao.get_latest_complete_history(account_id)
        if latest_history and latest_history.get("trade_date"):
            latest_dt = datetime.strptime(latest_history["trade_date"], "%Y-%m-%d")
            return (latest_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        return trade_dao.get_account_first_fact_date(account_id)

    def _get_missing_snapshot_codes(self, hold_codes: List[str], target_date: str) -> List[str]:
        hold_code_list = sorted(set(hold_codes or []))
        if not hold_code_list or not target_date:
            return []

        market_quotes = market_dao.get_latest_prices_batch_as_of(hold_code_list, target_date)
        fund_quotes = market_dao.get_latest_fund_navs_batch_as_of(hold_code_list, target_date)

        missing_codes: List[str] = []
        for asset_code in hold_code_list:
            market_trade_date = (market_quotes.get(asset_code) or {}).get("trade_date")
            fund_trade_date = (fund_quotes.get(asset_code) or {}).get("trade_date")
            if market_trade_date == target_date or fund_trade_date == target_date:
                continue
            missing_codes.append(asset_code)
        return missing_codes

    def _apply_history_result(
        self,
        summary: Dict[str, object],
        account_id: int,
        from_date: str,
        matched_codes: List[str],
        history_result: Dict[str, object],
    ) -> None:
        message = str(history_result.get("message", ""))
        missing_quotes = history_result.get("missing_quotes") or []
        updated_rows = int(history_result.get("updated_rows") or 0)

        if "行情不完整" in message or missing_quotes or "无交易日" in message:
            summary["history_refresh_skipped"] += 1
            if missing_quotes:
                summary["missing_quotes_summary"].append(
                    {
                        "account_id": account_id,
                        "missing_quotes": missing_quotes,
                    }
                )
            missing_desc = f" (缺失行情: {_fmt_missing_quotes(missing_quotes)})"
            self._emit_lines(
                "   历史资产重算: 跳过",
                f"      检查起点日期: {from_date}",
                f"      跳过原因说明: {message}{missing_desc}",
            )
            logger.warning(
                "[POST_MARKET_ASSET_REFRESH][ACCOUNT] account_id=%s history=skipped from_date=%s matched_codes=%s message=%s missing_quotes=%s",
                account_id,
                from_date,
                ",".join(matched_codes),
                message,
                missing_quotes,
            )
            return

        if updated_rows > 0 or "成功" in message:
            summary["history_refresh_success"] += 1
            self._emit_lines(
                "   历史资产重算: 成功",
                f"      检查起点日期: {from_date}",
                f"      更新行数: {updated_rows}",
            )
            logger.debug(
                "[POST_MARKET_ASSET_REFRESH][ACCOUNT] account_id=%s history=success from_date=%s matched_codes=%s updated_rows=%s message=%s",
                account_id,
                from_date,
                ",".join(matched_codes),
                updated_rows,
                message,
            )
            return

        summary["history_refresh_failed"] += 1
        self._emit_lines(f"   历史资产重算: 失败 ({message})")
        logger.error(
            "[POST_MARKET_ASSET_REFRESH][ACCOUNT] account_id=%s history=failed from_date=%s matched_codes=%s message=%s result=%s",
            account_id,
            from_date,
            ",".join(matched_codes),
            message,
            history_result,
        )


post_market_asset_refresh_service = PostMarketAssetRefreshService()
