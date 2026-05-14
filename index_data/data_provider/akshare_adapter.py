import akshare as ak
import pandas as pd
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .base import BaseDataProvider
from utils.date_utils import parse_excel_date
from utils.logger import logger
from utils.validators import (validate_asset_code, validate_date_range,
                               ValidationError)
from utils.exceptions import DataFetchError


class AkShareAdapter(BaseDataProvider):
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True
    )
    def fetch_raw(self, asset_code: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """
        从 AkShare 获取股票/指数日线数据
        
        自动重试机制：网络错误最多重试3次，指数退避
        """
        # 参数校验
        validate_asset_code(asset_code)
        validate_date_range(start_date, end_date)
        
        source_code = kwargs.get('source_code', asset_code)
        
        try:
            df = ak.stock_zh_index_daily_em(symbol=source_code)
            
            if df is None or df.empty:
                logger.warning(f"AkShare returned empty data for {asset_code}")
                return pd.DataFrame()
                
            return df
            
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Network error fetching {asset_code}, will retry: {e}")
            raise  # 让 tenacity 处理重试
        except Exception as e:
            logger.error(f"AkShare fetch failed for {asset_code}: {e}")
            raise DataFetchError(f"Failed to fetch data from AkShare for {asset_code}") from e

    def parse(self, raw_data, **kwargs) -> pd.DataFrame:
        if raw_data is None:
            return pd.DataFrame()
        
        if isinstance(raw_data, pd.DataFrame):
            if raw_data.empty:
                return pd.DataFrame()
            df = raw_data.copy()  # 避免修改原始数据
        else:
            if not raw_data:
                return pd.DataFrame()
            df = pd.DataFrame(raw_data)
        
        rename_map = {
            'date': 'trade_date',
            'open': 'open', 'close': 'close', 
            'high': 'high', 'low': 'low', 
            'volume': 'volume', 'amount': 'amount'
        }
        df = df.rename(columns=rename_map)
        
        cols = ['trade_date', 'open', 'close', 'high', 'low', 'volume', 'amount']
        df = df[[c for c in cols if c in df.columns]]
        
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        
        if start_date:
            df = df[df['trade_date'] >= start_date]
        if end_date:
            df = df[df['trade_date'] <= end_date]
            
        return df