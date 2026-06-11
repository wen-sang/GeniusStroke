# 文件: config/settings.py
import os
import pathlib
from dotenv import load_dotenv

from config.constants import DataInterface

# 加载环境变量
load_dotenv()


def _get_bool_env(name: str, default: bool) -> bool:
    """读取布尔环境变量，未设置时返回默认值。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_stripped_env(name: str, default: str = "") -> str:
    """读取字符串环境变量并去除首尾空白。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()

# ==============================================================================
# 1. 路径配置 (支持环境变量)
# ==============================================================================
# 锚点定位: 当前文件在 config/settings.py
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

# 从环境变量读取路径（如果未设置，使用默认值）
DATA_DIR = pathlib.Path(os.getenv('DATA_DIR', str(PROJECT_ROOT / "data")))
LOG_DIR = pathlib.Path(os.getenv('LOG_DIR', str(PROJECT_ROOT / "logs")))

# 数据库路径
DB_NAME = os.getenv('DB_NAME', "GeniusStroke_v2.db")
DB_PATH = DATA_DIR / DB_NAME

# 旧数据库路径 (用于迁移参考)
DB_V1_PATH = DATA_DIR / "GeniusStroke.db"

# [关键] 自动创建目录
# 确保项目拷贝到新环境后，即使 logs 文件夹丢失也能自动重建，防止报错
for directory in [DATA_DIR, LOG_DIR]:
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# 2. 环境配置
# ==============================================================================
ENV = os.getenv('ENV', 'development')
APP_NAME = os.getenv('APP_NAME', 'GeniusStroke')
VERSION = os.getenv('VERSION', '2.15.3').strip()
DB_AUTO_SCHEMA = _get_bool_env('DB_AUTO_SCHEMA', ENV == 'development')

# 服务器配置
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '8001'))
RELOAD = os.getenv('RELOAD', 'true').lower() == 'true'
DASHBOARD_URL = os.getenv('DASHBOARD_URL', f'http://localhost:{PORT}')
ENABLE_IMPORT_REBUILD_API = _get_bool_env('ENABLE_IMPORT_REBUILD_API', ENV == 'development')
ENABLE_DATA_SYNC_API = _get_bool_env('ENABLE_DATA_SYNC_API', False)
MANAGEMENT_API_TOKEN = os.getenv('MANAGEMENT_API_TOKEN', '').strip()

# 日志配置
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')

# ==============================================================================
# 3. 业务逻辑配置常量
# ==============================================================================
# 基本面数据同步配置
FUNDAMENTAL_BATCH_MODE_THRESHOLD_DAYS = 5  # 批量模式vs范围模式的阈值（天）
FUNDAMENTAL_RANGE_STEP_DAYS = 3000         # 范围模式每次拉取天数
FUNDAMENTAL_BATCH_CHUNK_SIZE = 100         # 批量模式每批数量
DATA_COLLECTION_DEFAULT_START_DATE = '2005-01-01'  # 行情/净值/基本面默认起始日期
FUNDAMENTAL_DEFAULT_START_DATE = DATA_COLLECTION_DEFAULT_START_DATE
TRADE_CALENDAR_START_YEAR = '2005'

# 交易日历更新配置
CALENDAR_UPDATE_THRESHOLD_DAYS = 5         # 日历过旧阈值（天）

# 数据采集配置
DEFAULT_SLEEP_INTERVAL = 2               # 默认API调用间隔（秒）
ASSET_CATALOG_SYNC_ENABLED = _get_bool_env('ASSET_CATALOG_SYNC_ENABLED', False)
ASSET_CATALOG_SYNC_TTL_SECONDS = int(os.getenv('ASSET_CATALOG_SYNC_TTL_SECONDS', '86400'))
ASSET_CATALOG_SYNC_TIMEOUT_SECONDS = int(os.getenv('ASSET_CATALOG_SYNC_TIMEOUT_SECONDS', '10'))
ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS = int(os.getenv('ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS', '60'))
ASSET_CATALOG_DEACTIVATE_MIN_FETCH_COUNT = int(os.getenv('ASSET_CATALOG_DEACTIVATE_MIN_FETCH_COUNT', '20'))

