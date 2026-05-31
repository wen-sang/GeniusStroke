from dataclasses import dataclass

from config.constants import AssetType, DataInterface
from config.lixinren_endpoints import (
    LIXINREN_ENDPOINT_CN_FUND_DAILY_BAR,
    LIXINREN_ENDPOINT_CN_FUND_NET_VALUE,
    LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE,
    LIXINREN_ENDPOINT_CN_INDEX_DAILY_BAR,
    LIXINREN_ENDPOINT_CN_INDEX_FUNDAMENTAL,
    LIXINREN_ENDPOINT_HK_INDEX_DAILY_BAR,
    LIXINREN_ENDPOINT_HK_INDEX_FUNDAMENTAL,
)
from config.settings import (
    get_lixinren_mode,
    get_lixinren_token_by_slot,
    get_lixinren_token_slot_name,
)


@dataclass(frozen=True)
class LixinrenRouteResolution:
    mode: str
    interface_type: str
    token_slot_name: str
    token_value: str
    endpoint_keys: list[str]


def _resolve_endpoint_keys(
    interface_type: str,
    exchange: str | None,
    asset_type: str | None,
) -> list[str]:
    normalized_exchange = (exchange or "SH").upper()
    normalized_asset_type = (asset_type or AssetType.INDEX).upper()

    if interface_type == DataInterface.DAILY_BAR:
        if normalized_exchange == "HK":
            return [LIXINREN_ENDPOINT_HK_INDEX_DAILY_BAR]
        if normalized_asset_type in (AssetType.ETF, AssetType.LOF):
            return [LIXINREN_ENDPOINT_CN_FUND_DAILY_BAR]
        return [LIXINREN_ENDPOINT_CN_INDEX_DAILY_BAR]

    if interface_type == DataInterface.FUNDAMENTAL:
        if normalized_exchange == "HK":
            return [LIXINREN_ENDPOINT_HK_INDEX_FUNDAMENTAL]
        return [LIXINREN_ENDPOINT_CN_INDEX_FUNDAMENTAL]

    if interface_type == DataInterface.NET_VALUE:
        return [
            LIXINREN_ENDPOINT_CN_FUND_NET_VALUE,
            LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE,
        ]

    raise ValueError(f"未知的理杏仁接口类型: {interface_type}")


def resolve_lixinren_route(
    interface_type: str,
    exchange: str | None = None,
    asset_type: str | None = None,
) -> LixinrenRouteResolution:
    """解析理杏仁接口级 token 与 endpoint 路由。"""
    mode = get_lixinren_mode()
    token_slot_name = get_lixinren_token_slot_name(interface_type, mode=mode)
    token_value = get_lixinren_token_by_slot(token_slot_name, required=True)
    endpoint_keys = _resolve_endpoint_keys(interface_type, exchange, asset_type)
    return LixinrenRouteResolution(
        mode=mode,
        interface_type=interface_type,
        token_slot_name=token_slot_name,
        token_value=token_value,
        endpoint_keys=endpoint_keys,
    )
