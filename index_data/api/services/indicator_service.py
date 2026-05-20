# 文件: api/services/indicator_service.py
import orjson
from dao.indicator_dao import indicator_dao


class IndicatorService:
    """技术指标数据服务层"""
    
    def get_indicator_data(
        self,
        page: int = 1,
        page_size: int = 60,
        group: str = "index",
    ):
        """
        获取技术指标数据
        
        Args:
            page: 页码（从1开始）
            page_size: 每页数量
            group: 资产分组，index 或 non_index
            
        Returns:
            dict: 包含分页信息和数据的字典
        """
        latest_date = indicator_dao.get_latest_trade_date_global()
            
        if not latest_date:
             return {
                'page': page,
                'page_size': page_size,
                'total': 0,
                'total_pages': 0,
                'items': []
            }

        if group == "index":
            total = indicator_dao.count_index_assets_by_date(latest_date)
        else:
            total = indicator_dao.count_assets_by_date(latest_date, group)
        if total <= 0:
            return {
                'page': page,
                'page_size': page_size,
                'total': 0,
                'total_pages': 0,
                'items': []
            }

        total_pages = (total + page_size - 1) // page_size
        start_idx = (page - 1) * page_size
        if group == "index":
            asset_codes_page = indicator_dao.get_index_asset_codes_page_by_date(
                trade_date=latest_date,
                limit=page_size,
                offset=start_idx
            )
        else:
            asset_codes_page = indicator_dao.get_asset_codes_page_by_date(
                trade_date=latest_date,
                group=group,
                limit=page_size,
                offset=start_idx
            )

        if not asset_codes_page:
            return {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
                'items': []
            }

        if group == "index":
            rows = indicator_dao.get_index_indicator_rows_by_date_and_codes(
                trade_date=latest_date,
                asset_codes=asset_codes_page
            )
        else:
            rows = indicator_dao.get_indicator_rows_by_date_and_codes(
                trade_date=latest_date,
                group=group,
                asset_codes=asset_codes_page
            )

        # 合并同一代码多 config 的 JSON 数据
        merged_data = {}
        for row in rows:
            key = (row['trade_date'], row['asset_code'])
            if key not in merged_data:
                merged_data[key] = {
                    'name': row['asset_name'], 
                    'close': row['close_price'],
                    'indicators': {}
                }
            try:
                val_dict = orjson.loads(row['val_json'])
                merged_data[key]['indicators'].update(val_dict)
            except:
                pass
        
        # 构建行数据
        items = []
        for (date, code), data_item in merged_data.items():
            name = data_item['name']
            close = data_item['close']
            indicators = data_item['indicators']
            row = {'trade_date': date, 'code': code, 'name': name, 'close': close}
            
            # MA
            row['ma5'] = indicators.get('SMA_5')
            row['ma10'] = indicators.get('SMA_10')
            row['ma20'] = indicators.get('SMA_20')
            
            # RSI
            row['rsi_6'] = indicators.get('RSI_6')
            row['rsi_14'] = indicators.get('RSI_14')
            
            # MACD
            row['dif'] = indicators.get('MACD_12_26_9')
            row['dea'] = indicators.get('MACDs_12_26_9')
            row['macd'] = indicators.get('MACDh_12_26_9')
            
            # ATR14
            # 优先使用 ATRr_14 (Rate?), 但根据扫描结果只有 ATRr_14
            atr14 = indicators.get('ATRr_14')
            if atr14 is None:
                atr14 = indicators.get('ATR_14')
            
            row['atr14'] = atr14
            
            # 计算 2.5倍 ATR 点位
            if atr14 is not None and close is not None:
                try:
                    row['atr_stop_loss'] = close - (atr14 * 2.5)
                except:
                    row['atr_stop_loss'] = None
            else:
                 row['atr_stop_loss'] = None
            
            items.append(row)

        # 保持分页顺序与代码页顺序一致
        code_order = {code: idx for idx, code in enumerate(asset_codes_page)}
        items.sort(key=lambda x: code_order.get(x.get('code', ''), 10**9))
        
        return {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'items': items
        }
