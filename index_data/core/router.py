import threading

from config.constants import DataInterface
from dao.meta_dao import meta_dao
from utils.logger import logger

class DataRouter:
    def __init__(self):
        self._rules_cache = []
        self._lock = threading.RLock()
        self.reload_rules()

    def reload_rules(self):
        """从数据库加载最新的路由规则"""
        rules = meta_dao.get_router_rules()
        with self._lock:
            self._rules_cache = rules
        logger.info(f"路由规则已加载，共 {len(rules)} 条")

    def _get_rules_snapshot(self):
        """返回当前缓存快照，避免遍历过程中受刷新影响。"""
        with self._lock:
            return tuple(self._rules_cache)

    def get_best_source(self, asset_code: str, asset_type: str, interface: str) -> tuple:
        """
        核心路由算法
        :return: (source_id, source_code) 
                 source_code 可能为 None (使用默认 asset_code) 或特定字符串 (如 csi931994)
        """
        normalized_interface = DataInterface.normalize(interface)
        if not normalized_interface:
            raise ValueError("route interface is required")
        for rule in self._get_rules_snapshot():
            # 接口类型必须匹配
            if DataInterface.normalize(rule['interface']) != normalized_interface:
                continue
            
            # A. 规则指定了 asset_code -> 必须完全匹配
            if rule['asset_code'] and rule['asset_code'] == asset_code:
                return rule['source_id'], rule.get('source_code')
            
            # B. 规则仅指定了 asset_type -> 匹配类型
            if not rule['asset_code'] and rule['asset_type'] and rule['asset_type'] == asset_type:
                return rule['source_id'], rule.get('source_code')
                
        # 兜底
        error_msg = (
            f"No route rule found for {asset_code} ({asset_type}) "
            f"interface={normalized_interface}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

router = DataRouter()
