"""
类型定义模块

定义项目中常用的类型别名和TypedDict，提升类型安全性和IDE支持。
"""
from typing import TypedDict, Dict, List, Any, Optional


# ==============================================================================
# 资产元数据类型
# ==============================================================================

class AssetMeta(TypedDict):
    """资产元数据字典类型"""
    asset_code: str
    asset_name: str
    asset_type: str
    exchange: Optional[str]
    listing_date: Optional[str]
    is_active: int


# ==============================================================================
# 路由规则类型
# ==============================================================================

class RouterRule(TypedDict):
    """路由规则字典类型"""
    rule_id: int
    asset_code: Optional[str]
    asset_type: Optional[str]
    interface: Optional[str]
    source_id: str
    source_code: Optional[str]
    priority: int


# ==============================================================================
# 指标配置类型
# ==============================================================================

class IndicatorConfig(TypedDict):
    """指标配置字典类型"""
    config_id: int
    asset_code: Optional[str]
    indicator_name: str
    params_json: str
    period: Optional[str]
    is_active: int


# ==============================================================================
# 通用类型别名
# ==============================================================================

# 数据源配置字典
DataSourceConfig = Dict[str, Any]

# 行情数据字典
MarketDataDict = Dict[str, Any]

# 基本面数据字典
FundamentalDataDict = Dict[str, Any]

# 指标数据字典
IndicatorDataDict = Dict[str, Any]
