# data_provider/__init__.py
from config.constants import DataSource
from config.lixinren_endpoints import get_lixinren_endpoints
from .akshare_adapter import AkShareAdapter
from .lixinren_adapter import LixinrenAdapter
from .lixinren_resolver import resolve_lixinren_route
from .efinance_adapter import EfinanceAdapter, efinance_adapter

# 1. 注册适配器类
# 注意：lixinren_hk 及其逻辑已合并入 lixinren，通过 exchange 参数区分
ADAPTER_REGISTRY = {
    DataSource.AKSHARE: AkShareAdapter,
    DataSource.LIXINREN: LixinrenAdapter,
    DataSource.EFINANCE: EfinanceAdapter,  # v2.4.5 新增
}

_LIXINREN_ADAPTER_CACHE = {}


def clear_data_provider_cache() -> None:
    """清空 provider 缓存，便于测试和显式刷新。"""
    _LIXINREN_ADAPTER_CACHE.clear()


def get_data_provider(
    source_id: str,
    *,
    interface_type: str | None = None,
    exchange: str | None = None,
    asset_type: str | None = None,
):
    """
    工厂模式：根据 source_id 实例化对应的数据适配器
    """
    source_id = DataSource.validate(source_id)
    adapter_cls = ADAPTER_REGISTRY.get(source_id)
    
    if not adapter_cls:
        raise ValueError(f"Unknown data source_id: {source_id}")
    
    # 2. 根据不同类，注入不同的依赖参数
    if source_id == DataSource.LIXINREN:
        if not interface_type:
            raise ValueError("source_id=lixinren 时必须显式传入 interface_type")
        resolution = resolve_lixinren_route(
            interface_type=interface_type,
            exchange=exchange,
            asset_type=asset_type,
        )
        cache_key = (
            source_id,
            resolution.interface_type,
            resolution.token_slot_name,
            tuple(resolution.endpoint_keys),
        )
        if cache_key not in _LIXINREN_ADAPTER_CACHE:
            _LIXINREN_ADAPTER_CACHE[cache_key] = adapter_cls(
                token=resolution.token_value,
                interface_type=resolution.interface_type,
                token_slot_name=resolution.token_slot_name,
                endpoint_urls=get_lixinren_endpoints(resolution.endpoint_keys),
                endpoint_keys=resolution.endpoint_keys,
                mode=resolution.mode,
            )
        return _LIXINREN_ADAPTER_CACHE[cache_key]

    # AkShare / efinance 等不需要 Token
    return adapter_cls()

# 导出 efinance 单例以便直接使用
__all__ = [
    'AkShareAdapter', 'LixinrenAdapter', 'EfinanceAdapter',
    'efinance_adapter', 'get_data_provider', 'clear_data_provider_cache',
    'ADAPTER_REGISTRY'
]
