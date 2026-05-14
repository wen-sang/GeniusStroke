# 文件: utils/null_handler.py
"""
空值处理工具模块

根据配置策略统一处理不同类型数据的空值。
"""
import pandas as pd
from config.null_handling import (MARKET_DATA_NULL_STRATEGY,
                                   DEFAULT_VALUES)
from utils.logger import logger


class NullHandlingError(ValueError):
    """空值处理异常"""
    pass


def handle_market_data_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """
    根据策略处理行情数据的空值

    :param df: 原始 DataFrame
    :return: 处理后的 DataFrame
    :raises NullHandlingError: 如果必填字段有 NULL
    """
    df = df.copy()
    
    for col, strategy in MARKET_DATA_NULL_STRATEGY.items():
        if col not in df.columns:
            continue
        
        if strategy == 'keep_null':
            # 保持 NULL，不做处理（SQLite 会存储为 NULL）
            pass
        
        elif strategy == 'fill_zero':
            # 填充为 0
            df[col] = df[col].fillna(0)
        
        elif strategy == 'fill_default':
            # 填充为默认值
            default_val = DEFAULT_VALUES.get(col, '')
            df[col] = df[col].fillna(default_val)
        
        elif strategy == 'raise_error_if_null':
            # 必填字段，如果有 NULL 则抛出异常
            if df[col].isnull().any():
                null_count = df[col].isnull().sum()
                raise NullHandlingError(
                    f"Column '{col}' contains {null_count} NULL values, "
                    f"but it's required"
                )
    
    return df


def convert_null_for_json(value):
    """
    将 pandas.NA / NaN 转换为 None（用于 JSON 序列化）

    :param value: 待转换的值
    :return: None if NaN/NA, otherwise original value
    """
    if pd.isna(value):
        return None
    return value
