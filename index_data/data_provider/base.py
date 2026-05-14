from abc import ABC, abstractmethod
import pandas as pd
from typing import Any

class BaseDataProvider(ABC):
    
    @abstractmethod
    def fetch_raw(self, asset_code: str, start_date: str, end_date: str, **kwargs) -> Any:
        """
        获取原始数据 (Extract)
        :param asset_code: 资产代码
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param kwargs: 扩展参数 (exchange, source_code 等)
        :return: JSON Serializable object (dict or list)
        """
        pass

    @abstractmethod
    def parse(self, raw_data: Any, **kwargs) -> pd.DataFrame:
        """
        解析原始数据 (Transform)
        :return: DataFrame (Standard Schema)
        """
        pass