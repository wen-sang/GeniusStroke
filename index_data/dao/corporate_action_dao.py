from typing import Dict, List, Optional, Sequence

from dao.base_dao import BaseDAO
from core.corporate_action.models import CorporateAction


class CorporateActionDAO(BaseDAO):
    @property
    def table_name(self) -> str:
        return "account_corporate_action"

    def insert_action(self, action: CorporateAction, conn=None) -> int:
        sql = """
        INSERT INTO account_corporate_action (
            account_id, asset_code, action_type, effective_date, record_date,
            ex_date, cash_base_unit, cash_base_qty, cash_amount, ratio_from,
            ratio_to, share_change_subtype, tax_mode, bundle_ref_id, reinvest_price,
            rounding_policy, status, remark, source_type, source_ref_id,
            confirmed_at, last_check_at, last_error_message, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            datetime('now', 'localtime'), datetime('now', 'localtime')
        )
        """
        params = (
            action.account_id,
            action.asset_code,
            action.action_type,
            action.effective_date,
            action.record_date,
            action.ex_date,
            action.cash_base_unit,
            action.cash_base_qty,
            action.cash_amount,
            action.ratio_from,
            action.ratio_to,
            action.share_change_subtype,
            action.tax_mode,
            action.bundle_ref_id,
            action.reinvest_price,
            action.rounding_policy,
            action.status,
            action.remark,
            action.source_type,
            action.source_ref_id,
            action.confirmed_at,
            action.last_check_at,
            action.last_error_message,
        )
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid

    def update_action(self, action: CorporateAction, conn=None) -> None:
        sql = """
        UPDATE account_corporate_action
        SET effective_date = ?,
            record_date = ?,
            ex_date = ?,
            cash_base_unit = ?,
            cash_base_qty = ?,
            cash_amount = ?,
            ratio_from = ?,
            ratio_to = ?,
            share_change_subtype = ?,
            tax_mode = ?,
            bundle_ref_id = ?,
            reinvest_price = ?,
            rounding_policy = ?,
            status = ?,
            remark = ?,
            confirmed_at = ?,
            last_check_at = ?,
            last_error_message = ?,
            updated_at = datetime('now', 'localtime')
        WHERE action_id = ?
        """
        params = (
            action.effective_date,
            action.record_date,
            action.ex_date,
            action.cash_base_unit,
            action.cash_base_qty,
            action.cash_amount,
            action.ratio_from,
            action.ratio_to,
            action.share_change_subtype,
            action.tax_mode,
            action.bundle_ref_id,
            action.reinvest_price,
            action.rounding_policy,
            action.status,
            action.remark,
            action.confirmed_at,
            action.last_check_at,
            action.last_error_message,
            action.action_id,
        )
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db_engine.get_connection() as write_conn:
            write_conn.execute(sql, params)

    def get_action(self, action_id: int, conn=None) -> Optional[CorporateAction]:
        sql = """
        SELECT
            action_id, account_id, asset_code, action_type, effective_date, record_date,
            ex_date, cash_base_unit, cash_base_qty, cash_amount, ratio_from, ratio_to,
            share_change_subtype, tax_mode, bundle_ref_id, reinvest_price,
            rounding_policy, status, remark, source_type, source_ref_id,
            confirmed_at, last_check_at, last_error_message, created_at, updated_at
        FROM account_corporate_action
        WHERE action_id = ?
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (action_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return CorporateAction.from_dict(self._row_to_dict(cursor, row))
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (action_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return CorporateAction.from_dict(self._row_to_dict(cursor, row))

    def exists_active_action(
        self,
        account_id: int,
        asset_code: str,
        effective_date: str,
        action_type: str,
        exclude_action_id: Optional[int] = None,
        conn=None,
    ) -> bool:
        sql = """
        SELECT 1
        FROM account_corporate_action
        WHERE account_id = ?
          AND asset_code = ?
          AND effective_date = ?
          AND action_type = ?
          AND status IN ('PENDING', 'CONFIRMED')
        """
        params: List[object] = [account_id, asset_code, effective_date, action_type]
        if exclude_action_id is not None:
            sql += " AND action_id != ?"
            params.append(exclude_action_id)
        sql += " LIMIT 1"
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return cursor.fetchone() is not None
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, tuple(params))
            return cursor.fetchone() is not None

    def exists_active_business_key(
        self,
        action: CorporateAction,
        exclude_action_id: Optional[int] = None,
        conn=None,
    ) -> bool:
        sql = """
        SELECT 1
        FROM account_corporate_action
        WHERE account_id = ?
          AND asset_code = ?
          AND action_type = ?
          AND status IN ('PENDING', 'CONFIRMED')
        """
        params: List[object] = [action.account_id, action.asset_code, action.action_type]
        key_fields = [
            ("record_date", action.record_date),
            ("ex_date", action.ex_date),
            ("effective_date", action.effective_date),
        ]
        if action.action_type == "CASH_DIVIDEND":
            key_fields.extend(
                [
                    ("cash_base_unit", action.cash_base_unit),
                    ("cash_base_qty", action.cash_base_qty),
                    ("cash_amount", action.cash_amount),
                    ("tax_mode", action.tax_mode),
                ]
            )
        elif action.action_type == "SPLIT":
            key_fields.extend(
                [
                    ("ratio_from", action.ratio_from),
                    ("ratio_to", action.ratio_to),
                    ("share_change_subtype", action.share_change_subtype),
                ]
            )
        else:
            key_fields.extend(
                [
                    ("cash_base_unit", action.cash_base_unit),
                    ("cash_amount", action.cash_amount),
                    ("reinvest_price", action.reinvest_price),
                    ("rounding_policy", action.rounding_policy),
                ]
            )
        for column_name, value in key_fields:
            if value is None:
                sql += f" AND {column_name} IS NULL"
            else:
                sql += f" AND {column_name} = ?"
                params.append(value)
        if exclude_action_id is not None:
            sql += " AND action_id != ?"
            params.append(exclude_action_id)
        sql += " LIMIT 1"

        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return cursor.fetchone() is not None
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, tuple(params))
            return cursor.fetchone() is not None

    def list_actions(
        self,
        account_id: int,
        asset_code: Optional[str] = None,
        status: Optional[str] = None,
        conn=None,
    ) -> List[Dict]:
        sql = """
        SELECT
            action_id, account_id, asset_code, action_type, effective_date, record_date,
            ex_date, cash_base_unit, cash_base_qty, cash_amount, ratio_from, ratio_to,
            share_change_subtype, tax_mode, bundle_ref_id, reinvest_price,
            rounding_policy, status, remark, source_type, source_ref_id,
            confirmed_at, last_check_at, last_error_message, created_at, updated_at
        FROM account_corporate_action
        WHERE account_id = ?
        """
        params: List[object] = [account_id]
        if asset_code:
            sql += " AND asset_code = ?"
            params.append(asset_code)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY effective_date DESC, action_id DESC"
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            return self._rows_to_dicts(cursor, cursor.fetchall())
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, tuple(params))
            return self._rows_to_dicts(cursor, cursor.fetchall())

    def list_actions_for_confirmation(
        self,
        target_date: str,
        account_ids: Optional[Sequence[int]] = None,
        asset_codes: Optional[Sequence[str]] = None,
        conn=None,
    ) -> List[CorporateAction]:
        sql = """
        SELECT
            action_id, account_id, asset_code, action_type, effective_date, record_date,
            ex_date, cash_base_unit, cash_base_qty, cash_amount, ratio_from, ratio_to,
            share_change_subtype, tax_mode, bundle_ref_id, reinvest_price,
            rounding_policy, status, remark, source_type, source_ref_id,
            confirmed_at, last_check_at, last_error_message, created_at, updated_at
        FROM account_corporate_action
        WHERE status = 'PENDING'
          AND effective_date <= ?
        """
        params: List[object] = [target_date]
        if account_ids:
            placeholders = ",".join("?" * len(account_ids))
            sql += f" AND account_id IN ({placeholders})"
            params.extend(account_ids)
        if asset_codes:
            placeholders = ",".join("?" * len(asset_codes))
            sql += f" AND asset_code IN ({placeholders})"
            params.extend(asset_codes)
        sql += " ORDER BY effective_date ASC, action_id ASC"

        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = self._rows_to_dicts(cursor, cursor.fetchall())
            return [CorporateAction.from_dict(row) for row in rows]

        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = self._rows_to_dicts(cursor, cursor.fetchall())
            return [CorporateAction.from_dict(row) for row in rows]

    def list_actions_by_bundle(
        self,
        bundle_ref_id: str,
        account_id: int,
        conn=None,
    ) -> List[CorporateAction]:
        sql = """
        SELECT
            action_id, account_id, asset_code, action_type, effective_date, record_date,
            ex_date, cash_base_unit, cash_base_qty, cash_amount, ratio_from, ratio_to,
            share_change_subtype, tax_mode, bundle_ref_id, reinvest_price,
            rounding_policy, status, remark, source_type, source_ref_id,
            confirmed_at, last_check_at, last_error_message, created_at, updated_at
        FROM account_corporate_action
        WHERE account_id = ?
          AND bundle_ref_id = ?
        ORDER BY effective_date ASC, action_id ASC
        """
        params = (account_id, bundle_ref_id)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = self._rows_to_dicts(cursor, cursor.fetchall())
            return [CorporateAction.from_dict(row) for row in rows]
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, params)
            rows = self._rows_to_dicts(cursor, cursor.fetchall())
            return [CorporateAction.from_dict(row) for row in rows]

    def get_asset_name(self, asset_code: str, conn=None) -> str:
        sql = """
        SELECT asset_name
        FROM sys_asset_meta
        WHERE asset_code = ?
        LIMIT 1
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (asset_code,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else asset_code
        with self.db_engine.get_connection(readonly=True) as ro_conn:
            cursor = ro_conn.cursor()
            cursor.execute(sql, (asset_code,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else asset_code

    def cancel_derived_cash_flows(self, action_id: int, conn=None) -> int:
        sql = """
        UPDATE account_cash_flow
        SET status = 'CANCELLED',
            updated_at = datetime('now', 'localtime')
        WHERE source_type = 'CORPORATE_ACTION'
          AND source_ref_id = ?
          AND COALESCE(status, 'ACTIVE') = 'ACTIVE'
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (str(action_id),))
            return cursor.rowcount
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, (str(action_id),))
            return cursor.rowcount

    def cancel_derived_orders(self, action_id: int, conn=None) -> int:
        sql = """
        UPDATE trade_order
        SET status = 0,
            updated_at = datetime('now', 'localtime')
        WHERE source_type = 'CORPORATE_ACTION'
          AND source_ref_id = ?
          AND status = 1
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(sql, (str(action_id),))
            return cursor.rowcount
        with self.db_engine.get_connection() as write_conn:
            cursor = write_conn.cursor()
            cursor.execute(sql, (str(action_id),))
            return cursor.rowcount


corporate_action_dao = CorporateActionDAO()
