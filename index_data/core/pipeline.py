# 文件: core/pipeline.py
import pandas as pd
from typing import Dict, Optional

from config.constants import DataInterface, DataSource
from core.source_code_normalizer import normalize_daily_bar_source_code
from data_provider import get_data_provider
from data_provider.base import BaseDataProvider
from dao.market_dao import market_dao
from utils.logger import logger
from utils.validators import (validate_asset_code, validate_not_empty,
                               validate_date_range, ValidationError)
from utils.null_handler import handle_market_data_nulls
from utils.exceptions import DataFetchError, DataParseError
from utils.compressor import compress_data


class DataPipeline:
    """
    负责单次 ETL 任务的标准执行流程:
    Extract (Fetch) -> Load (Raw) -> Transform (Parse) -> Load (Std)
    """

    def __init__(self):
        self.adapters = {}

    def _get_adapter(
        self,
        source_id: str,
        exchange: str = 'SH',
        asset_type: str = 'INDEX',
    ):
        source_id = DataSource.validate_asset_route(source_id)
        if source_id == DataSource.LIXINREN:
            try:
                return get_data_provider(
                    source_id,
                    interface_type=DataInterface.DAILY_BAR,
                    exchange=exchange,
                    asset_type=asset_type,
                )
            except Exception as e:
                logger.error(f"无法初始化适配器 [{source_id}]: {e}")
                return None
        if source_id not in self.adapters:
            try:
                self.adapters[source_id] = get_data_provider(source_id)
            except Exception as e:
                logger.error(f"无法初始化适配器 [{source_id}]: {e}")
                return None
        return self.adapters[source_id]

    def run_task(self, asset_code: str, source_id: str, start_date: str,
                 end_date: str, source_code: str = None,
                 exchange: str = 'SH', asset_type: str = 'INDEX') -> Dict[str, object]:
        """
        执行单个标的的更新任务

        :param asset_code: 资产代码
        :param source_id: 数据源 ID
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param source_code: AkShare 等需要的特殊代码格式 (from Router)
        :param exchange: 交易所代码 (from Meta)，用于 Lixinren 路由
        :param asset_type: 资产类型 (INDEX/ETF/STOCK)，用于 Lixinren 路由
        :return: {"status": "success"|"empty"|"failed", "rows": int}
        """
        # 参数校验
        try:
            asset_code = validate_asset_code(asset_code)
            source_id = DataSource.validate_asset_route(
                validate_not_empty(source_id, "source_id")
            )
            start_date, end_date = validate_date_range(start_date, end_date)
        except (ValidationError, ValueError) as e:
            logger.error(f"Pipeline task validation failed: {e}")
            return {"status": "failed", "rows": 0}

        task_id = f"{asset_code}_{end_date}"
        logger.info(
            f"[{source_id}] 启动任务: {asset_code} "
            f"({start_date} -> {end_date})"
        )

        adapter = self._get_adapter(source_id, exchange=exchange, asset_type=asset_type)
        if not adapter:
            return {"status": "failed", "rows": 0}

        effective_source_code = normalize_daily_bar_source_code(
            asset_code=asset_code,
            source_id=source_id,
            asset_type=asset_type,
            source_code=source_code,
        )
        endpoint_label = (
            "cn_index_daily_bar"
            if source_id == DataSource.LIXINREN and asset_type == "INDEX"
            else DataInterface.DAILY_BAR
        )

        # --- Step 1: Extract (Fetch Raw) ---
        raw_data = None
        try:
            # 关键：将 source_code, exchange 和 asset_type 透传给适配器
            raw_data = adapter.fetch_raw(
                asset_code=asset_code, 
                start_date=start_date,
                end_date=end_date,
                source_code=effective_source_code,
                exchange=exchange,
                asset_type=asset_type
            )
            if raw_data is None or (isinstance(raw_data, pd.DataFrame) and raw_data.empty) or (isinstance(raw_data, list) and not raw_data):
                logger.info(
                    f"[{asset_code}] 接口返回空数据 "
                    f"source_id={source_id} source_code={source_code} "
                    f"effective_source_code={effective_source_code} "
                    f"asset_type={asset_type} exchange={exchange} "
                    f"range={start_date}->{end_date} "
                    f"endpoint={endpoint_label}"
                )
                return {"status": "empty", "rows": 0}
        except DataFetchError as e:
            logger.error(f"[{asset_code}] 数据获取失败: {e}")
            market_dao.save_raw_log(task_id, asset_code, source_id, f"{start_date}|{end_date}", b"")
            return {"status": "failed", "rows": 0}
        except Exception as e:
            logger.error(f"[{asset_code}] 获取数据异常: {e}")
            market_dao.save_raw_log(task_id, asset_code, source_id, f"{start_date}|{end_date}", b"")
            raise DataFetchError(f"Unexpected error fetching {asset_code}") from e 


        # --- Step 2: Load Raw (Save to DB) ---
        raw_log_id = 0
        try:
            # 对于 DataFrame，需要转换为可序列化格式
            if isinstance(raw_data, pd.DataFrame):
                raw_data_to_save = raw_data.to_dict('records')
            else:
                raw_data_to_save = raw_data
            
            compressed = compress_data(raw_data_to_save)
            raw_log_id = market_dao.save_raw_log(
                batch_id=task_id, 
                asset_code=asset_code, 
                source_id=source_id, 
                req_params=f"{start_date},{end_date}|{effective_source_code}",
                compressed_payload=compressed
            )
        except Exception as e:
            logger.error(f"[{asset_code}] 保存 Raw Log 失败: {e}")
            return {"status": "failed", "rows": 0}

        # --- Step 3: Transform (Parse) ---
        df_std = pd.DataFrame()
        try:
            df_std = adapter.parse(
                raw_data, start_date=start_date, end_date=end_date
            )
            
            if not df_std.empty:
                # [核心修正] 强制使用系统内部 asset_code
                df_std['asset_code'] = asset_code
                df_std['source_id'] = source_id
                df_std['updated_at'] = pd.Timestamp.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                
                # 确保列顺序与数据库 schema 一致（为批量操作优化准备）
                df_std = df_std[['asset_code', 'trade_date', 'open', 'high',
                                 'low', 'close', 'volume', 'amount',
                                 'source_id', 'updated_at']]
                
                # 使用统一的空值处理策略（替代 fillna(0)）
                try:
                    from utils.null_handler import (handle_market_data_nulls,
                                                    NullHandlingError)
                    df_std = handle_market_data_nulls(df_std)
                except NullHandlingError as e:
                    logger.error(f"[{asset_code}] 空值处理失败: {e}")
                    market_dao.update_raw_status(raw_log_id, -1)
                    return {"status": "failed", "rows": 0}
                
        except Exception as e:
            logger.error(f"[{asset_code}] 解析失败: {e}")
            market_dao.update_raw_status(raw_log_id, -1) 
            return {"status": "failed", "rows": 0}

        # --- Step 4: Load Std (Upsert) ---
        try:
            if not df_std.empty:
                market_dao.upsert_daily_data(df_std)
                logger.info(f"[{asset_code}] 入库成功: {len(df_std)} 条记录")
                rows = len(df_std)
            else:
                logger.info(f"[{asset_code}] 解析后无符合日期的数据")
                rows = 0

            market_dao.update_raw_status(raw_log_id, 1) 
            self._save_adjustment_factor_raw_log(
                adapter=adapter,
                task_id=task_id,
                asset_code=asset_code,
                source_id=source_id,
                source_code=source_code,
                start_date=start_date,
                end_date=end_date,
                exchange=exchange,
                asset_type=asset_type,
            )
            return {"status": "success" if rows > 0 else "empty", "rows": rows}

        except Exception as e:
            logger.error(f"[{asset_code}] 标准数据入库失败: {e}")
            market_dao.update_raw_status(raw_log_id, -1)
            return {"status": "failed", "rows": 0}

    def _save_adjustment_factor_raw_log(
        self,
        adapter: BaseDataProvider,
        task_id: str,
        asset_code: str,
        source_id: str,
        source_code: str | None,
        start_date: str,
        end_date: str,
        exchange: str,
        asset_type: str,
    ) -> None:
        if asset_type != "STOCK":
            return
        fetcher = getattr(adapter, "fetch_adjustment_factors", None)
        if not callable(fetcher):
            return
        try:
            factor_data = fetcher(
                asset_code=asset_code,
                start_date=start_date,
                end_date=end_date,
                source_code=source_code,
                exchange=exchange,
                asset_type=asset_type,
            )
            if isinstance(factor_data, pd.DataFrame):
                factor_payload = factor_data.to_dict("records")
            else:
                factor_payload = factor_data
            log_id = market_dao.save_raw_log(
                batch_id=task_id,
                asset_code=asset_code,
                source_id=source_id,
                req_params=(
                    "adjustment_factor|"
                    f"source_code={source_code or ''}|"
                    f"start={start_date}|end={end_date}"
                ),
                compressed_payload=compress_data(factor_payload),
            )
            status = 1
            if isinstance(factor_payload, dict):
                if factor_payload.get("status") in {"unavailable", "skipped", "failed"}:
                    status = -1
            market_dao.update_raw_status(log_id, status)
        except Exception as exc:
            try:
                log_id = market_dao.save_raw_log(
                    batch_id=task_id,
                    asset_code=asset_code,
                    source_id=source_id,
                    req_params=(
                        "adjustment_factor|"
                        f"source_code={source_code or ''}|"
                        f"start={start_date}|end={end_date}"
                    ),
                    compressed_payload=compress_data({
                        "status": "failed",
                        "reason": str(exc),
                    }),
                )
                market_dao.update_raw_status(log_id, -1)
            except Exception:
                logger.warning(
                    "[%s] 复权因子失败 raw log 写入失败 source_id=%s",
                    asset_code,
                    source_id,
                )
            logger.warning(
                "[%s] 复权因子处理失败 source_id=%s err=%s",
                asset_code,
                source_id,
                exc,
            )

pipeline = DataPipeline()