# ==============================================================================
# 4. 其他配置
# ==============================================================================
# 计算层独立日志文件名
CALC_LOG_NAME = "calculation.log"

# 爬虫策略配置
MARKET_CLOSE_HOUR = 17
SLEEP_MIN = 10
SLEEP_MAX = 30
MARKET_UPDATE_NON_AKSHARE_SLEEP_SECONDS = 0.5
MARKET_UPDATE_ERROR_SLEEP_SECONDS = 1
MAX_RETRIES = 3

# 数据库配置
DB_TIMEOUT = 30  # SQLite 等待锁的超时时间 (秒)

# API Token 配置
# 敏感凭据只允许通过环境变量注入，不允许代码内置默认值
LIXINREN_MODE_GLOBAL = "global"
LIXINREN_MODE_PERSONALIZED = "personalized"
LIXINREN_MODE = _get_stripped_env("LIXINREN_MODE", LIXINREN_MODE_GLOBAL).lower()
LIXINREN_TOKEN = _get_stripped_env("LIXINREN_TOKEN")
LIXINREN_TOKEN_DAILY_BAR = _get_stripped_env("LIXINREN_TOKEN_DAILY_BAR")
LIXINREN_TOKEN_FUNDAMENTAL = _get_stripped_env("LIXINREN_TOKEN_FUNDAMENTAL")
LIXINREN_TOKEN_NET_VALUE = _get_stripped_env("LIXINREN_TOKEN_NET_VALUE")
LIXINREN_TIMEOUT = 60


def get_lixinren_mode() -> str:
    """读取理杏仁运行模式，未配置时默认 global。"""
    mode = _get_stripped_env("LIXINREN_MODE", LIXINREN_MODE_GLOBAL).lower()
    if not mode:
        return LIXINREN_MODE_GLOBAL
    if mode not in {LIXINREN_MODE_GLOBAL, LIXINREN_MODE_PERSONALIZED}:
        raise ValueError(
            "LIXINREN_MODE 配置非法，仅允许 global 或 personalized"
        )
    return mode


def get_lixinren_token_slot_name(interface_type: str, mode: str | None = None) -> str:
    """根据运行模式与逻辑接口类型解析 token 配置槽位名称。"""
    resolved_mode = mode or get_lixinren_mode()
    if resolved_mode == LIXINREN_MODE_GLOBAL:
        return "LIXINREN_TOKEN"

    mapping = {
        DataInterface.DAILY_BAR: "LIXINREN_TOKEN_DAILY_BAR",
        DataInterface.FUNDAMENTAL: "LIXINREN_TOKEN_FUNDAMENTAL",
        DataInterface.NET_VALUE: "LIXINREN_TOKEN_NET_VALUE",
    }
    slot_name = mapping.get(interface_type)
    if not slot_name:
        raise ValueError(f"未知的理杏仁接口类型: {interface_type}")
    return slot_name


def get_lixinren_token_by_slot(slot_name: str, required: bool = False) -> str:
    """按槽位名称读取理杏仁 token。"""
    token = _get_stripped_env(slot_name)
    if required and not token:
        raise ValueError(f"{slot_name} 未配置，无法初始化理杏仁数据源")
    return token


def get_lixinren_token(required: bool = False) -> str:
    """兼容旧逻辑：读取全局理杏仁 Token。"""
    return get_lixinren_token_by_slot("LIXINREN_TOKEN", required=required)

# ==============================================================================
# 5. 理杏仁流控配置 (Time Sleep Settings)
# ==============================================================================
# K线分页拉取时的间隔 (秒)
LIXINREN_KLINE_PAGE_SLEEP = 5

# 基本面初始化模式 (Init Mode) 每个时间段处理后的间隔 (秒)
LIXINREN_FUND_INIT_SLEEP = 6

