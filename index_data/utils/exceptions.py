"""
自定义异常类模块

定义项目特定的异常类型，用于更精确的错误处理和诊断。
"""


class DataFetchError(Exception):
    """
    数据获取失败异常
    
    用于网络请求失败、API调用失败等可重试的错误场景。
    """
    pass


class DataParseError(Exception):
    """
    数据解析失败异常
    
    用于原始数据格式错误、字段缺失等数据质量问题。
    """
    pass


class DatabaseError(Exception):
    """
    数据库操作异常
    
    用于数据库连接、查询、事务等操作失败的场景。
    """
    pass


class ConfigurationError(Exception):
    """
    配置错误异常
    
    用于配置文件错误、必需参数缺失等配置问题。
    """
    pass
