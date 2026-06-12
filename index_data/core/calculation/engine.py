# 文件: core/calculation/engine.py
import time
import pandas as pd
import pandas_ta as ta  # noqa: F401 - registers the pandas .ta accessor
import orjson
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from core.db_engine import db_engine
from dao.meta_dao import meta_dao
from dao.indicator_dao import indicator_dao
from core.calculation.loader import config_loader
from utils.logger import get_calc_logger

class CalculationEngine:
    
    def __init__(self):
        self.calc_logger = get_calc_logger()

    def run(
        self,
        target_assets: List[str] = None,
        progress_callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]] = None,
    ):
        """执行计算任务的主入口"""
        start_time = time.time()
        self.calc_logger.info("启动指标计算引擎...")
        self._report_progress(progress_callback, 2, None, "加载指标配置")
        
        configs_map = config_loader.load_all_configs()
        if not configs_map:
            self.calc_logger.warning("未找到任何有效的指标配置，计算任务结束。")
            self._report_progress(progress_callback, 100, "0/0", "未找到有效指标配置")
            return

        if not target_assets:
            assets_dicts = meta_dao.get_active_assets()
            target_assets = [a['asset_code'] for a in assets_dicts]
        
        total = len(target_assets)
        self.calc_logger.info(f"本次待处理标的数量: {total}")
        if total == 0:
            self._report_progress(progress_callback, 100, "0/0", "无待计算标的")
            return

        self._report_progress(progress_callback, 5, f"0/{total}", "准备计算指标")

        global_updated_count = 0 
        
        for i, code in enumerate(target_assets):
            progress_prefix = f"[{i+1}/{total}] {code}"
            try:
                updated_rows = self._process_single_asset(code, configs_map, progress_prefix)
                if updated_rows > 0:
                    global_updated_count += 1
            except Exception as e:
                # 只有计算出错才打印，保持清爽
                self.calc_logger.error(f"{progress_prefix} 处理异常: {e}", exc_info=True)
            finally:
                progress = min(100, 5 + round(((i + 1) / total) * 95))
                self._report_progress(
                    progress_callback,
                    progress,
                    f"{i + 1}/{total}",
                    f"指标计算: {code}",
                )

        elapsed = time.time() - start_time
        
        # 汇总报告
        if global_updated_count == 0:
            self.calc_logger.info("扫描完成: 所有标的指标数据均已是最新，无需更新。")
        else:
            self.calc_logger.info(f"计算任务完成。共更新 {global_updated_count} 个标的指标，总耗时: {elapsed:.2f}s")
        self._report_progress(progress_callback, 100, f"{total}/{total}", "指标计算完成")

    def rebuild_asset_from_date(
        self,
        asset_code: str,
        from_date: str,
    ) -> dict:
        configs_map = config_loader.load_all_configs()
        global_cfgs = configs_map.get("*", [])
        asset_cfgs = configs_map.get(asset_code, [])
        deleted_rows = indicator_dao.delete_asset_from_date(
            asset_code,
            from_date,
        )
        written_rows = self._process_single_asset(
            asset_code,
            configs_map,
            f"[REBUILD] {asset_code}",
            strict=True,
        )
        return {
            "asset_code": asset_code,
            "from_date": from_date,
            "config_count": len(global_cfgs) + len(asset_cfgs),
            "deleted_rows": deleted_rows,
            "written_rows": written_rows,
        }

    def _process_single_asset(
        self,
        asset_code: str,
        configs_map: Dict,
        prefix: str,
        strict: bool = False,
    ) -> int:
        """
        处理单个标的
        :return: 插入的总行数 (0 表示无需更新)
        """
        global_cfgs = configs_map.get('*', [])
        spec_cfgs = configs_map.get(asset_code, [])
        all_cfgs = global_cfgs + spec_cfgs
        
        if not all_cfgs:
            return 0

        df_market = self._read_market_data(asset_code)
        if df_market.empty:
            return 0

        batch_upsert_list = []
        executed_algos = defaultdict(list) 
        total_inserted_count = 0
        has_error = False

        for cfg in all_cfgs:
            algo_name = cfg['algo_name']
            p_vals = [str(v) for v in cfg['params'].values()]
            p_display = "-".join(p_vals) if len(p_vals) > 1 else p_vals[0]
            
            df_calc = df_market.copy()
            period = cfg['time_period']
            
            if period != '1d':
                try:
                    df_calc = self._resample_data(df_calc, period)
                    if df_calc.empty:
                        continue
                except Exception as exc:
                    has_error = True
                    if strict:
                        raise RuntimeError(
                            f"Indicator resample failed: {algo_name}"
                        ) from exc
                    continue

            func_name = cfg['lib_func']
            params = cfg['params']
            
            try:
                if not hasattr(df_calc.ta, func_name):
                    has_error = True
                    if strict:
                        raise RuntimeError(
                            f"Indicator function missing: {func_name}"
                        )
                    continue
                method = getattr(df_calc.ta, func_name)
                result = method(**params)
                if result is None or result.empty:
                    continue
                if isinstance(result, pd.Series):
                    result = result.to_frame()
                executed_algos[algo_name].append(p_display)
            except Exception as exc:
                has_error = True
                if strict:
                    raise RuntimeError(
                        f"Indicator calculation failed: {algo_name}"
                    ) from exc
                continue

            last_db_date = indicator_dao.get_last_indicator_date(asset_code, cfg['config_id'])
            result_dates = result.index.strftime('%Y-%m-%d')
            
            if last_db_date:
                mask = result_dates > last_db_date
                rows_to_save = result[mask]
            else:
                rows_to_save = result


            count = len(rows_to_save)
            if rows_to_save.empty:
                continue

            total_inserted_count += count
            
            # 性能优化：使用向量化操作替代 iterrows
            # 将 NaN 转换为 None，然后一次性转为字典列表
            rows_dict = rows_to_save.where(
                pd.notnull(rows_to_save), None
            ).to_dict('records')
            
            for i, val_dict in enumerate(rows_dict):
                trade_date_str = rows_to_save.index[i].strftime('%Y-%m-%d')
                val_json_str = orjson.dumps(val_dict).decode('utf-8')
                batch_upsert_list.append({
                    'asset_code': asset_code,
                    'trade_date': trade_date_str,
                    'config_id': cfg['config_id'],
                    'val_json': val_json_str
                })

        if batch_upsert_list:
            indicator_dao.upsert_batch(batch_upsert_list)
        
        # 仅当有更新或出错时打印日志
        if total_inserted_count > 0:
            display_parts = []
            for algo, p_list in executed_algos.items():
                try:
                    p_list.sort(key=lambda x: float(x) if x.replace('.','',1).isdigit() else x)
                except Exception:
                    pass
                p_str = ", ".join(p_list)
                display_parts.append(f"{algo}({p_str})")
            
            algo_info_str = " | ".join(display_parts)
            msg = f"{prefix} -> {algo_info_str}, 更新成功 {total_inserted_count} 条"
            self.calc_logger.info(msg)
        
        elif has_error:
            self.calc_logger.warning(f"{prefix} -> 计算完成但部分指标出错，无数据更新")
        
        return total_inserted_count

    def _read_market_data(self, asset_code: str) -> pd.DataFrame:
        sql = "SELECT trade_date, open, high, low, close, volume FROM dat_market_daily WHERE asset_code = ? ORDER BY trade_date ASC"
        try:
            with db_engine.get_connection(readonly=True) as conn:
                df = pd.read_sql(sql, conn, params=(asset_code,),
                                 parse_dates=['trade_date'])
            if not df.empty:
                df.set_index('trade_date', inplace=True)
            return df
        except Exception as e:
            self.calc_logger.error(f"Read market data failed ({asset_code}): {e}")
            return pd.DataFrame()

    def _resample_data(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        rule = period
        if period == '1w':
            rule = 'W-FRI'
        elif period == '1m':
            rule = 'M'
        agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        df_res = df.resample(rule, closed='right', label='right').agg(agg_dict)
        df_res.dropna(inplace=True)
        return df_res

    @staticmethod
    def _report_progress(
        callback: Optional[Callable[[Optional[int], Optional[str], Optional[str]], None]],
        progress: Optional[int],
        sub_progress: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        if callback:
            callback(progress, sub_progress, detail)

calc_engine = CalculationEngine()
