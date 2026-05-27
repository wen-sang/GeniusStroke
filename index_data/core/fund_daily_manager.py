# 文件: core/fund_daily_manager.py
import time
import datetime
from typing import List, Dict
from datetime import timedelta

from config.settings import (
    DATA_COLLECTION_DEFAULT_START_DATE,
    FUND_DAILY_MAX_DAYS_PER_REQUEST,
    FUND_DAILY_REQUEST_SLEEP_SECONDS,
    LIXINREN_FUND_INIT_SLEEP,
)
from config.constants import AssetType, DataInterface, DataSource
from data_provider import get_data_provider
from dao.fund_daily_dao import fund_daily_dao
from dao.meta_dao import meta_dao
from core.router import router
from utils.logger import logger


class FundDailyManager:
    """
    基金净值数据调度管理器
    负责从理杏仁获取ETF/基金的净值数据
    """

    def __init__(self):
        self.exchange_map = {}
        self.max_days_per_request = FUND_DAILY_MAX_DAYS_PER_REQUEST

    def run(self, target_date: str) -> Dict[str, object]:
        """
        执行净值数据同步任务
        
        :param target_date: 目标日期 (YYYY-MM-DD)
        """
        logger.info(f"   >>> [Phase 3] 基金净值数据同步...")

        # 1. 获取需要净值数据的资产（ETF类型）
        all_assets = meta_dao.get_active_assets()
        
        # 筛选需要理杏仁净值数据源的资产（通常是 ETF）
        fund_assets = []
        for asset in all_assets:
            code = asset['asset_code']
            asset_type = asset.get('asset_type', 'INDEX')
            
            # 检查路由规则，只处理使用理杏仁净值数据源的资产
            try:
                # [Fix] 指数和股票没有净值概念，直接跳过
                if asset_type in ('INDEX', 'STOCK'):
                    continue

                best_source_id, _ = router.get_best_source(
                    code,
                    asset_type,
                    interface=DataInterface.NET_VALUE,
                )
                best_source_id = DataSource.validate_asset_route(best_source_id)
                if best_source_id == DataSource.LIXINREN:
                    fund_assets.append(asset)
            except Exception as e:
                logger.error(f"   [FundDaily] 路由失败 {code}: {e}")
                continue
        
        if not fund_assets:
            logger.info("   扫描完成: 无需要净值数据的标的，跳过净值更新。")
            return self._build_result(target_date)
        
        self.exchange_map = {
            a['asset_code']: a.get('exchange', 'SH')
            for a in fund_assets
        }
        
        logger.info(f"   发现 {len(fund_assets)} 个基金需要更新净值数据")
        
        # 2. 批量查询最新净值数据日期和最新行情基准日期
        fund_codes = [a['asset_code'] for a in fund_assets]
        last_dates_map = fund_daily_dao.get_last_dates_batch(fund_codes)
        
        from dao.market_dao import market_dao
        market_last_dates_map = market_dao.get_last_dates_batch(fund_codes)
        
        # 3. 构建更新队列
        update_queue = []
        for asset in fund_assets:
            code = asset['asset_code']
            last_date = last_dates_map.get(code)
            market_last_date = market_last_dates_map.get(code)
            
            if last_date:
                # [新增] 净值已更新到最新交易日基准，跳过
                if market_last_date and last_date >= market_last_date:
                    logger.info(f"   -> 跳过 {code}: 净值日期({last_date}) 已对齐最后交易日({market_last_date})")
                    continue
                
                # 增量更新：从最新日期的下一天开始
                start_dt = datetime.datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
                start_date = start_dt.strftime("%Y-%m-%d")
            else:
                # 全量初始化：从上市日期或默认日期开始
                start_date = asset.get('listing_date') or DATA_COLLECTION_DEFAULT_START_DATE
            
            if start_date <= target_date:
                update_queue.append({
                    'code': code,
                    'start_date': start_date,
                    'target_date': target_date,
                    'exchange': self.exchange_map.get(code, 'SH'),
                    'asset_type': asset.get('asset_type', 'ETF')
                })
        
        # 4. 执行更新
        if not update_queue:
            logger.info(f"   扫描完成: 所有标的净值数据均已是最新 ({target_date})，无需更新。")
            return self._build_result(target_date)
        
        logger.info(f"   发现 {len(update_queue)} 个标的需更新净值:")
        
        success_count = 0
        fail_count = 0
        success_codes = set()
        fail_codes = set()
        empty_codes = set()
        
        for i, task in enumerate(update_queue):
            code = task['code']
            s_date = task['start_date']
            t_date = task['target_date']
            asset_type = task.get('asset_type', AssetType.ETF)
            
            progress = f"[{i+1}/{len(update_queue)}]"
            
            try:
                adapter = get_data_provider(
                    DataSource.LIXINREN,
                    interface_type=DataInterface.NET_VALUE,
                    exchange=exchange,
                    asset_type=asset_type,
                )
                
                # 分段拉取（理杏仁限制不超过10年）
                curr_start = datetime.datetime.strptime(s_date, "%Y-%m-%d")
                target_dt = datetime.datetime.strptime(t_date, "%Y-%m-%d")
                
                all_data = []
                
                while curr_start <= target_dt:
                    next_end = curr_start + timedelta(days=self.max_days_per_request)
                    seg_end = min(next_end, target_dt)
                    
                    seg_start_str = curr_start.strftime("%Y-%m-%d")
                    seg_end_str = seg_end.strftime("%Y-%m-%d")
                    
                    try:
                        seg_data = adapter.fetch_fund_daily(
                            stock_code=code,
                            start_date=seg_start_str,
                            end_date=seg_end_str,
                            exchange=exchange
                        )
                        all_data.extend(seg_data)
                        
                        if next_end < target_dt:
                            time.sleep(LIXINREN_FUND_INIT_SLEEP)
                    
                    except Exception as e:
                        logger.error(f"         {progress} {code} Segment ({seg_start_str} -> {seg_end_str}) Fail: {e}")
                    
                    curr_start = seg_end + timedelta(days=1)
                
                # 转换并保存数据
                if all_data:
                    clean_data = self._parse_and_transform(all_data, code, DataSource.LIXINREN)
                    rows_inserted = fund_daily_dao.upsert_batch(clean_data)
                    
                    success_count += 1
                    success_codes.add(code)
                    logger.info(f"      {progress} 更新 {code} ({s_date} -> {t_date}) ... Success ({rows_inserted} rows)")
                else:
                    empty_codes.add(code)
                    logger.warning(f"      {progress} 更新 {code} ({s_date} -> {t_date}) ... No Data")
                
                time.sleep(FUND_DAILY_REQUEST_SLEEP_SECONDS)
                
            except Exception as e:
                fail_count += 1
                fail_codes.add(code)
                logger.error(f"      {progress} 更新 {code} 异常: {e}")
        
        logger.info(f"   -> Phase 3 完成: 成功 {success_count}, 失败 {fail_count}。")
        return self._build_result(
            target_date,
            success_codes=success_codes,
            fail_codes=fail_codes,
            empty_codes=empty_codes,
        )

    def _build_result(
        self,
        target_date: str,
        success_codes=None,
        fail_codes=None,
        empty_codes=None,
    ) -> Dict[str, object]:
        return {
            "target_date": target_date,
            "success_codes": sorted(success_codes or []),
            "failed_codes": sorted(fail_codes or []),
            "empty_codes": sorted(empty_codes or []),
        }

    def _parse_and_transform(self, raw_data: List[Dict], asset_code: str, source_id: str) -> List[Dict]:
        """
        转换净值数据为数据库格式
        
        :param raw_data: [{'date': '2026-01-29', 'unit_nav': 0.7386, 'accum_nav': 1.8398}, ...]
        :param asset_code: 资产代码
        :param source_id: 数据源
        :return: [{'asset_code': '159516', 'trade_date': '2026-01-29', ...}, ...]
        """
        result = []
        for item in raw_data:
            if 'date' not in item:
                continue
            
            result.append({
                'asset_code': asset_code,
                'trade_date': item['date'],
                'unit_nav': item.get('unit_nav'),
                'accum_nav': item.get('accum_nav'),
                'source_id': source_id
            })
        
        return result


# 单例
fund_daily_manager = FundDailyManager()
