"""
理杏仁接口地址集中配置。

说明：
1. 本文件只负责维护 endpoint key -> URL 的静态映射。
2. token 与运行模式不在此文件维护，统一通过 .env 管理。
3. 修改本文件后需重启服务生效。
"""

from typing import Iterable

LIXINREN_ENDPOINT_CN_INDEX_DAILY_BAR = "cn_index_daily_bar"
LIXINREN_ENDPOINT_CN_FUND_DAILY_BAR = "cn_fund_daily_bar"
LIXINREN_ENDPOINT_CN_COMPANY_DAILY_BAR = "cn_company_daily_bar"
LIXINREN_ENDPOINT_CN_COMPANY_FUNDAMENTAL_NON_FINANCIAL = (
    "cn_company_fundamental_non_financial"
)
LIXINREN_ENDPOINT_HK_INDEX_DAILY_BAR = "hk_index_daily_bar"
LIXINREN_ENDPOINT_CN_INDEX_FUNDAMENTAL = "cn_index_fundamental"
LIXINREN_ENDPOINT_HK_INDEX_FUNDAMENTAL = "hk_index_fundamental"
LIXINREN_ENDPOINT_CN_FUND_NET_VALUE = "cn_fund_net_value"
LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE = "cn_fund_total_net_value"

LIXINREN_ENDPOINTS = {
    # 中国区指数日行情接口
    LIXINREN_ENDPOINT_CN_INDEX_DAILY_BAR: "https://open.lixinger.com/api/cn/index/candlestick",
    # 中国区基金/ETF 日行情接口
    LIXINREN_ENDPOINT_CN_FUND_DAILY_BAR: "https://open.lixinger.com/api/cn/fund/candlestick",
    # 中国区股票日行情接口
    LIXINREN_ENDPOINT_CN_COMPANY_DAILY_BAR: "https://open.lixinger.com/api/cn/company/candlestick",
    # 中国区非金融公司基本面接口
    LIXINREN_ENDPOINT_CN_COMPANY_FUNDAMENTAL_NON_FINANCIAL: (
        "https://open.lixinger.com/api/cn/company/fundamental/non_financial"
    ),
    # 香港区指数日行情接口
    LIXINREN_ENDPOINT_HK_INDEX_DAILY_BAR: "https://open.lixinger.com/api/hk/index/candlestick",
    # 中国区指数基本面接口
    LIXINREN_ENDPOINT_CN_INDEX_FUNDAMENTAL: "https://open.lixinger.com/api/cn/index/fundamental",
    # 香港区指数基本面接口
    LIXINREN_ENDPOINT_HK_INDEX_FUNDAMENTAL: "https://open.lixinger.com/api/hk/index/fundamental",
    # 中国区基金单位净值接口
    LIXINREN_ENDPOINT_CN_FUND_NET_VALUE: "https://open.lixinger.com/api/cn/fund/net-value",
    # 中国区基金累计净值接口
    LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE: "https://open.lixinger.com/api/cn/fund/total-net-value",
}


def get_lixinren_endpoint(endpoint_key: str) -> str:
    """读取单个理杏仁 endpoint 配置。"""
    url = str(LIXINREN_ENDPOINTS.get(endpoint_key, "")).strip()
    if not url:
        raise ValueError(f"理杏仁 endpoint 配置缺失或为空: {endpoint_key}")
    return url


def get_lixinren_endpoints(endpoint_keys: Iterable[str]) -> dict[str, str]:
    """按 key 批量读取理杏仁 endpoint 配置。"""
    return {key: get_lixinren_endpoint(key) for key in endpoint_keys}
