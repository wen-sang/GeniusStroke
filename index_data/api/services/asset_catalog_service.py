import concurrent.futures
from datetime import datetime, timedelta
from typing import Any, Dict

from config.constants import DataSource
from config.settings import (
    ASSET_CATALOG_DEACTIVATE_MIN_FETCH_COUNT,
    ASSET_CATALOG_SYNC_ENABLED,
    ASSET_CATALOG_SYNC_TIMEOUT_SECONDS,
    ASSET_CATALOG_SYNC_TTL_SECONDS,
)
from core.asset_catalog.providers import get_catalog_provider
from dao.asset_catalog_dao import asset_catalog_dao
from utils.logger import logger


CATALOG_SOURCES: Dict[str, Dict[str, Any]] = {
    DataSource.TICKFLOW: {
        "display_name": "TickFlow",
        "catalog_enabled": True,
        "collection_enabled": True,
    },
    DataSource.LIXINREN: {
        "display_name": "理杏仁",
        "catalog_enabled": True,
        "collection_enabled": True,
    },
}


class AssetCatalogService:
    def list_sources(self) -> dict:
        items = []
        for source_id, config in CATALOG_SOURCES.items():
            last_sync = asset_catalog_dao.get_latest_sync_log(source_id)
            items.append({
                "source_id": source_id,
                "display_name": config["display_name"],
                "catalog_enabled": config["catalog_enabled"],
                "collection_enabled": config["collection_enabled"],
                "last_sync_status": last_sync.get("status"),
                "last_synced_at": last_sync.get("finished_at"),
            })
        return {"items": items}

    def search_catalog(
        self,
        source_id: str,
        keyword: str | None = None,
        asset_type: str | None = None,
        exchange: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        self._ensure_catalog_source(source_id)
        result = asset_catalog_dao.search_catalog(
            source_id=source_id,
            keyword=keyword,
            asset_type=asset_type,
            exchange=exchange,
            page=page,
            page_size=page_size,
        )
        collection_supported = self.is_collection_enabled(source_id)
        for item in result["items"]:
            item["already_added"] = bool(item["already_added"])
            item["collection_supported"] = collection_supported
        return result

    def sync_source(self, source_id: str, force: bool = False) -> dict:
        self._ensure_catalog_source(source_id)
        if not force and self._is_recently_synced(source_id):
            last_sync = asset_catalog_dao.get_latest_sync_log(source_id)
            return {
                "sync_id": last_sync.get("sync_id"),
                "source_id": source_id,
                "status": "skipped",
                "skip_reason": "ttl_not_expired",
                "last_sync": last_sync,
            }

        started_at = self._now()
        sync_id = f"catalog_{source_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        asset_catalog_dao.create_sync_log(sync_id, source_id, started_at)
        try:
            provider = get_catalog_provider(source_id)
            items = provider.fetch_catalog_items()
            sync_time = self._now()
            total_fetched = len(items)
            deactivation_skipped = total_fetched < ASSET_CATALOG_DEACTIVATE_MIN_FETCH_COUNT
            skip_reason = (
                "fetched_count_below_guard_threshold"
                if deactivation_skipped else None
            )
            finished_at = self._now()
            totals = asset_catalog_dao.complete_successful_sync(
                sync_id=sync_id,
                source_id=source_id,
                items=items,
                sync_time=sync_time,
                allow_deactivate=not deactivation_skipped,
                skip_reason=skip_reason,
                finished_at=finished_at,
            )
            return {
                "sync_id": sync_id,
                "source_id": source_id,
                "status": "success",
                "total_fetched": total_fetched,
                "total_upserted": totals["total_upserted"],
                "total_deactivated": totals["total_deactivated"],
                "deactivation_skipped": deactivation_skipped,
                "skip_reason": skip_reason,
                "started_at": started_at,
                "finished_at": finished_at,
            }
        except Exception as exc:
            finished_at = self._now()
            asset_catalog_dao.finish_sync_log(
                sync_id=sync_id,
                status="failed",
                total_fetched=0,
                total_upserted=0,
                total_deactivated=0,
                deactivation_skipped=True,
                skip_reason="sync_failed",
                error_message=str(exc),
                finished_at=finished_at,
            )
            raise

    def get_sync_status(self, source_id: str) -> dict:
        self._ensure_catalog_source(source_id)
        return {
            "source_id": source_id,
            "last_sync": asset_catalog_dao.get_latest_sync_log(source_id) or None,
        }

    def sync_enabled_sources_with_timeout(self) -> dict:
        if not ASSET_CATALOG_SYNC_ENABLED:
            return {"status": "skipped", "reason": "disabled", "items": []}

        def _sync_all() -> list[dict]:
            results = []
            for source_id in CATALOG_SOURCES:
                try:
                    results.append(self.sync_source(source_id))
                except Exception as exc:
                    logger.warning("目录同步失败 source_id=%s err=%s", source_id, exc)
                    results.append({
                        "source_id": source_id,
                        "status": "failed",
                        "error_message": str(exc),
                    })
            return results

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_sync_all)
        try:
            return {"status": "completed", "items": future.result(timeout=ASSET_CATALOG_SYNC_TIMEOUT_SECONDS)}
        except concurrent.futures.TimeoutError:
            logger.warning("目录同步超时，继续执行正式数据采集")
            future.cancel()
            return {"status": "timeout", "items": []}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def is_collection_enabled(source_id: str) -> bool:
        config = CATALOG_SOURCES.get(source_id)
        return bool(config and config["collection_enabled"])

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _ensure_catalog_source(source_id: str) -> None:
        if source_id not in CATALOG_SOURCES:
            raise ValueError(f"不支持的目录来源: {source_id}")
        if not CATALOG_SOURCES[source_id]["catalog_enabled"]:
            raise ValueError(f"目录来源未启用: {source_id}")

    @staticmethod
    def _is_recently_synced(source_id: str) -> bool:
        last_sync = asset_catalog_dao.get_latest_sync_log(source_id)
        if not last_sync or last_sync.get("status") != "success":
            return False
        finished_at = last_sync.get("finished_at")
        if not finished_at:
            return False
        try:
            finished_dt = datetime.strptime(finished_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        return datetime.now() - finished_dt < timedelta(seconds=ASSET_CATALOG_SYNC_TTL_SECONDS)


asset_catalog_service = AssetCatalogService()
