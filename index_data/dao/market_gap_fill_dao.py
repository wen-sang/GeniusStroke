# 文件: dao/market_gap_fill_dao.py
"""行情缺口治理 DAO 门面。

方法实现按职责拆分在 dao/market_gap_fill/ 各 Mixin 模块：
task_lifecycle（任务生命周期）、commit（落库提交）、queries（状态与统计查询）、
support（issue 状态同步与共享辅助函数）。
外部导入路径与单例保持不变。
"""
from dao.base_dao import BaseDAO
from dao.market_gap_fill.commit import CommitMixin
from dao.market_gap_fill.queries import QueryMixin
from dao.market_gap_fill.support import GapIssueSyncMixin
from dao.market_gap_fill.task_lifecycle import TaskLifecycleMixin


class MarketGapFillDAO(
    TaskLifecycleMixin,
    CommitMixin,
    QueryMixin,
    GapIssueSyncMixin,
    BaseDAO,
):
    """行情缺口治理任务 DAO"""

    @property
    def table_name(self) -> str:
        return 'dat_market_gap_fill_task'


market_gap_fill_dao = MarketGapFillDAO()
