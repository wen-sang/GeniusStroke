# core/fundamental/manager.py
import time
import orjson
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict

from config.settings import (
    FUNDAMENTAL_BATCH_CHUNK_SIZE,
    FUNDAMENTAL_BATCH_MODE_THRESHOLD_DAYS,
    FUNDAMENTAL_DEFAULT_START_DATE,
    FUNDAMENTAL_RANGE_STEP_DAYS,
    LIXINREN_FUND_BATCH_SLEEP,
    LIXINREN_FUND_INIT_SLEEP,
)
from config.constants import AssetType, DataInterface, DataSource
from data_provider import get_data_provider
from dao.fundamental_dao import fundamental_dao
from dao.meta_dao import meta_dao
from core.router import router
from config.fundamental_map import METRICS_MAPPING, REQUIRED_METRICS_LIST
from utils.logger import logger


class FundamentalManager:
    """
    基本面数据调度管理器 (v2.2 Final UX)
    包含: 数据源熔断检查、智能策略切换、极简日志
    """

    def __init__(self):
        self.exchange_map = {}

    def run(self, target_date: str):
        # 这里的日志可以保留，作为阶段开始的标记
        # logger.info(f"🚀 [Fundamental] 启动基本面同步，目标日期: {target_date}")

        assets = meta_dao.get_active_assets()
        if not assets:
            logger.warning("   [Fundamental] 无在市标的，任务结束。")
            return

        self.exchange_map = {
            a['asset_code']: a.get('exchange', 'SH')
            for a in assets
        }

        init_list = []
        batch_map = defaultdict(list)

        # 1.扫描与分类
        # 先筛选需要 lixinren 数据源的资产
        lixinren_assets = []
        for asset in assets:
            code = asset['asset_code']
            asset_type = asset.get('asset_type', 'INDEX')

            # [新增] 过滤 ETF 标的，因为理杏仁基本面接口不支持
            if asset_type == 'ETF':
                continue

            # [数据源熔断] 非 lixinren 数据源直接跳过
            try:
                best_source_id, _ = router.get_best_source(
                    code,
                    asset_type,
                    interface=DataInterface.FUNDAMENTAL,
                )
            except Exception as e:
                logger.error(f"   [Fundamental] 路由失败 {code}: {e}")
                continue

            try:
                best_source_id = DataSource.validate_asset_route(best_source_id)
            except ValueError as e:
                logger.error(f"   [Fundamental] 路由失败 {code}: {e}")
                continue

            if best_source_id == DataSource.LIXINREN:
                lixinren_assets.append(asset)

        if not lixinren_assets:
            logger.info(
                "   扫描完成: 无需要 lixinren 数据源的标的，跳过基本面更新。"
            )
            return

        # 性能优化：批量查询所有资产的最新基本面数据日期
        lixinren_codes = [a['asset_code'] for a in lixinren_assets]
        last_dates_map = fundamental_dao.get_last_update_dates_batch(
            lixinren_codes
        )

        # 2. 根据查询结果分类资产
        for asset in lixinren_assets:
            code = asset['asset_code']
            last_date = last_dates_map.get(code)

            if not last_date:
                init_list.append(asset)
                continue

            if last_date < target_date:
                start_dt = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
                end_dt = datetime.strptime(target_date, "%Y-%m-%d")
                delta_days = (end_dt - start_dt).days + 1

                # [智能切换] 缺失超过阈值 -> Range Mode，否则 -> Batch Mode
                if delta_days > FUNDAMENTAL_BATCH_MODE_THRESHOLD_DAYS:
                    asset_copy = asset.copy()
                    asset_copy['custom_start_date'] = start_dt.strftime("%Y-%m-%d")
                    init_list.append(asset_copy)
                else:
                    curr = start_dt
                    missing = []
                    while curr <= end_dt:
                        missing.append(curr.strftime("%Y-%m-%d"))
                        curr += timedelta(days=1)

                    if missing:
                        batch_map[code] = missing

        # 2. 根据扫描结果打印日志
        if not init_list and not batch_map:
            logger.info(f"   扫描完成: 所有标的基本面数据均已是最新 ({target_date})，无需更新。")
        else:
            if init_list:
                logger.info(f"   [Init/Range Mode] 发现 {len(init_list)} 个标的需范围更新:")
                self._process_init_mode(init_list, target_date)

            if batch_map:
                logger.info(f"   [Batch Mode] 发现 {len(batch_map)} 个标的需增量更新:")
                self._process_batch_mode(batch_map)

        # logger.info("✅ [Fundamental] 所有同步任务完成。")

    def _process_init_mode(self, asset_list: List[Dict], target_date: str):
        total = len(asset_list)
        for i, asset in enumerate(asset_list):
            code = asset['asset_code']
            exchange = self.exchange_map.get(code, 'SH')
            start_date = (asset.get('custom_start_date') or 
                          asset.get('listing_date') or 
                          FUNDAMENTAL_DEFAULT_START_DATE)
            source_id = DataSource.LIXINREN
            asset_type = asset.get('asset_type', AssetType.INDEX)

            try:
                adapter = get_data_provider(
                    source_id,
                    interface_type=DataInterface.FUNDAMENTAL,
                    exchange=exchange,
                    asset_type=asset_type,
                )
                # 打印简洁进度
                logger.info(f"      -> [{i + 1}/{total}] {code} (Exch:{exchange}) 范围更新 ({start_date} -> {target_date})")

                curr_start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                target_dt = datetime.strptime(target_date, "%Y-%m-%d")

                while curr_start_dt <= target_dt:
                    next_hop = curr_start_dt + timedelta(days=FUNDAMENTAL_RANGE_STEP_DAYS)
                    curr_end_dt = min(next_hop, target_dt)
                    s_str = curr_start_dt.strftime("%Y-%m-%d")
                    e_str = curr_end_dt.strftime("%Y-%m-%d")

                    try:
                        raw_list = adapter.fetch_fundamental(
                            stock_codes=[code],
                            metrics_list=REQUIRED_METRICS_LIST,
                            start_date=s_str,
                            end_date=e_str,
                            exchange=exchange
                        )

                        if raw_list:
                            clean_data = self._parse_and_transform(raw_list, source_id)
                            fundamental_dao.upsert_batch(clean_data)
                            logger.info(f"         Upsert Success: {len(clean_data)} rows ({s_str} -> {e_str})")
                        else:
                            # 空数据在控制台通常不需要刷屏，除非是为了调试
                            pass

                        time.sleep(LIXINREN_FUND_INIT_SLEEP)  # 使用配置参数

                    except Exception as e:
                        logger.error(f"         [Fund-Init] {code} Segment Fail: {e}")

                    curr_start_dt = curr_end_dt + timedelta(days=1)
            except Exception as e:
                logger.error(f"       [Fund-Init] Adapter Fail: {e}")

    def _process_batch_mode(self, batch_map: Dict[str, List[str]]):
        date_assets_map = defaultdict(list)
        for code, dates in batch_map.items():
            for d in dates:
                date_assets_map[d].append(code)

        sorted_dates = sorted(date_assets_map.keys())
        source_id = DataSource.LIXINREN

        for d in sorted_dates:
            codes_in_date = date_assets_map[d]
            groups = defaultdict(list)
            for code in codes_in_date:
                exch = self.exchange_map.get(code, 'SH')
                groups[exch].append(code)

            for exchange, code_list in groups.items():
                try:
                    adapter = get_data_provider(
                        source_id,
                        interface_type=DataInterface.FUNDAMENTAL,
                        exchange=exchange,
                        asset_type=AssetType.INDEX,
                    )
                    preview = ",".join(code_list[:3])
                    if len(code_list) > 3: preview += "..."

                    # 打印简洁的 Batch 日志
                    logger.info(f"      -> 日期: {d} | Exch: {exchange} | 数量: {len(code_list)} | Codes: {preview}")

                    chunk_size = FUNDAMENTAL_BATCH_CHUNK_SIZE
                    for i in range(0, len(code_list), chunk_size):
                        sub_codes = code_list[i:i + chunk_size]

                        raw_list = adapter.fetch_fundamental(
                            stock_codes=sub_codes,
                            metrics_list=REQUIRED_METRICS_LIST,
                            date=d,
                            exchange=exchange
                        )

                        if raw_list:
                            clean_data = self._parse_and_transform(raw_list, source_id)
                            fundamental_dao.upsert_batch(clean_data)
                            logger.info(f"         Upsert: {len(clean_data)} rows")

                        time.sleep(LIXINREN_FUND_BATCH_SLEEP)  # 使用配置参数
                except Exception as e:
                    logger.error(f"         [Fund-Batch] {d} Failed: {e}")

    def _parse_and_transform(self, raw_list: List[Dict], source_id: str) -> List[Dict]:
        result = []
        mapped_api_keys = set(METRICS_MAPPING.values())
        for item in raw_list:
            if 'stockCode' not in item or 'date' not in item:
                continue
            internal_code = item['stockCode']
            row = {
                'asset_code': internal_code,
                'trade_date': item['date'][:10],
                'source_id': source_id
            }
            for db_col, api_key in METRICS_MAPPING.items():
                val = item.get(api_key)
                row[db_col] = val
            stats_subset = {}
            for k, v in item.items():
                if k in ['stockCode', 'date']: continue
                if k in mapped_api_keys: continue
                stats_subset[k] = v
            if stats_subset:
                row['full_stats_json'] = orjson.dumps(stats_subset).decode('utf-8')
            result.append(row)
        return result


# 单例
fundamental_manager = FundamentalManager()
