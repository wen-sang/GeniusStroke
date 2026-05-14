# 文件: core/calculation/loader.py
import orjson
from collections import defaultdict
from typing import Dict, List, Any

from core.db_engine import db_engine
from utils.logger import logger

class ConfigLoader:
    """
    负责从数据库加载指标配置，并组装成 {target: [configs]} 的映射结构
    """

    def load_all_configs(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        加载所有有效的指标配置
        :return: {
            '*': [ {config_id:1, func:'sma', params:{...}, period:'1d'}, ... ],
            '000001': [ ... ]
        }
        """
        # 关联查询: Scope -> Config -> Meta
        # 结果集包含: scope_target, config_id, time_period, params_json, lib_func
        sql = """
        SELECT 
            s.apply_target,
            c.config_id,
            c.time_period,
            c.params_json,
            m.lib_func,
            m.algo_name
        FROM sys_algo_scope s
        JOIN sys_algo_config c ON s.config_id = c.config_id
        JOIN sys_algo_meta m ON c.algo_id = m.algo_id
        WHERE s.is_enabled = 1
        """

        config_map = defaultdict(list)
        
        try:
            with db_engine.get_connection(readonly=True) as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                rows = cursor.fetchall()
                
                for row in rows:
                    target, cfg_id, period, params_str, func, name = row
                    
                    try:
                        params = orjson.loads(params_str)
                    except Exception:
                        logger.warning(f"Config {cfg_id} params invalid JSON, skipped.")
                        continue

                    cfg_obj = {
                        'config_id': cfg_id,
                        'algo_name': name,
                        'lib_func': func,       # e.g., 'sma'
                        'time_period': period,  # e.g., '1d'
                        'params': params        # dict
                    }
                    
                    config_map[target].append(cfg_obj)

            logger.info(f"配置加载完成: 全局配置数={len(config_map.get('*', []))}, 个股特殊配置数={len(config_map) - (1 if '*' in config_map else 0)}")
            return config_map

        except Exception as e:
            logger.error(f"Load configs failed: {e}")
            return {}

# 单例
config_loader = ConfigLoader()
