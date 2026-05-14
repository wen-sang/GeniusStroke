from typing import Literal, Optional

from pydantic import BaseModel, Field


class AccountSummaryResponse(BaseModel):
    """账户汇总响应"""

    account_id: int
    account_name: str
    broker_name: str
    cash_balance: float
    total_market_value: float
    total_asset: float
    total_deposit: float
    total_withdraw: float
    acc_profit: float
    floating_pnl: float
    daily_return: float
    daily_return_rate: float
    history_total_pnl: float
    history_total_pnl_rate: float
    account_xirr: float
    data_updated_to: Optional[str] = None
    commission_rate: float
    commission_min: float
    stamp_duty_rate: float


class DepositRequest(BaseModel):
    """入金请求"""

    amount: float = Field(..., gt=0, description="入金金额")
    remark: str = Field("", description="备注")


class WithdrawRequest(BaseModel):
    """出金请求"""

    amount: float = Field(..., gt=0, description="出金金额")
    remark: str = Field("", description="备注")


class AdjustRequest(BaseModel):
    """调账请求"""

    amount: float = Field(..., gt=0, description="调账金额，始终传正值")
    direction: Literal["IN", "OUT"] = Field(..., description="调账方向：IN=增加现金，OUT=减少现金")
    remark: str = Field("", description="备注")
    biz_date: Optional[str] = Field(None, description="业务日期 YYYY-MM-DD")


class CashFlowCreateRequest(BaseModel):
    """资金流水新增请求"""

    flow_type: Literal["DEPOSIT", "WITHDRAW", "ADJUST"] = Field(..., description="资金流水类型")
    amount: float = Field(..., gt=0, description="金额，始终传正值")
    remark: str = Field("", description="备注")
    biz_date: Optional[str] = Field(None, description="业务日期 YYYY-MM-DD")
    adjust_direction: Optional[Literal["IN", "OUT"]] = Field(
        None,
        description="仅 ADJUST 需要，IN=增加现金，OUT=减少现金",
    )


class CashFlowResponse(BaseModel):
    """资金流水响应"""

    flow_id: int
    account_id: int
    biz_date: str
    flow_type: str
    direction: str
    amount: float
    remark: str
    source_type: Optional[str] = None
    source_ref_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OperationResponse(BaseModel):
    """操作响应"""

    success: bool
    message: str


class RebuildResponse(BaseModel):
    """重算响应"""

    success: bool
    message: str
    summary: dict


class ImportRebuildCashReconcileRequest(BaseModel):
    auto_inject_opening_adjust: bool = Field(True, description="是否自动补足期初现金")
    opening_adjust_date: Optional[str] = Field(None, description="期初调账日期 YYYY-MM-DD")
    target_final_cash: Optional[float] = Field(None, description="目标期末现金")
    final_adjust_date: Optional[str] = Field(None, description="期末调账日期 YYYY-MM-DD")


class ImportRebuildRequest(BaseModel):
    dry_run: bool = Field(False, description="是否仅预检查，不执行清理和导入")
    account_no: Optional[str] = Field(None, description="账户编号")
    account_name: Optional[str] = Field(None, description="账户名称")
    broker_name: Optional[str] = Field(None, description="券商名称")
    commission_rate: Optional[float] = Field(None, description="佣金费率")
    commission_min: Optional[float] = Field(None, description="最低佣金")
    stamp_duty_rate: Optional[float] = Field(None, description="印花税率")
    history_file: Optional[str] = Field(None, description="历史交易文件绝对路径")
    history_sheet: Optional[str] = Field(None, description="历史交易 Sheet 名")
    deposit_file: Optional[str] = Field(None, description="入金文件绝对路径")
    withdraw_file: Optional[str] = Field(None, description="出金文件绝对路径")
    valuation_date: Optional[str] = Field(None, description="估值日期 YYYY-MM-DD")
    cash_reconcile: Optional[ImportRebuildCashReconcileRequest] = Field(
        None,
        description="现金对账配置",
    )


class ImportRebuildResponse(BaseModel):
    success: bool
    message: str
    account_id: Optional[int] = None
    preview: dict = Field(default_factory=dict)
    current_summary: dict = Field(default_factory=dict)
    history_summary: dict = Field(default_factory=dict)


class AccountListItem(BaseModel):
    """账户列表项"""

    account_id: int
    account_name: str


class AccountManageRequest(BaseModel):
    """账户新增/编辑请求"""

    account_name: str = Field(..., description="账户名称")


class AccountManageModel(BaseModel):
    """账户管理模型"""

    account_id: int
    account_name: str


class AccountManageResponse(BaseModel):
    """账户新增/编辑响应"""

    success: bool
    message: str
    account: AccountManageModel


class AccountDeleteResponse(BaseModel):
    """账户删除响应"""

    success: bool
    message: str
    deleted_account_id: int
    next_account_id: Optional[int] = None
    remaining_account_count: int
