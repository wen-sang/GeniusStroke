# 文件: api/services/fundamental_service.py
import orjson
from dao.fundamental_dao import fundamental_dao


class FundamentalService:
    """基本面数据服务层"""

    @staticmethod
    def _parse_stats(json_str):
        """解析 full_stats_json 中的 PE 分位阈值"""
        try:
            if not json_str:
                return None, None, None
            data = orjson.loads(json_str)
            # 保持原有优先级：先 y10，再 fs
            q2 = data.get("pe_ttm.y10.mcw.q2v") or data.get("pe_ttm.fs.mcw.q2v")
            q5 = data.get("pe_ttm.y10.mcw.q5v") or data.get("pe_ttm.fs.mcw.q5v")
            q8 = data.get("pe_ttm.y10.mcw.q8v") or data.get("pe_ttm.fs.mcw.q8v")
            return q2, q5, q8
        except Exception:
            return None, None, None
    
    def get_fundamental_data(self, page: int = 1, page_size: int = 60):
        """
        获取基本面数据
        
        Args:
            page: 页码（从1开始）
            page_size: 每页数量
            
        Returns:
            dict: 包含分页信息和数据的字典
        """
        # 计算偏移量
        offset = (page - 1) * page_size
        
        latest_date = fundamental_dao.get_latest_trade_date_global()
            
        if not latest_date:
             return {
                'page': page,
                'page_size': page_size,
                'total': 0,
                'total_pages': 0,
                'items': []
            }

        total = fundamental_dao.get_index_fundamental_count_by_date(latest_date)
        rows = fundamental_dao.get_index_fundamental_page_by_date(
            trade_date=latest_date,
            limit=page_size,
            offset=offset
        )

        if not rows:
            return {
                'page': page,
                'page_size': page_size,
                'total': 0,
                'total_pages': 0,
                'items': []
            }

        # 构造输出数据（轻量路径：避免 DataFrame/concat/apply 开销）
        data = []
        for row in rows:
            pe_low_20, pe_mid_50, pe_high_80 = self._parse_stats(row.get('full_stats_json'))
            data.append({
                'trade_date': row.get('trade_date'),
                'code': row.get('asset_code'),
                'name': row.get('asset_name'),
                'pe_ttm': row.get('pe_ttm'),
                'pb': row.get('pb'),
                'pe_pos_5y': row.get('pe_pos_5y'),
                'pe_low_20': pe_low_20,
                'pe_mid_50': pe_mid_50,
                'pe_high_80': pe_high_80,
            })
        
        # 计算总页数
        total_pages = (total + page_size - 1) // page_size
        
        return {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'items': data
        }
