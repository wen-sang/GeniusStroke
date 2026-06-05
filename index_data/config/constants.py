"""
项目常量定义
"""


class DataSource:
    """数据源标识"""
    AKSHARE = 'akshare'
    LIXINREN = 'lixinren'
    EFINANCE = 'efinance'
    TICKFLOW = 'tickflow'
    TDX = 'tdx'
    VALID = (AKSHARE, LIXINREN, EFINANCE, TICKFLOW)
    ASSET_ROUTE_VALID = (AKSHARE, LIXINREN, TICKFLOW)
    MARKET_DAILY_SOURCE_VALID = (AKSHARE, LIXINREN, TICKFLOW, TDX)

    @classmethod
    def validate(cls, source_id: str) -> str:
        """校验系统级数据源标识。"""
        if source_id not in cls.VALID:
            raise ValueError(cls._unknown_message(source_id, cls.VALID))
        return source_id

    @classmethod
    def validate_asset_route(cls, source_id: str) -> str:
        """校验资产路由可用的数据源标识。"""
        if source_id not in cls.ASSET_ROUTE_VALID:
            raise ValueError(
                cls._unknown_message(source_id, cls.ASSET_ROUTE_VALID)
            )
        return source_id

    @classmethod
    def validate_market_daily_source(cls, source_id: str) -> str:
        """校验标准行情行可写入的数据来源。"""
        if source_id not in cls.MARKET_DAILY_SOURCE_VALID:
            raise ValueError(
                cls._unknown_message(source_id, cls.MARKET_DAILY_SOURCE_VALID)
            )
        return source_id

    @classmethod
    def _unknown_message(cls, source_id: str, expected: tuple[str, ...]) -> str:
        legacy_source_id = f"{cls.LIXINREN[:5]}g{cls.LIXINREN[5:]}"
        if source_id == legacy_source_id:
            return (
                f"Unknown data source_id: {legacy_source_id}. "
                f"Use {cls.LIXINREN}."
            )
        return (
            f"Unknown data source_id: {source_id}. "
            f"Expected one of: {', '.join(expected)}"
        )


class AssetType:
    """资产类型"""
    INDEX = 'INDEX'
    STOCK = 'STOCK'
    ETF = 'ETF'
    LOF = 'LOF'
    FUND = 'FUND'


class Exchange:
    """合法交易所标识"""
    SH = 'SH'
    SZ = 'SZ'
    HK = 'HK'
    VALID = (SH, SZ, HK)


class DataInterface:
    """数据接口类型"""
    DAILY_BAR = 'daily_bar'
    MARKET = DAILY_BAR
    FUNDAMENTAL = 'fundamental'
    NET_VALUE = 'net_value'
    INDICATOR = 'indicator'

    @classmethod
    def normalize(cls, interface: str | None) -> str | None:
        """统一接口标识，兼容历史 market 命名。"""
        if interface == 'market':
            return cls.DAILY_BAR
        return interface


class TableNames:
    """数据库表名常量"""
    # 数据表
    MARKET_DAILY = 'dat_market_daily'
    FUNDAMENTAL_DAILY = 'dat_fundamental_daily'
    INDICATOR_DAILY = 'dat_indicator_daily'
    RAW_API_LOG = 'dat_raw_api_log'
    
    # 配置表
    ASSET_META = 'sys_asset_meta'
    DATASOURCE = 'sys_datasource'
    ROUTER = 'sys_data_router'
    
    # 辅助表
    CALENDAR = 'trade_calendar'
