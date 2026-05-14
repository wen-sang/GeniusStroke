"""
DAO 基类定义

提供通用的数据库操作方法，所有DAO类继承此基类。
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict, Tuple, Sequence, Callable
from core.db_engine import db_engine


class BaseDAO(ABC):
    """
    DAO 基类
    
    提供通用的数据库操作方法，子类继承后可复用这些方法。
    """
    
    def __init__(self):
        self.db_engine = db_engine
    
    @property
    @abstractmethod
    def table_name(self) -> str:
        """子类必须实现：返回对应的表名"""
        pass
    
    def _execute_query(self, sql: str, params: tuple = (),
                       readonly: bool = True) -> List[tuple]:
        """
        执行查询SQL
        
        :param sql: SQL 语句
        :param params: 参数元组
        :param readonly: 是否只读查询
        :return: 查询结果列表
        """
        with self.db_engine.get_connection(readonly=readonly) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
    
    def _execute_update(self, sql: str, params: tuple = ()) -> int:
        """
        执行更新SQL
        
        :param sql: SQL 语句
        :param params: 参数元组
        :return: 受影响的行数
        """
        with self.db_engine.get_connection(readonly=False) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.rowcount
    
    def _execute_many(self, sql: str, data: List[tuple]) -> int:
        """
        批量执行SQL
        
        :param sql: SQL 语句
        :param data: 数据列表
        :return: 受影响的行数
        """
        with self.db_engine.get_connection(readonly=False) as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, data)
            return cursor.rowcount
    
    def _row_to_dict(self, cursor, row: Optional[tuple]) -> Dict[str, Any]:
        """
        将查询结果行转换为字典
        
        :param cursor: 数据库游标
        :param row: 结果行
        :return: 字典
        """
        if not row:
            return {}
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    
    def _rows_to_dicts(self, cursor, 
                       rows: List[tuple]) -> List[Dict[str, Any]]:
        """
        将查询结果转换为字典列表
        
        :param cursor: 数据库游标
        :param rows: 结果行列表
        :return: 字典列表
        """
        if not rows:
            return []
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    @staticmethod
    def _join_columns(columns: Sequence[str], indent: str = "            ") -> str:
        """将列名列表格式化为多行 SELECT 片段。"""
        return (",\n" + indent).join(columns)

    @staticmethod
    def _build_placeholders(values: Sequence[Any]) -> str:
        """根据参数数量构造 IN 查询占位符。"""
        return ",".join("?" for _ in values)

    @staticmethod
    def _rows_to_keyed_dict(
        rows: List[tuple],
        key_index: int,
        value_builder: Callable[[tuple], Any],
        row_filter: Optional[Callable[[tuple], bool]] = None,
    ) -> Dict[Any, Any]:
        """将结果行转换为以指定列为 key 的字典。"""
        result = {}
        for row in rows:
            if not row:
                continue
            key = row[key_index]
            if not key:
                continue
            if row_filter is not None and not row_filter(row):
                continue
            result[key] = value_builder(row)
        return result

    @staticmethod
    def _ensure_keys(result_dict: Dict[Any, Any], keys: Sequence[Any], default: Any = None) -> Dict[Any, Any]:
        """补齐缺失 key，保持批量查询结果结构稳定。"""
        for key in keys:
            result_dict.setdefault(key, default)
        return result_dict

    @staticmethod
    def _build_latest_trade_date_subquery(
        table_name: str,
        placeholders: str,
        extra_conditions: Optional[Sequence[str]] = None,
    ) -> str:
        """构造按资产代码分组取最新 trade_date 的子查询。"""
        conditions = [f"asset_code IN ({placeholders})"]
        if extra_conditions:
            conditions.extend(extra_conditions)
        where_clause = "\n              AND ".join(conditions)
        return f"""
            SELECT asset_code, MAX(trade_date) AS latest_trade_date
            FROM {table_name}
            WHERE {where_clause}
            GROUP BY asset_code
        """
