# 配置说明

启动服务前，请先复制 `.env.example` 为 `.env`：

```powershell
Copy-Item .env.example .env
```

## 安全默认值

`.env.example` 默认面向本地运行：

```env
ENV=public
HOST=127.0.0.1
PORT=8002
RELOAD=false
ENABLE_IMPORT_REBUILD_API=false
ENABLE_DATA_SYNC_API=false
MANAGEMENT_API_TOKEN=
```

服务默认只监听 `127.0.0.1`。

## 数据库与日志

运行时文件会在本地生成，并被 Git 忽略：

```env
DATA_DIR=../data
LOG_DIR=../logs
DB_NAME=GeniusStroke_v2.db
```

## 外部数据源 Token

Token 相关变量默认留空：

```env
LIXINREN_MODE=global
LIXINREN_TOKEN=
LIXINREN_TOKEN_DAILY_BAR=
LIXINREN_TOKEN_FUNDAMENTAL=
LIXINREN_TOKEN_NET_VALUE=
TICKFLOW_API_KEY=
TICKFLOW_ADJUST=none
TICKFLOW_TIMEOUT_SECONDS=60
TICKFLOW_MAX_RETRIES=3
TICKFLOW_REQUEST_SLEEP_SECONDS=0.2
TICKFLOW_KLINE_COUNT_LIMIT=10000
```

基础启动不需要这些 token。只有使用对应外部数据源能力时，才需要填写相关变量。

TickFlow 行情采集支持两种模式：

- `TICKFLOW_API_KEY` 留空：使用 TickFlow 免费模式。
- `TICKFLOW_API_KEY` 填写注册版 key：使用注册版客户端。

`TICKFLOW_ADJUST` 默认 `none`，表示 V2 首版按不复权日线采集。
`TICKFLOW_KLINE_COUNT_LIMIT` 默认 `10000`，与 TickFlow 单次单标的 K 线数量限制保持一致。
`TICKFLOW_REQUEST_SLEEP_SECONDS` 用于正式行情采集时的 TickFlow 单标的请求间隔。
