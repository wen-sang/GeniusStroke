from dao.market_dao import market_dao


MARKET_SORT_FIELDS = {
    "amount",
    "return_22d",
    "return_60d",
    "return_6m",
    "return_1y",
}


class MarketService:
    """行情数据服务层"""
    
    def get_market_data(
        self,
        page: int = 1,
        page_size: int = 60,
        group: str = "index",
        sort_by: str = "amount",
        sort_order: str = "desc",
    ):
        """
        获取市场行情数据
        
        Args:
            page: 页码（从1开始）
            page_size: 每页数量
            group: 资产分组，index 或 non_index
            sort_by: 排序字段
            sort_order: 排序方向，desc 或 asc
            
        Returns:
            dict: 包含分页信息和数据的字典
        """
        # 计算偏移量
        offset = (page - 1) * page_size

        result = market_dao.get_market_page_result(
            group=group,
            limit=page_size,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        if not result["trade_date"]:
             return {
                'page': page,
                'page_size': page_size,
                'total': 0,
                'total_pages': 0,
                'items': []
            }

        total = result["total"]
        # 计算总页数
        total_pages = (total + page_size - 1) // page_size
        
        return {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'items': result["items"]
        }
