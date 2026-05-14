import datetime
import time
from typing import Dict, List, Mapping, Sequence

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from config.lixinren_endpoints import (
    LIXINREN_ENDPOINT_CN_FUND_NET_VALUE,
    LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE,
)
from config.settings import (
    LIXINREN_TIMEOUT,
    LIXINREN_KLINE_PAGE_SLEEP,
    LIXINREN_RETRY_WAIT
)
from .base import BaseDataProvider
from utils.logger import logger


class LixinrenAdapter(BaseDataProvider):
    """
    理杏仁适配器。

    Token、接口类型与 endpoint 全部由 provider 工厂注入，适配器内部
    不再负责选择具体 URL。
    """
    MAX_DAYS = 3000

    def __init__(
        self,
        token: str,
        interface_type: str,
        token_slot_name: str,
        endpoint_urls: Mapping[str, str],
        endpoint_keys: Sequence[str] | None = None,
        mode: str | None = None,
    ):
        self.token = str(token).strip()
        self.interface_type = interface_type
        self.token_slot_name = token_slot_name
        self.endpoint_urls = {
            str(key): str(value).strip()
            for key, value in dict(endpoint_urls).items()
        }
        self.endpoint_keys = list(endpoint_keys or self.endpoint_urls.keys())
        self.mode = mode or ""
        if not self.token:
            raise ValueError("LIXINREN_TOKEN 未配置，无法初始化理杏仁适配器")
        if not self.endpoint_urls:
            raise ValueError("理杏仁 endpoint 配置不能为空")
        for key, url in self.endpoint_urls.items():
            if not url:
                raise ValueError(f"理杏仁 endpoint 配置缺失或为空: {key}")

    def _safe_payload(self, payload: Dict) -> Dict:
        safe_payload = dict(payload)
        if 'token' in safe_payload:
            safe_payload['token'] = '******'
        return safe_payload

    def _log_context(self, endpoint_key: str | None = None) -> str:
        resolved_endpoint_key = endpoint_key or ",".join(self.endpoint_keys)
        return (
            f"interface={self.interface_type} "
            f"token_slot={self.token_slot_name} "
            f"mode={self.mode} "
            f"endpoint={resolved_endpoint_key}"
        )

    def _get_single_endpoint_url(self) -> str:
        endpoint_key = self.endpoint_keys[0]
        return self.endpoint_urls[endpoint_key]

    def _get_endpoint_url(self, endpoint_key: str) -> str:
        url = self.endpoint_urls.get(endpoint_key, "").strip()
        if not url:
            raise ValueError(f"理杏仁 endpoint 配置缺失或为空: {endpoint_key}")
        return url

    # --------------------------------------------------------------------------
    # Part 1: K线数据
    # --------------------------------------------------------------------------
    def fetch_raw(self, asset_code: str, start_date: str, end_date: str, **kwargs) -> List[Dict]:
        exchange = kwargs.get('exchange', 'SH')
        url_kline = self._get_single_endpoint_url()

        dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d")

        all_data = []
        curr = dt_start

        while curr <= dt_end:
            next_hop = curr + datetime.timedelta(days=self.MAX_DAYS)
            seg_end = min(next_hop, dt_end)

            s_str = curr.strftime("%Y-%m-%d")
            e_str = seg_end.strftime("%Y-%m-%d")

            try:
                seg_data = self._do_request(url_kline, {
                    "token": self.token,
                    "stockCode": asset_code,
                    "type": "normal",
                    "startDate": s_str,
                    "endDate": e_str
                }, endpoint_key=self.endpoint_keys[0])
                all_data.extend(seg_data)

                if next_hop < dt_end:
                    time.sleep(LIXINREN_KLINE_PAGE_SLEEP)  # 使用配置参数
            except Exception as e:
                logger.error(
                    f"Lixinren Segment Fail {self._log_context(self.endpoint_keys[0])} "
                    f"exchange={exchange} asset_code={asset_code} err={e}"
                )
                raise

            curr = seg_end + datetime.timedelta(days=1)

        return all_data

    def parse(self, raw_data, **kwargs) -> pd.DataFrame:
        if not raw_data:
            return pd.DataFrame()
        df = pd.DataFrame(raw_data)
        if 'date' in df.columns:
            df['trade_date'] = df['date'].apply(lambda x: str(x)[:10])
        cols = ['trade_date', 'open', 'close', 'high', 'low', 'volume', 'amount']
        for c in cols:
            if c not in df.columns:
                df[c] = 0.0
        return df[cols]

    # --------------------------------------------------------------------------
    # Part 2: 基本面数据
    # --------------------------------------------------------------------------
    def fetch_fundamental(self,
                          stock_codes: List[str],
                          metrics_list: List[str],
                          date: str = None,
                          start_date: str = None,
                          end_date: str = None,
                          exchange: str = 'SH') -> List[Dict]:
        url_fundamental = self._get_single_endpoint_url()

        payload = {
            "token": self.token,
            "stockCodes": stock_codes,
            "metricsList": metrics_list
        }

        if date:
            payload["date"] = date
        elif start_date and end_date:
            if len(stock_codes) > 1:
                raise ValueError("Lixinren API limits: Range mode supports only 1 stock code.")
            payload["startDate"] = start_date
            payload["endDate"] = end_date
        else:
            raise ValueError("Must provide either 'date' OR 'start_date'+'end_date'")

        return self._do_request(
            url_fundamental,
            payload,
            endpoint_key=self.endpoint_keys[0],
        )

    # --------------------------------------------------------------------------
    # Part 3: 净值数据
    # --------------------------------------------------------------------------
    def fetch_net_value(self,
                       stock_code: str,
                       start_date: str,
                       end_date: str = None,
                       exchange: str = 'SH') -> List[Dict]:
        """
        获取基金单位净值数据
        
        :param stock_code: 基金代码
        :param start_date: 开始日期 (YYYY-MM-DD)
        :param end_date: 结束日期 (YYYY-MM-DD)，可选
        :param exchange: 交易所 (SH/SZ/HK)
        :return: 净值数据列表 [{'date': '2026-01-29', 'netValue': 0.7386}, ...]
        """
        url_net_value = self._get_endpoint_url(LIXINREN_ENDPOINT_CN_FUND_NET_VALUE)
        
        payload = {
            "token": self.token,
            "stockCode": stock_code,
            "startDate": start_date
        }
        
        if end_date:
            payload["endDate"] = end_date
        
        return self._do_request(
            url_net_value,
            payload,
            endpoint_key=LIXINREN_ENDPOINT_CN_FUND_NET_VALUE,
        )
    
    def fetch_total_net_value(self,
                             stock_code: str,
                             start_date: str,
                             end_date: str = None,
                             exchange: str = 'SH') -> List[Dict]:
        """
        获取基金累计净值数据
        
        :param stock_code: 基金代码
        :param start_date: 开始日期 (YYYY-MM-DD)
        :param end_date: 结束日期 (YYYY-MM-DD)，可选
        :param exchange: 交易所 (SH/SZ/HK)
        :return: 累计净值数据列表 [{'date': '2026-01-30', 'totalNetValue': 1.8398}, ...]
        """
        url_total_net_value = self._get_endpoint_url(
            LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE
        )
        
        payload = {
            "token": self.token,
            "stockCode": stock_code,
            "startDate": start_date
        }
        
        if end_date:
            payload["endDate"] = end_date
        
        return self._do_request(
            url_total_net_value,
            payload,
            endpoint_key=LIXINREN_ENDPOINT_CN_FUND_TOTAL_NET_VALUE,
        )
    
    def fetch_fund_daily(self,
                        stock_code: str,
                        start_date: str,
                        end_date: str = None,
                        exchange: str = 'SH') -> List[Dict]:
        """
        批量获取基金日线数据（净值 + 累计净值）
        
        :param stock_code: 基金代码
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param exchange: 交易所
        :return: 合并后的数据列表 [{'date': '2026-01-29', 'unit_nav': 0.7386, 'accum_nav': 1.8398}, ...]
        """
        # 分别获取单位净值和累计净值
        net_value_data = self.fetch_net_value(stock_code, start_date, end_date, exchange)
        total_net_value_data = self.fetch_total_net_value(stock_code, start_date, end_date, exchange)
        
        # 构建日期映射
        net_value_map = {item['date'][:10]: item.get('netValue') for item in net_value_data}
        total_net_value_map = {item['date'][:10]: item.get('totalNetValue') for item in total_net_value_data}
        
        # 合并数据
        all_dates = set(net_value_map.keys()) | set(total_net_value_map.keys())
        
        result = []
        for date in sorted(all_dates):
            result.append({
                'date': date,
                'unit_nav': net_value_map.get(date),
                'accum_nav': total_net_value_map.get(date)
            })
        
        return result

    # [优化] 增加重试机制：遇错重试3次，每次间隔使用配置参数
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(LIXINREN_RETRY_WAIT),  # 使用配置参数
        retry=retry_if_exception_type((requests.exceptions.RequestException, RuntimeError, ConnectionError))
    )
    def _do_request(self, url, payload, endpoint_key: str | None = None):
        safe_payload = self._safe_payload(payload)
        try:
            resp = requests.post(url, json=payload, timeout=LIXINREN_TIMEOUT)
        except Exception as e:
            logger.warning(
                f"Lixinren Network Error (Retrying...) "
                f"{self._log_context(endpoint_key)} payload={safe_payload} err={e}"
            )
            raise ConnectionError(f"Network Error: {e}")

        if resp.status_code != 200:
            if 400 <= resp.status_code < 500:
                logger.error(
                    f"HTTP {resp.status_code} Client Error "
                    f"{self._log_context(endpoint_key)} payload={safe_payload} "
                    f"body={resp.text}"
                )
                raise ValueError(f"Client Error {resp.status_code}: {resp.text}")
            
            logger.warning(
                f"HTTP {resp.status_code} (Retrying...) "
                f"{self._log_context(endpoint_key)} payload={safe_payload}"
            )
            raise ConnectionError(f"HTTP {resp.status_code}")

        res_json = resp.json()
        code_val = str(res_json.get("code"))

        if code_val not in ['1', '200', '0']:
            err_msg = res_json.get('message', 'Unknown API Error')
            logger.error(
                f"Lixinren API Error {self._log_context(endpoint_key)} "
                f"message={err_msg} payload={safe_payload}"
            )
            raise RuntimeError(f"API Error: {err_msg}")

        return res_json.get("data", [])