# 基本面增量模式 (Batch Mode) 每批次(100个)处理后的间隔 (秒)
LIXINREN_FUND_BATCH_SLEEP = 3

# 基金净值分页拉取配置
FUND_DAILY_MAX_DAYS_PER_REQUEST = 3650
FUND_DAILY_REQUEST_SLEEP_SECONDS = 1

# 接口请求失败重试等待时间 (秒)
LIXINREN_RETRY_WAIT = 60

# ==============================================================================
# 6. efinance 实时行情配置
# ==============================================================================
# 行情缓存刷新 TTL (秒)
EFINANCE_REFRESH_TTL_SECONDS = 600

# 保留旧配置名兼容历史调用
EFINANCE_POLL_INTERVAL = EFINANCE_REFRESH_TTL_SECONDS

# 最大重试次数
EFINANCE_MAX_RETRY = 2

# 单次请求最大代码数
EFINANCE_MAX_CODES_PER_REQUEST = 50

# ==============================================================================
DB_AUTO_SCHEMA = _get_bool_env('DB_AUTO_SCHEMA', ENV == 'development')

# 服务器配置
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '8001'))
RELOAD = os.getenv('RELOAD', 'true').lower() == 'true'
DASHBOARD_URL = os.getenv('DASHBOARD_URL', f'http://localhost:{PORT}')
ENABLE_IMPORT_REBUILD_API = _get_bool_env('ENABLE_IMPORT_REBUILD_API', ENV == 'development')
ENABLE_DATA_SYNC_API = _get_bool_env('ENABLE_DATA_SYNC_API', False)
MANAGEMENT_API_TOKEN = os.getenv('MANAGEMENT_API_TOKEN', '').strip()

# 日志配置
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')

# ==============================================================================
# 3. 业务逻辑配置常量
# ==============================================================================
# 基本面数据同步配置
FUNDAMENTAL_BATCH_MODE_THRESHOLD_DAYS = 5  # 批量模式vs范围模式的阈值（天）
FUNDAMENTAL_RANGE_STEP_DAYS = 3000         # 范围模式每次拉取天数
FUNDAMENTAL_BATCH_CHUNK_SIZE = 100         # 批量模式每批数量
DATA_COLLECTION_DEFAULT_START_DATE = '2005-01-01'  # 行情/净值/基本面默认起始日期
FUNDAMENTAL_DEFAULT_START_DATE = DATA_COLLECTION_DEFAULT_START_DATE
TRADE_CALENDAR_START_YEAR = '2005'

# 交易日历更新配置
CALENDAR_UPDATE_THRESHOLD_DAYS = 5         # 日历过旧阈值（天）

# 数据采集配置
DEFAULT_SLEEP_INTERVAL = 2               # 默认API调用间隔（秒）
ASSET_CATALOG_SYNC_ENABLED = _get_bool_env('ASSET_CATALOG_SYNC_ENABLED', False)
ASSET_CATALOG_SYNC_TTL_SECONDS = int(os.getenv('ASSET_CATALOG_SYNC_TTL_SECONDS', '86400'))
ASSET_CATALOG_SYNC_TIMEOUT_SECONDS = int(os.getenv('ASSET_CATALOG_SYNC_TIMEOUT_SECONDS', '10'))
ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS = int(os.getenv('ASSET_CATALOG_REQUEST_TIMEOUT_SECONDS', '60'))
ASSET_CATALOG_DEACTIVATE_MIN_FETCH_COUNT = int(os.getenv('ASSET_CATALOG_DEACTIVATE_MIN_FETCH_COUNT', '20'))

# ==============================================================================
# 4. 其他配置
# ==============================================================================
# 计算层独立日志文件名
CALC_LOG_NAME = "calculation.log"

# 爬虫策略配置
MARKET_CLOSE_HOUR = 17
SLEEP_MIN = 10
SLEEP_MAX = 30
MARKET_UPDATE_NON_AKSHARE_SLEEP_SECONDS = 0.5
MARKET_UPDATE_ERROR_SLEEP_SECONDS = 1
MAX_RETRIES = 3

