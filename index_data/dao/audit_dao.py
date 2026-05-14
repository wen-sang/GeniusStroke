"""
审计日志数据访问层 (Audit DAO)

管理 log_trade_audit 表，记录所有资金变动流水。
支持可追溯、可还原的完整审计日志。
"""
import json
from typing import List, Dict, Any, Optional
from dao.base_dao import BaseDAO
from utils.logger import logger


class AuditDAO(BaseDAO):
    """审计日志数据访问对象"""
    
    @property
    def table_name(self) -> str:
        return "log_trade_audit"
    
    def log_action(self, account_id: int, action_type: str,
                   order_id: int = None,
                   before_cash: float = None, after_cash: float = None,
                   before_deposit: float = None, after_deposit: float = None,
                   before_withdraw: float = None, after_withdraw: float = None,
                   before_profit: float = None, after_profit: float = None,
                   amount_change: float = None,
                   snapshot: Dict = None,
                   remark: str = None) -> int:
        """
        记录一条审计日志
        
        :param account_id: 账户ID
        :param action_type: 操作类型 (INIT/DEPOSIT/WITHDRAW/BUY/SELL/DIV_CASH/ADJUST等)
        :param order_id: 关联订单ID (可选)
        :param before_cash: 变动前现金余额
        :param after_cash: 变动后现金余额
        :param before_deposit: 变动前累计入金
        :param after_deposit: 变动后累计入金
        :param before_withdraw: 变动前累计出金
        :param after_withdraw: 变动后累计出金
        :param before_profit: 变动前已实现收益
        :param after_profit: 变动后已实现收益
        :param amount_change: 资金变动额
        :param snapshot: 完整快照 (JSON)
        :param remark: 备注
        :return: 新日志ID
        """
        snapshot_json = json.dumps(snapshot, ensure_ascii=False) if snapshot else None
        
        sql = """
        INSERT INTO log_trade_audit (
            account_id, order_id, action_type,
            before_cash, after_cash, amount_change,
            before_deposit, after_deposit,
            before_withdraw, after_withdraw,
            before_profit, after_profit,
            snapshot_json, remark, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """
        with self.db_engine.get_connection(readonly=False) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (
                account_id, order_id, action_type,
                before_cash, after_cash, amount_change,
                before_deposit, after_deposit,
                before_withdraw, after_withdraw,
                before_profit, after_profit,
                snapshot_json, remark
            ))
            return cursor.lastrowid
    
    def get_audit_trail(self, account_id: int, 
                        limit: int = 100,
                        action_type: str = None) -> List[Dict]:
        """
        获取审计日志列表
        
        :param account_id: 账户ID
        :param limit: 返回条数限制
        :param action_type: 可选的操作类型过滤
        :return: 日志列表 (按时间倒序)
        """
        sql = f"""
        SELECT
            log_id, account_id, order_id, action_type,
            before_cash, after_cash, amount_change,
            before_deposit, after_deposit,
            before_withdraw, after_withdraw,
            before_profit, after_profit,
            snapshot_json, remark, created_at
        FROM {self.table_name}
        WHERE account_id = ?
        """
        params = [account_id]
        
        if action_type:
            sql += " AND action_type = ?"
            params.append(action_type)
        
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)
    
    def get_last_state(self, account_id: int) -> Optional[Dict]:
        """
        获取最后一条日志的状态 (用于还原)
        
        :return: 包含 after_* 字段的字典
        """
        sql = f"""
        SELECT after_cash, after_deposit, after_withdraw, after_profit
        FROM {self.table_name}
        WHERE account_id = ?
        ORDER BY log_id DESC
        LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (account_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'cash_balance': row[0],
                    'total_deposit': row[1],
                    'total_withdraw': row[2],
                    'acc_profit': row[3]
                }
            return None
    
    def rebuild_account_state(self, account_id: int, 
                              up_to_log_id: int = None) -> Dict:
        """
        通过回放日志重建账户状态
        
        :param account_id: 账户ID
        :param up_to_log_id: 回放到指定日志ID (可选)
        :return: 重建后的账户状态
        """
        sql = f"""
        SELECT action_type, amount_change, after_cash, after_deposit, 
               after_withdraw, after_profit
        FROM {self.table_name}
        WHERE account_id = ?
        """
        params = [account_id]
        
        if up_to_log_id:
            sql += " AND log_id <= ?"
            params.append(up_to_log_id)
        
        sql += " ORDER BY log_id ASC"
        
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            if not rows:
                return {'cash_balance': 0, 'total_deposit': 0, 
                        'total_withdraw': 0, 'acc_profit': 0}
            
            # 返回最后一条的 after 状态
            last = rows[-1]
            return {
                'cash_balance': last[2] or 0,
                'total_deposit': last[3] or 0,
                'total_withdraw': last[4] or 0,
                'acc_profit': last[5] or 0
            }


# 单例
audit_dao = AuditDAO()
