# config/fundamental_map.py

# ==============================================================================
# 1. 字段映射配置 (Database Column -> API JSON Path)
# ==============================================================================
# KEY: dat_fundamental_daily 表的列名
# VALUE: 理杏仁 API 返回 JSON 中的 Key (点号分隔表示层级，但在本系统中 API Key 本身就是点号连接的字符串)
# ==============================================================================

METRICS_MAPPING = {
    # --- A. 核心绝对值 (Base Values) ---
    "pe_ttm": "pe_ttm.mcw",
    "pb":     "pb.mcw",
    "ps_ttm": "ps_ttm.mcw",
    "dyr":    "dyr.mcw",

    # --- B. PE 分位点 (PE Percentiles) ---
    "pe_pos_fs":  "pe_ttm.fs.mcw.cvpos",
    "pe_pos_10y": "pe_ttm.y10.mcw.cvpos",
    "pe_pos_5y":  "pe_ttm.y5.mcw.cvpos",
    "pe_pos_3y":  "pe_ttm.y3.mcw.cvpos",

    # --- C. PB 分位点 (PB Percentiles) ---
    "pb_pos_fs":  "pb.fs.mcw.cvpos",
    "pb_pos_10y": "pb.y10.mcw.cvpos",
    "pb_pos_5y":  "pb.y5.mcw.cvpos",
    "pb_pos_3y":  "pb.y3.mcw.cvpos",

    # --- D. PS 分位点 (PS Percentiles) ---
    "ps_pos_fs":  "ps_ttm.fs.mcw.cvpos",
    "ps_pos_10y": "ps_ttm.y10.mcw.cvpos",
    "ps_pos_5y":  "ps_ttm.y5.mcw.cvpos",
    "ps_pos_3y":  "ps_ttm.y3.mcw.cvpos",

    # --- E. 股息率分位点 (DYR Percentiles) ---
    "dyr_pos_fs":  "dyr.fs.mcw.cvpos",
    "dyr_pos_10y": "dyr.y10.mcw.cvpos",
    "dyr_pos_5y":  "dyr.y5.mcw.cvpos",
    "dyr_pos_3y":  "dyr.y3.mcw.cvpos",
}

# ==============================================================================
# 2. API 请求参数生成 (Required Metrics List)
# ==============================================================================
# 根据业务需求，自动组装需要向 API 请求的 metricsList
# 规则: 
# 1. 绝对值: [metric].mcw
# 2. 统计值: [metric].[period].mcw.[cvpos|q5v|q8v|q2v]
# ==============================================================================

_BASE_METRICS = ["pe_ttm", "pb", "ps_ttm", "dyr"]
_PERIODS = ["fs", "y20", "y10", "y5", "y3"] # 虽然库表只存部分周期，但请求时可按需调整，这里对应库表
_STATS_TYPES = ["cvpos", "q5v", "q8v", "q2v"] # cvpos存列, qXv存JSON

REQUIRED_METRICS_LIST = []

# 1. 添加绝对值指标
for m in _BASE_METRICS:
    REQUIRED_METRICS_LIST.append(f"{m}.mcw")

# 2. 添加统计指标 (分位点 + 阈值)
# 注意：y20 虽然不在独立列中，但可能会放在 json 里，这里暂时只请求库表定义的周期
_DB_PERIODS = ["fs", "y10", "y5", "y3"]

for m in _BASE_METRICS:
    for p in _DB_PERIODS:
        for s in _STATS_TYPES:
            # 格式: pe_ttm.y10.mcw.cvpos
            key = f"{m}.{p}.mcw.{s}"
            REQUIRED_METRICS_LIST.append(key)

# 打印一下数量，确保没超过 API 限制 (理杏仁通常不限制指标数量，只限制频率)
# print(f"Load Metrics Config: {len(REQUIRED_METRICS_LIST)} items")