# 数据库配置
DB_TIMEOUT = 30  # SQLite 等待锁的超时时间 (秒)

# API Token 配置
# 敏感凭据只允许通过环境变量注入，不允许代码内置默认值
LIXINREN_MODE_GLOBAL = "global"
LIXINREN_MODE_PERSONALIZED = "personalized"
LIXINREN_MODE = _get_stripped_env("LIXINREN_MODE", LIXINREN_MODE_GLOBAL).lower()
LIXINREN_TOKEN = _get_stripped_env("LIXINREN_TOKEN")
LIXINREN_TOKEN_DAILY_BAR = _get_stripped_env("LIXINREN_TOKEN_DAILY_BAR")
LIXINREN_TOKEN_FUNDAMENTAL = _get_stripped_env("LIXINREN_TOKEN_FUNDAMENTAL")
LIXINREN_TOKEN_NET_VALUE = _get_stripped_env("LIXINREN_TOKEN_NET_VALUE")
LIXINREN_TIMEOUT = 60


def get_lixinren_mode() -> str:
    """读取理杏仁运行模式，未配置时默认 global。"""
    mode = _get_stripped_env("LIXINREN_MODE", LIXINREN_MODE_GLOBAL).lower()
    if not mode:
        return LIXINREN_MODE_GLOBAL
    if mode not in {LIXINREN_MODE_GLOBAL, LIXINREN_MODE_PERSONALIZED}:
        raise ValueError(
            "LIXINREN_MODE 配置非法，仅允许 global 或 personalized"
        )
    return mode


def get_lixinren_token_slot_name(interface_type: str, mode: str | None = None) -> str:
    """根据运行模式与逻辑接口类型解析 token 配置槽位名称。"""
    resolved_mode = mode or get_lixinren_mode()
    if resolved_mode == LIXINREN_MODE_GLOBAL:
        return "LIXINREN_TOKEN"

    mapping = {
        DataInterface.DAILY_BAR: "LIXINREN_TOKEN_DAILY_BAR",
        DataInterface.FUNDAMENTAL: "LIXINREN_TOKEN_FUNDAMENTAL",
        DataInterface.NET_VALUE: "LIXINREN_TOKEN_NET_VALUE",
    }
    slot_name = mapping.get(interface_type)
    if not slot_name:
        raise ValueError(f"未知的理杏仁接口类型: {interface_type}")
    return slot_name


def get_lixinren_token_by_slot(slot_name: str, required: bool = False) -> str:
    """按槽位名称读取理杏仁 token。"""
    token = _get_stripped_env(slot_name)
    if required and not token:
        raise ValueError(f"{slot_name} 未配置，无法初始化理杏仁数据源")
    return token


def get_lixinren_token(required: bool = False) -> str:
    """兼容旧逻辑：读取全局理杏仁 Token。"""
    return get_lixinren_token_by_slot("LIXINREN_TOKEN", required=required)

# ==============================================================================
# 5. 理杏仁流控配置 (Time Sleep Settings)
# ==============================================================================
# K线分页拉取时的间隔 (秒)
LIXINREN_KLINE_PAGE_SLEEP = 5

# 基本面初始化模式 (Init Mode) 每个时间段处理后的间隔 (秒)
LIXINREN_FUND_INIT_SLEEP = 6

# 基本面增量模式 (Batch Mode) 每批次(100个)处理后的间隔 (秒)
LIXINREN_FUND_BATCH_SLEEP = 3

# 基金净值分页拉取配置
FUND_DAILY_MAX_DAYS_PER_REQUEST = 3650
FUND_DAILY_REQUEST_SLEEP_SECONDS = 1

# 接口请求失败重试等待时间 (秒)
LIXINREN_RETRY_WAIT = 60

# ==============================================================================
# 6. efinance 实时行情配置
# ==============================================================================
# 行情缓存刷新 TTL (秒)
EFINANCE_REFRESH_TTL_SECONDS = 600

