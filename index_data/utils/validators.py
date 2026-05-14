# 文件: utils/validators.py
"""
参数校验工具模块

提供统一的参数验证功能，提高代码健壮性和错误信息清晰度。
"""
import re
from datetime import datetime
from typing import Any, Optional


class ValidationError(ValueError):
    """参数校验异常"""
    pass


def validate_asset_code(code: str) -> str:
    """
    校验资产代码格式

    :param code: 资产代码
    :return: 标准化的资产代码
    :raises ValidationError: 如果格式不合法
    """
    if not code or not isinstance(code, str):
        raise ValidationError("asset_code cannot be empty")

    code = code.strip()
    if not code:
        raise ValidationError("asset_code cannot be whitespace only")

    # 可选：校验代码格式（如 6 位数字）
    # if not re.match(r'^\d{6}$', code):
    #     raise ValidationError(f"Invalid asset_code format: {code}")

    return code


def validate_date(date_str: str, param_name: str = "date") -> str:
    """
    校验日期格式 (YYYY-MM-DD)

    :param date_str: 日期字符串
    :param param_name: 参数名称（用于错误信息）
    :return: 验证通过的日期字符串
    :raises ValidationError: 如果格式不合法
    """
    if not date_str or not isinstance(date_str, str):
        raise ValidationError(f"{param_name} cannot be empty")

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise ValidationError(
            f"Invalid {param_name} format: {date_str}, expected YYYY-MM-DD"
        )


def validate_date_range(start_date: str, end_date: str) -> tuple:
    """
    校验日期范围

    :param start_date: 开始日期
    :param end_date: 结束日期
    :return: (start_date, end_date) 元组
    :raises ValidationError: 如果 start_date > end_date
    """
    start = validate_date(start_date, "start_date")
    end = validate_date(end_date, "end_date")

    if start > end:
        raise ValidationError(
            f"start_date ({start}) must be before or equal to "
            f"end_date ({end})"
        )

    return start, end


def validate_not_empty(value: Any, param_name: str) -> Any:
    """
    校验参数不为空

    :param value: 待验证的值
    :param param_name: 参数名称
    :return: 验证通过的值
    :raises ValidationError: 如果值为空
    """
    if value is None:
        raise ValidationError(f"{param_name} cannot be None")

    if isinstance(value, (str, list, dict)) and not value:
        raise ValidationError(f"{param_name} cannot be empty")

    return value
