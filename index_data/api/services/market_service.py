# 文件: api/services/market_service.py
from dao.market_dao import market_dao


class MarketService:
    """行情数据服务层"""
    
    def get_market_data(self, page: int = 1, page_size: int = 60):
        """
        获取市场行情数据
        
        Args:
            page: 页码（从1开始）
            page_size: 每页数量
            
        Returns:
            dict: 包含分页信息和数据的字典
        """
        # 计算偏移量
        offset = (page - 1) * page_size
        
        latest_date = market_dao.get_latest_trade_date_global()
            
        if not latest_date:
             return {
                'page': page,
                'page_size': page_size,
                'total': 0,
                'total_pages': 0,
                'items': []
            }

        total = market_dao.get_index_market_count_by_date(latest_date)
        data = market_dao.get_index_market_page_by_date(
            trade_date=latest_date,
            limit=page_size,
            offset=offset
        )
        
        # 计算总页数
        total_pages = (total + page_size - 1) // page_size
        
        return {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'items': data
        }
