# data_provider/efinance_adapter.py - efinance 数据源适配器
"""
efinance 实时行情适配器
v2.4.5: 支持 ETF/股票实时行情查询
"""
import pandas as pd
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from utils.logger import logger
import concurrent.futures

try:
    import efinance as ef
    EFINANCE_AVAILABLE = True
except ImportError:
    EFINANCE_AVAILABLE = False
    logger.warning("efinance 库未安装，实时行情功能不可用")

from .base import BaseDataProvider


@dataclass
class RealtimeQuote:
    """实时行情数据模型"""
    code: str = ""
    name: str = ""
    date: str = ""
    open: float = 0.0
    close: float = 0.0  # 当前价/收盘价
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    amplitude: float = 0.0  # 振幅 (%)
    change_pct: float = 0.0  # 涨跌幅 (%)
    change_amt: float = 0.0  # 涨跌额
    turnover: float = 0.0  # 换手率 (%)
    is_realtime: bool = True
    
    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'name': self.name,
            'date': self.date,
            'open': self.open,
            'close': self.close,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'amplitude': self.amplitude,
            'change_pct': self.change_pct,
            'change_amt': self.change_amt,
            'turnover': self.turnover,
            'is_realtime': self.is_realtime,
        }


class EfinanceAdapter(BaseDataProvider):
    """
    efinance 数据源适配器
    特点：
    - 免费接口，无需 Token
    - 返回全量历史数据，取最新一条作为实时行情
    - 建议轮询间隔不低于 30 分钟
    """
    
    def __init__(self):
        if not EFINANCE_AVAILABLE:
            logger.warning("EfinanceAdapter 初始化：efinance 库不可用")
    
    def fetch_raw(self, asset_code: str, start_date: str, end_date: str, **kwargs) -> Any:
        """
        获取历史 K 线数据
        :param asset_code: 股票/ETF 代码 (如 '513050', '510300')
        :return: DataFrame
        """
        if not EFINANCE_AVAILABLE:
            logger.error("efinance 库未安装")
            return None
        
        try:
            # 调用 efinance API
            df = ef.stock.get_quote_history(asset_code)
            
            if df is None or df.empty:
                logger.warning(f"efinance 返回空数据: {asset_code}")
                return None
            
            return df
        except Exception as e:
            logger.error(f"efinance 请求失败: {asset_code} - {e}")
            return None
    
    def parse(self, raw_data: Any, **kwargs) -> pd.DataFrame:
        """
        解析 efinance 返回的 DataFrame
        """
        if raw_data is None or raw_data.empty:
            return pd.DataFrame()
        
        df = raw_data.copy()
        
        # 重命名列 (efinance 返回的列名是中文)
        column_map = {
            '股票代码': 'asset_code',
            '股票名称': 'name',
            '日期': 'trade_date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '振幅': 'amplitude',
            '涨跌幅': 'change_pct',
            '涨跌额': 'change_amt',
            '换手率': 'turnover',
        }
        
        df = df.rename(columns=column_map)
        
        # 确保日期格式
        if 'trade_date' in df.columns:
            df['trade_date'] = df['trade_date'].astype(str)
        
        return df
    
    def fetch_realtime(self, codes: List[str]) -> Optional[Dict[str, RealtimeQuote]]:
        """
        获取实时行情 (使用批量接口)
        :param codes: 代码列表
        :return: {code: RealtimeQuote} 字典
        """
        if not EFINANCE_AVAILABLE:
            logger.warning("efinance 库不可用，无法获取实时行情")
            return None
        
        result = {}
        
        try:
            # 批量获取行情
            # efinance 的 get_latest_quote 支持传入代码列表
            # v2.5.1: 增加超时控制，避免卡死页面
            def _fetch():
                return ef.stock.get_latest_quote(codes)
            
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_fetch)
            try:
                df = future.result(timeout=4) # 4秒超时
            except concurrent.futures.TimeoutError:
                future.cancel()
                logger.warning("efinance 实时行情获取超时 (4s), 跳过更新")
                return None
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            
            if df is None or df.empty:
                logger.warning("efinance get_latest_quote 返回空数据")
                return None
            
            for _, row in df.iterrows():
                try:
                    code = str(row.get('代码'))
                    if not code:
                        continue
                        
                    quote = RealtimeQuote(
                        code=code,
                        name=str(row.get('名称', '')),
                        date=str(row.get('最新交易日', ''))[:10],
                        open=float(row.get('今开', 0) or 0),
                        close=float(row.get('最新价', 0) or 0),
                        high=float(row.get('最高', 0) or 0),
                        low=float(row.get('最低', 0) or 0),
                        volume=float(row.get('成交量', 0) or 0),
                        amount=float(row.get('成交额', 0) or 0),
                        amplitude=float(row.get('振幅', 0) or 0),
                        change_pct=float(row.get('涨跌幅', 0) or 0),
                        change_amt=float(row.get('涨跌额', 0) or 0),
                        turnover=float(row.get('换手率', 0) or 0),
                        is_realtime=True,
                    )
                    
                    result[code] = quote
                    
                except Exception as e:
                    logger.error(f"解析行情行失败: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"批量获取实时行情失败: {e}")
            # 降级：如果批量失败，记录错误并返回 None (前端会容错处理)
            return None
            
        return result if result else None
    
    def get_latest_quote(self, code: str) -> Optional[RealtimeQuote]:
        """
        获取单个代码的最新行情
        :param code: 股票/ETF 代码
        :return: RealtimeQuote 或 None
        """
        result = self.fetch_realtime([code])
        if result and code in result:
            return result[code]
        return None


# 单例
efinance_adapter = EfinanceAdapter()