# 保留旧配置名兼容历史调用
EFINANCE_POLL_INTERVAL = EFINANCE_REFRESH_TTL_SECONDS

# 最大重试次数
EFINANCE_MAX_RETRY = 2

# 单次请求最大代码数
EFINANCE_MAX_CODES_PER_REQUEST = 50

# ==============================================================================
# 7. TickFlow 日线采集配置
# ==============================================================================
TICKFLOW_API_KEY = _get_stripped_env("TICKFLOW_API_KEY")
TICKFLOW_ADJUST = _get_stripped_env("TICKFLOW_ADJUST", "none") or "none"
TICKFLOW_TIMEOUT_SECONDS = float(os.getenv("TICKFLOW_TIMEOUT_SECONDS", "60"))
TICKFLOW_MAX_RETRIES = int(os.getenv("TICKFLOW_MAX_RETRIES", "3"))
TICKFLOW_DAILY_BAR_REQUEST_SLEEP_SECONDS = float(os.getenv("TICKFLOW_DAILY_BAR_REQUEST_SLEEP_SECONDS", "6.1"))
TICKFLOW_REALTIME_MAX_CODES_PER_REQUEST = int(os.getenv("TICKFLOW_REALTIME_MAX_CODES_PER_REQUEST", "5"))
TICKFLOW_REALTIME_REQUESTS_PER_MINUTE = int(os.getenv("TICKFLOW_REALTIME_REQUESTS_PER_MINUTE", "10"))
TICKFLOW_REALTIME_REQUEST_SLEEP_SECONDS = float(os.getenv("TICKFLOW_REALTIME_REQUEST_SLEEP_SECONDS", "6.1"))
TICKFLOW_KLINE_COUNT_LIMIT = int(os.getenv("TICKFLOW_KLINE_COUNT_LIMIT", "10000"))

# ==============================================================================
# 8. 历史行情缺口回补配置
# ==============================================================================
MARKET_GAP_FILL_ENABLED = _get_bool_env("MARKET_GAP_FILL_ENABLED", True)
MARKET_GAP_FILL_MAX_RETRIES = int(os.getenv("MARKET_GAP_FILL_MAX_RETRIES", "3"))
MARKET_GAP_FILL_RETRY_DELAY_MINUTES = int(
    os.getenv("MARKET_GAP_FILL_RETRY_DELAY_MINUTES", "60")
)
MARKET_GAP_FILL_RUNNING_TTL_MINUTES = int(
    os.getenv("MARKET_GAP_FILL_RUNNING_TTL_MINUTES", "30")
)
MARKET_GAP_FILL_ZERO_HISTORY_DAYS_PER_ASSET = int(
    os.getenv("MARKET_GAP_FILL_ZERO_HISTORY_DAYS_PER_ASSET", "250")
)
MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN = int(
    os.getenv("MARKET_GAP_FILL_MAX_NEW_TASKS_PER_RUN", "5000")
)
TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN = int(
    os.getenv("TICKFLOW_GAP_FILL_MAX_REQUESTS_PER_RUN", "30")
)
TICKFLOW_GAP_FILL_SLEEP_SECONDS = float(
    os.getenv("TICKFLOW_GAP_FILL_SLEEP_SECONDS", "6.1")
)
TDX_VIPDOC_PAGE_URL = _get_stripped_env(
    "TDX_VIPDOC_PAGE_URL",
    "https://www.tdx.com.cn/article/vipdata.html",
)
TDX_VIPDOC_ZIP_URL = _get_stripped_env("TDX_VIPDOC_ZIP_URL")
TDX_VIPDOC_ROOT = pathlib.Path(
    os.getenv("TDX_VIPDOC_ROOT", str(DATA_DIR / "tdx_vipdoc"))
)
TDX_VIPDOC_STALE_DAYS = int(os.getenv("TDX_VIPDOC_STALE_DAYS", "1"))
TDX_REFRESH_TIMEOUT_SECONDS = int(os.getenv("TDX_REFRESH_TIMEOUT_SECONDS", "1800"))
