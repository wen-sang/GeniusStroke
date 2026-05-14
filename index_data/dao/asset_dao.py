from typing import Any, Dict, List, Sequence, Tuple

from config.constants import DataInterface, DataSource
from dao.base_dao import BaseDAO


class AssetDAO(BaseDAO):
    """负责基础资产档案及其路由配置的持久化操作。"""

    DEFAULT_ROUTE_PRIORITY = 10
    DEPENDENCY_CHECKS: Sequence[Tuple[str, str]] = (
        ("dat_market_daily", "SELECT 1 FROM dat_market_daily WHERE asset_code=? LIMIT 1"),
        ("dat_fundamental_daily", "SELECT 1 FROM dat_fundamental_daily WHERE asset_code=? LIMIT 1"),
        ("dat_indicator_daily", "SELECT 1 FROM dat_indicator_daily WHERE asset_code=? LIMIT 1"),
        ("trade_order", "SELECT 1 FROM trade_order WHERE asset_code=? LIMIT 1"),
        ("dat_position", "SELECT 1 FROM dat_position WHERE asset_code=? LIMIT 1"),
    )

    @property
    def table_name(self) -> str:
        return "sys_asset_meta"

    def list_assets(self, category: str = "others", page: int = 1, page_size: int = 60) -> Dict[str, Any]:
        is_index = category == "index"
        offset = (page - 1) * page_size
        category_flag = 1 if is_index else 0

        sql = """
            SELECT
                m.asset_code, m.asset_name, m.asset_type,
                m.exchange, m.listing_date, m.market_category, m.is_active,
                COALESCE(r.source_id, ?) as source_id
            FROM sys_asset_meta m
            LEFT JOIN sys_data_router r ON m.asset_code = r.asset_code
            WHERE (
                (? = 1 AND m.asset_type = 'INDEX')
                OR (? = 0 AND m.asset_type != 'INDEX')
            )
            ORDER BY m.asset_code ASC
            LIMIT ? OFFSET ?
        """
        count_sql = """
            SELECT COUNT(*)
            FROM sys_asset_meta m
            WHERE (
                (? = 1 AND m.asset_type = 'INDEX')
                OR (? = 0 AND m.asset_type != 'INDEX')
            )
        """

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(count_sql, (category_flag, category_flag))
            total = cursor.fetchone()[0]
            cursor.execute(sql, (DataSource.LIXINREN, category_flag, category_flag, page_size, offset))
            items = self._rows_to_dicts(cursor, cursor.fetchall())

        total_pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def create_asset(
        self,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        exchange: str | None,
        listing_date: str | None,
        market_category: str,
        source_id: str,
    ) -> None:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM sys_asset_meta WHERE asset_code = ?", (asset_code,))
            if cursor.fetchone():
                raise ValueError(f"资产代码 {asset_code} 已存在")

        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sys_asset_meta
                (asset_code, asset_name, asset_type, exchange, listing_date, market_category, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (asset_code, asset_name, asset_type, exchange, listing_date, market_category),
            )
            cursor.execute(
                """
                INSERT INTO sys_data_router
                (asset_code, asset_type, interface, source_id, priority)
                VALUES (?, ?, ?, ?, ?)
                """,
                (asset_code, asset_type, DataInterface.DAILY_BAR, source_id, self.DEFAULT_ROUTE_PRIORITY),
            )

    def update_asset(
        self,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        exchange: str | None,
        listing_date: str | None,
        market_category: str,
        source_id: str,
    ) -> None:
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sys_asset_meta
                SET asset_name=?, asset_type=?, exchange=?, listing_date=?, market_category=?
                WHERE asset_code=?
                """,
                (asset_name, asset_type, exchange, listing_date, market_category, asset_code),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"资产代码 {asset_code} 不存在")

            cursor.execute("SELECT id FROM sys_data_router WHERE asset_code=?", (asset_code,))
            route_exists = cursor.fetchone()
            if route_exists:
                cursor.execute(
                    "UPDATE sys_data_router SET source_id=? WHERE asset_code=?",
                    (source_id, asset_code),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO sys_data_router (asset_code, asset_type, interface, source_id, priority)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (asset_code, asset_type, DataInterface.DAILY_BAR, source_id, self.DEFAULT_ROUTE_PRIORITY),
                )

    def delete_asset(self, asset_code: str) -> Dict[str, Any]:
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM sys_asset_meta WHERE asset_code=?", (asset_code,))
            if not cursor.fetchone():
                raise ValueError(f"资产代码 {asset_code} 不存在")

        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            self._ensure_asset_has_no_dependencies(cursor, asset_code)
            cursor.execute("DELETE FROM sys_data_router WHERE asset_code=?", (asset_code,))
            cursor.execute("DELETE FROM sys_asset_meta WHERE asset_code=?", (asset_code,))

        return {"status": "success", "msg": "由于无系统依赖数据，已物理删除该条目"}

    def _ensure_asset_has_no_dependencies(self, cursor, asset_code: str) -> None:
        for table_name, sql in self.DEPENDENCY_CHECKS:
            cursor.execute(sql, (asset_code,))
            if cursor.fetchone():
                raise ValueError(f"资产由于关联了历史数据表 [{table_name}] 而无法被删除")


asset_dao = AssetDAO()
