import datetime
import pandas as pd
from typing import Any, Dict, Optional

from utils.logger import logger

def get_current_date() -> str:
    """返回当前日期 YYYY-MM-DD"""
    return datetime.datetime.now().strftime("%Y-%m-%d")

def is_market_closed(close_hour: int, now: Optional[datetime.datetime] = None) -> bool:
    """判断当前时间是否已过收盘时间"""
    current = now or datetime.datetime.now()
    return current.hour >= close_hour

def get_trade_day_close_context(
    market_dao: Any,
    close_hour: int,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, object]:
    """基于本地交易日历与收盘小时返回统一判定上下文。"""
    current = now or datetime.datetime.now()
    today = current.strftime("%Y-%m-%d")

    try:
        is_trade_day = bool(market_dao.is_trade_date(today))
        calendar_available = True
    except Exception:
        logger.exception("交易日历读取失败，按保守策略降级为非交易日")
        is_trade_day = False
        calendar_available = False

    return {
        "today": today,
        "is_trade_day": is_trade_day,
        "market_closed": is_trade_day and is_market_closed(close_hour, current),
        "market_close_hour": close_hour,
        "calendar_available": calendar_available,
    }

def parse_excel_date(raw_val) -> str:
    """
    清洗 Excel 中的日期格式，统一返回 YYYY-MM-DD
    支持: datetime, Timestamp, 'YYYY-MM-DD', 'YYYYMMDD'
    """
    if pd.isna(raw_val) or raw_val == "":
        return None
    
    try:
        # 如果已经是 datetime 对象
        if isinstance(raw_val, (datetime.datetime, datetime.date)):
            return raw_val.strftime("%Y-%m-%d")
        
        # 如果是 Pandas Timestamp
        if isinstance(raw_val, pd.Timestamp):
            return raw_val.strftime("%Y-%m-%d")

        # 字符串清洗
        s_val = str(raw_val).strip()
        
        # 常见格式尝试
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                dt = datetime.datetime.strptime(s_val, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
                
        return None
    except Exception:
        return None
