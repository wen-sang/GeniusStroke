"""
账户导入重建运行时。

承载 API 与 CLI 共享的导入重建逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from core.db_engine import db_engine
from core.trade.history_rebuild_service import account_history_rebuild_service
from core.trade.models import CashFlow, Order
from core.trade.rebuild_service import account_rebuild_service
from dao.cash_flow_dao import cash_flow_dao
from dao.import_rebuild_dao import import_rebuild_dao
from dao.trade_dao import trade_dao
from utils.logger import get_import_logger


logger = get_import_logger()
PROJECT_ROOT = Path(__file__).resolve().parents[3]


DEFAULT_CONFIG = {
    "account_no": "ACC0001",
    "account_name": "华宝ETF账户",
    "broker_name": "华宝证券",
    "commission_rate": 0.00001,
    "commission_min": 0.0,
    "stamp_duty_rate": 0.0,
    "history_file": str(PROJECT_ROOT / "Import_expert" / "my_history.xls"),
    "history_sheet": "交易流水",
    "deposit_file": str(PROJECT_ROOT / "Import_expert" / "20260202入金流水.xls"),
    "withdraw_file": str(PROJECT_ROOT / "Import_expert" / "20260202出金流水.xls"),
    "valuation_date": "2026-03-07",
    "cash_reconcile": {
        "auto_inject_opening_adjust": True,
        "opening_adjust_date": "2025-05-22",
        "target_final_cash": 2491.77,
        "final_adjust_date": "2026-02-25",
    },
    "skip_confirmation": False,
}


def merge_config(target: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_config(target[key], value)
        else:
            target[key] = value
    return target


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_str(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def format_date(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y%m%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def infer_exchange(code: str) -> str:
    if not code:
        return "SZ"
    if code.startswith(("6", "5", "9")):
        return "SH"
    if code.startswith(("0", "3", "159", "16")):
        return "SZ"
    if code.startswith(("8", "4")):
        return "BJ"
    return "SZ"


@dataclass
class HistoryRow:
    row_num: int
    asset_code: str
    asset_name: str
    asset_type: str
    exchange: str
    listing_date: Optional[str]
    buy_date: str
    buy_price: float
    buy_volume: float
    buy_commission: float
    buy_transfer_fee: float
    target_rate: float
    sell_date: Optional[str]
    sell_price: float
    sell_volume: float
    sell_commission: float
    sell_transfer_fee: float
    sell_tax: float


class AccountImportRebuilder:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.account_id: Optional[int] = None
        self.history_rows: List[HistoryRow] = []
        self.deposit_rows: List[Dict[str, Any]] = []
        self.withdraw_rows: List[Dict[str, Any]] = []
        self.opening_adjust_amount: float = 0.0
        self.final_adjust_amount: float = 0.0
        self.final_adjust_direction: str = "IN"

    def build_preview(self) -> Dict[str, Any]:
        self._validate_files()
        self._load_source_files()
        self._plan_cash_adjustments()
        sold_count = sum(1 for row in self.history_rows if row.sell_date and row.sell_volume > 0)
        preview = {
            "account_no": self.config["account_no"],
            "account_name": self.config["account_name"],
            "buy_batch_count": len(self.history_rows),
            "sell_record_count": sold_count,
            "deposit_count": len(self.deposit_rows),
            "withdraw_count": len(self.withdraw_rows),
            "opening_adjust_amount": round(self.opening_adjust_amount, 2),
            "final_adjust_amount": round(self.final_adjust_amount, 2),
            "final_adjust_direction": self.final_adjust_direction,
            "valuation_date": self.config.get("valuation_date"),
        }
        self._print_preview(preview)
        return preview

    def run(self) -> Dict[str, Any]:
        preview = self.build_preview()
        self.account_id = self._ensure_account()

        if not self.config.get("skip_confirmation", False):
            answer = input("确认执行重建? [y/N]: ").strip().lower()
            if answer != "y":
                print("已取消。")
                return {
                    "success": False,
                    "cancelled": True,
                    "account_id": self.account_id,
                    "preview": preview,
                }

        with db_engine.get_connection() as conn:
            self._clear_account_data(conn=conn)
            self._import_cash_flows(conn=conn)
            self._import_trade_orders(conn=conn)
            self._apply_optional_adjustment(conn=conn)
            current_summary = account_rebuild_service.rebuild_current_state(
                account_id=self.account_id,
                conn=conn,
                as_of_date=self.config.get("valuation_date"),
            )
            history_summary = account_history_rebuild_service.rebuild_history(
                account_id=self.account_id,
                conn=conn,
            )

        print("\n重建完成")
        print(f"当前状态: {current_summary}")
        print(f"历史状态: {history_summary}")
        logger.info("账户重建完成 account_id=%s current=%s history=%s", self.account_id, current_summary, history_summary)
        return {
            "success": True,
            "cancelled": False,
            "account_id": self.account_id,
            "preview": preview,
            "current_summary": current_summary,
            "history_summary": history_summary,
        }

    def _validate_files(self) -> None:
        file_keys = ("history_file", "deposit_file", "withdraw_file")
        missing_files = [self.config[key] for key in file_keys if not Path(self.config[key]).exists()]
        if missing_files:
            raise FileNotFoundError(f"导入文件不存在: {missing_files}")

    def _load_source_files(self) -> None:
        self.history_rows = self._load_history_rows(
            file_path=self.config["history_file"],
            sheet_name=self.config["history_sheet"],
        )
        self.deposit_rows = self._load_cash_flow_rows(
            file_path=self.config["deposit_file"],
            date_column="日期",
            amount_column="银行转证券（元）",
            flow_type="DEPOSIT",
        )
        self.withdraw_rows = self._load_cash_flow_rows(
            file_path=self.config["withdraw_file"],
            date_column="日期",
            amount_column="结转金额",
            flow_type="WITHDRAW",
        )

    def _ensure_account(self) -> int:
        return import_rebuild_dao.upsert_import_account(
            account_no=self.config["account_no"],
            account_name=self.config["account_name"],
            broker_name=self.config["broker_name"],
            commission_rate=self.config["commission_rate"],
            commission_min=self.config["commission_min"],
            stamp_duty_rate=self.config["stamp_duty_rate"],
        )

    def _print_preview(self, preview: Dict[str, Any]) -> None:
        print("\n==============================")
        print("账户历史数据重建预览")
        print("==============================")
        print(f"账户: {preview['account_no']} / {preview['account_name']}")
        print(f"买入批次: {preview['buy_batch_count']}")
        print(f"卖出记录: {preview['sell_record_count']}")
        print(f"入金记录: {preview['deposit_count']}")
        print(f"出金记录: {preview['withdraw_count']}")
        print(f"期初调账: {preview['opening_adjust_amount']:.2f}")
        print(f"期末调账: {preview['final_adjust_direction']} {preview['final_adjust_amount']:.2f}")
        print("==============================")

    def _clear_account_data(self, conn) -> None:
        import_rebuild_dao.clear_import_account_data(self.account_id, conn=conn)

    def _import_cash_flows(self, conn) -> None:
        all_rows = self._build_cash_flow_plan()
        for index, row in enumerate(all_rows, start=1):
            cash_flow = CashFlow(
                account_id=self.account_id,
                biz_date=row["biz_date"],
                flow_type=row["flow_type"],
                direction=row["direction"],
                amount=row["amount"],
                remark=row["remark"],
                source_type="IMPORT",
                source_ref_id=f"cash_flow:{row['source_key']}:{index}",
            )
            cash_flow_dao.insert_cash_flow(cash_flow, conn=conn)

    def _import_trade_orders(self, conn) -> None:
        for row in self.history_rows:
            self._upsert_asset_meta(
                asset_code=row.asset_code,
                asset_name=row.asset_name,
                exchange=row.exchange,
                listing_date=row.listing_date,
                asset_type=row.asset_type,
                conn=conn,
            )

            buy_order = Order(
                account_id=self.account_id,
                asset_code=row.asset_code,
                trade_time=f"{row.buy_date} 09:30:00",
                side="BUY",
                price=row.buy_price,
                volume=row.buy_volume,
                amount=row.buy_price * row.buy_volume,
                commission=row.buy_commission,
                transfer_fee=row.buy_transfer_fee,
                remain_vol=row.buy_volume,
                target_rate=row.target_rate,
                remark="历史导入",
                source_type="IMPORT",
                source_ref_id=f"my_history:row:{row.row_num}:BUY",
            )
            buy_order_id = trade_dao.insert_order(buy_order, conn=conn)

            if row.sell_date and row.sell_volume > 0 and row.sell_price > 0:
                sell_order = Order(
                    account_id=self.account_id,
                    asset_code=row.asset_code,
                    trade_time=f"{row.sell_date} 15:00:00",
                    side="SELL",
                    price=row.sell_price,
                    volume=row.sell_volume,
                    amount=row.sell_price * row.sell_volume,
                    commission=row.sell_commission,
                    transfer_fee=row.sell_transfer_fee,
                    tax=row.sell_tax,
                    link_order_id=buy_order_id,
                    remark="历史导入",
                    source_type="IMPORT",
                    source_ref_id=f"my_history:row:{row.row_num}:SELL",
                )
                trade_dao.insert_order(sell_order, conn=conn)

    def _apply_optional_adjustment(self, conn) -> None:
        """保留兼容钩子，当前调账已统一进入资金流水导入计划。"""
        return

    def _plan_cash_adjustments(self) -> None:
        plan = self._build_cash_flow_plan(include_auto_adjust=False)
        trade_events = []
        for row in self.history_rows:
            trade_events.append(
                (
                    row.buy_date,
                    "BUY",
                    row.buy_price * row.buy_volume + row.buy_commission + row.buy_transfer_fee,
                )
            )
            if row.sell_date and row.sell_volume > 0 and row.sell_price > 0:
                trade_events.append(
                    (
                        row.sell_date,
                        "SELL",
                        (
                            row.sell_price * row.sell_volume
                            - row.sell_commission
                            - row.sell_transfer_fee
                            - row.sell_tax
                        ),
                    )
                )

        ordered_events = [
            (item["biz_date"], item["flow_type"], item["amount"], item["direction"])
            for item in plan
        ]
        for date, kind, amount in trade_events:
            direction = "IN" if kind == "SELL" else "OUT"
            ordered_events.append((date, kind, amount, direction))

        priority = {"DEPOSIT": 0, "WITHDRAW": 1, "ADJUST": 2, "BUY": 3, "SELL": 4}
        ordered_events.sort(key=lambda item: (item[0], priority[item[1]]))

        cash_balance = 0.0
        min_cash = 0.0
        for date, kind, amount, direction in ordered_events:
            if direction == "IN":
                cash_balance += amount
            else:
                cash_balance -= amount
            min_cash = min(min_cash, cash_balance)

        reconcile_config = self.config.get("cash_reconcile", {})
        if reconcile_config.get("auto_inject_opening_adjust", False) and min_cash < 0:
            self.opening_adjust_amount = round(abs(min_cash), 2)

        projected_final_cash = cash_balance + self.opening_adjust_amount
        target_final_cash = reconcile_config.get("target_final_cash")
        if target_final_cash is not None:
            delta = round(float(target_final_cash) - projected_final_cash, 2)
            if abs(delta) >= 0.01:
                self.final_adjust_amount = abs(delta)
                self.final_adjust_direction = "IN" if delta > 0 else "OUT"

    def _build_cash_flow_plan(self, include_auto_adjust: bool = True) -> List[Dict[str, Any]]:
        all_rows = []
        for row in self.deposit_rows:
            all_rows.append({**row, "direction": "IN", "source_key": "deposit"})
        for row in self.withdraw_rows:
            all_rows.append({**row, "direction": "OUT", "source_key": "withdraw"})

        reconcile_config = self.config.get("cash_reconcile", {})
        if include_auto_adjust and self.opening_adjust_amount > 0:
            all_rows.append(
                {
                    "biz_date": reconcile_config.get("opening_adjust_date") or min(r["biz_date"] for r in all_rows),
                    "amount": self.opening_adjust_amount,
                    "flow_type": "ADJUST",
                    "direction": "IN",
                    "remark": f"自动补足期初现金 {self.opening_adjust_amount:.2f}",
                    "source_key": "adjust_opening",
                }
            )
        if include_auto_adjust and self.final_adjust_amount > 0:
            all_rows.append(
                {
                    "biz_date": reconcile_config.get("final_adjust_date") or max(r["biz_date"] for r in all_rows),
                    "amount": self.final_adjust_amount,
                    "flow_type": "ADJUST",
                    "direction": self.final_adjust_direction,
                    "remark": f"自动对齐期末现金 {self.final_adjust_direction} {self.final_adjust_amount:.2f}",
                    "source_key": "adjust_final",
                }
            )

        return sorted(all_rows, key=lambda item: (item["biz_date"], item["flow_type"], item["direction"]))

    def _load_history_rows(self, file_path: str, sheet_name: str) -> List[HistoryRow]:
        dataframe = pd.read_excel(file_path, sheet_name=sheet_name)
        result: List[HistoryRow] = []
        for index, row in dataframe.iterrows():
            asset_code = safe_str(row.get("代码"))
            buy_date = format_date(row.get("买入日期"))
            buy_price = safe_float(row.get("买入价格"))
            buy_volume = safe_float(row.get("买入份数"))
            if not asset_code or not buy_date or buy_price <= 0 or buy_volume <= 0:
                raise ValueError(f"交易历史第 {index + 2} 行关键字段缺失")

            target_rate_raw = safe_float(row.get("目标收益率"))
            target_rate = target_rate_raw / 100.0 if target_rate_raw > 1 else target_rate_raw
            result.append(
                HistoryRow(
                    row_num=index + 2,
                    asset_code=asset_code,
                    asset_name=safe_str(row.get("名称")) or asset_code,
                    asset_type=(safe_str(row.get("资产类型")) or "ETF").upper(),
                    exchange=infer_exchange(asset_code),
                    listing_date=format_date(row.get("上市时期")) or format_date(row.get("上市日期")),
                    buy_date=buy_date,
                    buy_price=buy_price,
                    buy_volume=buy_volume,
                    buy_commission=safe_float(row.get("买入手续费")),
                    buy_transfer_fee=safe_float(row.get("买入过户费")),
                    target_rate=target_rate,
                    sell_date=format_date(row.get("卖出日期")),
                    sell_price=safe_float(row.get("卖出价格")),
                    sell_volume=safe_float(row.get("卖出份数")),
                    sell_commission=safe_float(row.get("卖出手续费")),
                    sell_transfer_fee=safe_float(row.get("卖出过户费")),
                    sell_tax=safe_float(row.get("卖出印花税")),
                )
            )
        return result

    def _load_cash_flow_rows(
        self,
        file_path: str,
        date_column: str,
        amount_column: str,
        flow_type: str,
    ) -> List[Dict[str, Any]]:
        dataframe = pd.read_excel(file_path)
        rows: List[Dict[str, Any]] = []
        for index, row in dataframe.iterrows():
            biz_date = format_date(row.get(date_column))
            amount = safe_float(row.get(amount_column))
            if not biz_date or amount <= 0:
                continue
            rows.append(
                {
                    "biz_date": biz_date,
                    "amount": amount,
                    "flow_type": flow_type,
                    "remark": f"历史导入{flow_type.lower()}第{index + 2}行",
                }
            )
        return rows

    def _upsert_asset_meta(
        self,
        asset_code: str,
        asset_name: str,
        exchange: str,
        listing_date: Optional[str],
        asset_type: str = "ETF",
        conn=None,
    ) -> None:
        import_rebuild_dao.upsert_import_asset_meta(
            asset_code=asset_code,
            asset_name=asset_name,
            exchange=exchange,
            listing_date=listing_date,
            asset_type=asset_type,
            conn=conn,
        )
