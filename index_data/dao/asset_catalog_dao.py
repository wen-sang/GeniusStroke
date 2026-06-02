import json
from typing import Any, Dict, List

from dao.base_dao import BaseDAO


class AssetCatalogDAO(BaseDAO):
    """外部标的目录与同步日志的数据访问层。"""

    @property
    def table_name(self) -> str:
        return "dat_external_asset_catalog"

    def upsert_catalog_items(
        self,
        source_id: str,
        items: list[dict],
        sync_time: str,
    ) -> int:
        with self.db_engine.get_connection() as conn:
            return self._upsert_catalog_items_with_cursor(
                conn.cursor(), source_id, items, sync_time
            )

    def deactivate_missing(
        self,
        source_id: str,
        active_external_symbols: set[str],
        sync_time: str,
    ) -> int:
        with self.db_engine.get_connection() as conn:
            return self._deactivate_missing_with_cursor(
                conn.cursor(), source_id, active_external_symbols, sync_time
            )

    def complete_successful_sync(
        self,
        sync_id: str,
        source_id: str,
        items: list[dict],
        sync_time: str,
        allow_deactivate: bool,
        skip_reason: str | None,
        finished_at: str,
    ) -> dict:
        with self.db_engine.get_connection() as conn:
            cursor = conn.cursor()
            total_upserted = self._upsert_catalog_items_with_cursor(
                cursor, source_id, items, sync_time
            )
            total_deactivated = 0
            if allow_deactivate:
                total_deactivated = self._deactivate_missing_with_cursor(
                    cursor,
                    source_id,
                    {item["external_symbol"] for item in items},
                    sync_time,
                )
            self._finish_sync_log_with_cursor(
                cursor=cursor,
                sync_id=sync_id,
                status="success",
                total_fetched=len(items),
                total_upserted=total_upserted,
                total_deactivated=total_deactivated,
                deactivation_skipped=not allow_deactivate,
                skip_reason=skip_reason,
                error_message=None,
                finished_at=finished_at,
            )
            return {
                "total_upserted": total_upserted,
                "total_deactivated": total_deactivated,
            }

    def search_catalog(
        self,
        source_id: str,
        keyword: str | None,
        asset_type: str | None,
        exchange: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        offset = (page - 1) * page_size
        where_parts = ["c.source_id = ?", "c.is_active = 1"]
        params: list[Any] = [source_id]

        if keyword:
            pattern = f"%{keyword.strip()}%"
            where_parts.append(
                "(c.asset_code LIKE ? OR c.external_symbol LIKE ? OR c.asset_name LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])
        if asset_type:
            where_parts.append("c.asset_type = ?")
            params.append(asset_type)
        if exchange:
            where_parts.append("c.exchange = ?")
            params.append(exchange)

        where_sql = " AND ".join(where_parts)
        count_sql = f"""
            SELECT COUNT(*)
            FROM dat_external_asset_catalog c
            LEFT JOIN sys_asset_meta m ON m.asset_code = c.asset_code
            WHERE {where_sql}
        """
        query_sql = f"""
            SELECT
                c.catalog_id,
                c.source_id,
                c.external_symbol,
                c.asset_code,
                c.asset_name,
                c.asset_type,
                c.exchange,
                c.market_category,
                c.listing_date,
                c.source_universe_id,
                c.source_universe_name,
                c.is_active,
                CASE WHEN m.asset_code IS NULL THEN 0 ELSE 1 END AS already_added,
                r.source_id AS current_route_source_id
            FROM dat_external_asset_catalog c
            LEFT JOIN sys_asset_meta m ON m.asset_code = c.asset_code
            LEFT JOIN sys_data_router r
                ON r.asset_code = c.asset_code
               AND r.interface = 'daily_bar'
            WHERE {where_sql}
            ORDER BY c.asset_code ASC, c.external_symbol ASC
            LIMIT ? OFFSET ?
        """

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(count_sql, tuple(params))
            total = cursor.fetchone()[0]
            cursor.execute(query_sql, tuple(params + [page_size, offset]))
            items = self._rows_to_dicts(cursor, cursor.fetchall())

        total_pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def search_unified_catalog(
        self,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 50)
        offset = (page - 1) * page_size
        pattern = f"%{keyword.strip()}%"
        params: list[Any] = [pattern, pattern, pattern]
        where_sql = """
            c.source_id IN ('lixinren', 'tickflow')
            AND c.is_active = 1
            AND (
                c.asset_code LIKE ?
                OR c.external_symbol LIKE ?
                OR c.asset_name LIKE ?
            )
        """
        count_sql = f"""
            SELECT COUNT(*)
            FROM dat_external_asset_catalog c
            WHERE {where_sql}
        """
        query_sql = f"""
            SELECT
                c.asset_code AS code,
                c.asset_name AS name,
                c.asset_type AS type,
                c.exchange AS exchange,
                c.source_id AS source,
                c.listing_date AS list_date,
                CASE
                    WHEN c.source_id = 'lixinren' AND instr(c.external_symbol, ':') > 0
                        THEN substr(c.external_symbol, instr(c.external_symbol, ':') + 1)
                    WHEN c.source_id = 'lixinren'
                        THEN c.asset_code
                    ELSE c.external_symbol
                END AS source_code,
                CASE WHEN m.asset_code IS NULL THEN 0 ELSE 1 END AS already_added
            FROM dat_external_asset_catalog c
            LEFT JOIN sys_asset_meta m ON m.asset_code = c.asset_code
            WHERE {where_sql}
            ORDER BY
                c.asset_code ASC,
                CASE c.source_id
                    WHEN 'lixinren' THEN 0
                    WHEN 'tickflow' THEN 1
                    ELSE 9
                END,
                c.external_symbol ASC
            LIMIT ? OFFSET ?
        """

        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(count_sql, tuple(params))
            total = cursor.fetchone()[0]
            cursor.execute(query_sql, tuple(params + [page_size, offset]))
            items = self._rows_to_dicts(cursor, cursor.fetchall())

        return {
            "items": items,
            "has_more": total > page * page_size,
        }

    def create_sync_log(self, sync_id: str, source_id: str, started_at: str) -> None:
        with self.db_engine.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO dat_external_asset_catalog_sync_log
                (sync_id, source_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (sync_id, source_id, started_at),
            )

    def finish_sync_log(
        self,
        sync_id: str,
        status: str,
        total_fetched: int,
        total_upserted: int,
        total_deactivated: int,
        deactivation_skipped: bool,
        skip_reason: str | None,
        error_message: str | None,
        finished_at: str,
    ) -> None:
        with self.db_engine.get_connection() as conn:
            self._finish_sync_log_with_cursor(
                cursor=conn.cursor(),
                sync_id=sync_id,
                status=status,
                total_fetched=total_fetched,
                total_upserted=total_upserted,
                total_deactivated=total_deactivated,
                deactivation_skipped=deactivation_skipped,
                skip_reason=skip_reason,
                error_message=error_message,
                finished_at=finished_at,
            )

    def get_latest_sync_log(self, source_id: str | None = None) -> dict:
        params: tuple[Any, ...] = ()
        where_sql = ""
        if source_id:
            where_sql = "WHERE source_id = ?"
            params = (source_id,)

        sql = f"""
            SELECT
                sync_id,
                source_id,
                status,
                started_at,
                finished_at,
                total_fetched,
                total_upserted,
                total_deactivated,
                deactivation_skipped,
                skip_reason,
                error_message
            FROM dat_external_asset_catalog_sync_log
            {where_sql}
            ORDER BY started_at DESC
            LIMIT 1
        """
        with self.db_engine.get_connection(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return self._row_to_dict(cursor, cursor.fetchone())

    @staticmethod
    def _build_catalog_row(source_id: str, item: dict, sync_time: str) -> tuple:
        raw_payload = item.get("raw_payload", item)
        if not isinstance(raw_payload, str):
            raw_payload = json.dumps(raw_payload, ensure_ascii=False)

        return (
            source_id,
            item["external_symbol"],
            item["asset_code"],
            item["asset_name"],
            item["asset_type"],
            item.get("exchange"),
            item.get("market_category") or "EXCHANGE",
            item.get("listing_date"),
            item.get("source_universe_id"),
            item.get("source_universe_name"),
            item.get("source_asset_type"),
            item.get("source_status"),
            raw_payload,
            sync_time,
            sync_time,
        )

    def _upsert_catalog_items_with_cursor(
        self,
        cursor,
        source_id: str,
        items: list[dict],
        sync_time: str,
    ) -> int:
        if not items:
            return 0

        rows = [self._build_catalog_row(source_id, item, sync_time) for item in items]
        cursor.executemany(
            """
            INSERT INTO dat_external_asset_catalog (
                source_id,
                external_symbol,
                asset_code,
                asset_name,
                asset_type,
                exchange,
                market_category,
                listing_date,
                source_universe_id,
                source_universe_name,
                source_asset_type,
                source_status,
                raw_payload,
                is_active,
                last_synced_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(source_id, external_symbol) DO UPDATE SET
                asset_code = excluded.asset_code,
                asset_name = excluded.asset_name,
                asset_type = excluded.asset_type,
                exchange = excluded.exchange,
                market_category = excluded.market_category,
                listing_date = excluded.listing_date,
                source_universe_id = excluded.source_universe_id,
                source_universe_name = excluded.source_universe_name,
                source_asset_type = excluded.source_asset_type,
                source_status = excluded.source_status,
                raw_payload = excluded.raw_payload,
                is_active = 1,
                last_synced_at = excluded.last_synced_at,
                updated_at = excluded.updated_at
            """,
            rows,
        )
        return cursor.rowcount

    def _deactivate_missing_with_cursor(
        self,
        cursor,
        source_id: str,
        active_external_symbols: set[str],
        sync_time: str,
    ) -> int:
        symbols = set(active_external_symbols)
        if symbols:
            sorted_symbols = sorted(symbols)
            placeholders = self._build_placeholders(sorted_symbols)
            sql = f"""
                UPDATE dat_external_asset_catalog
                SET is_active = 0, updated_at = ?
                WHERE source_id = ?
                  AND is_active = 1
                  AND external_symbol NOT IN ({placeholders})
            """
            cursor.execute(sql, (sync_time, source_id, *sorted_symbols))
        else:
            cursor.execute(
                """
                UPDATE dat_external_asset_catalog
                SET is_active = 0, updated_at = ?
                WHERE source_id = ? AND is_active = 1
                """,
                (sync_time, source_id),
            )
        return cursor.rowcount

    @staticmethod
    def _finish_sync_log_with_cursor(
        cursor,
        sync_id: str,
        status: str,
        total_fetched: int,
        total_upserted: int,
        total_deactivated: int,
        deactivation_skipped: bool,
        skip_reason: str | None,
        error_message: str | None,
        finished_at: str,
    ) -> None:
        cursor.execute(
            """
            UPDATE dat_external_asset_catalog_sync_log
            SET status = ?,
                finished_at = ?,
                total_fetched = ?,
                total_upserted = ?,
                total_deactivated = ?,
                deactivation_skipped = ?,
                skip_reason = ?,
                error_message = ?
            WHERE sync_id = ?
            """,
            (
                status,
                finished_at,
                total_fetched,
                total_upserted,
                total_deactivated,
                1 if deactivation_skipped else 0,
                skip_reason,
                error_message,
                sync_id,
            ),
        )


asset_catalog_dao = AssetCatalogDAO()
