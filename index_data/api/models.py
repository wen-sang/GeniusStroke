# 文件: api/models.py
from pydantic import BaseModel
from typing import List, Any, Optional


class PaginationParams(BaseModel):
    """分页参数模型"""
    page: int = 1
    page_size: int = 60


class PaginatedResponse(BaseModel):
    """分页响应模型"""
    page: int
    page_size: int
    total: int
    total_pages: int
    items: List[dict]
