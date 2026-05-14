# Configuration

Copy `.env.example` to `.env` before starting the service.

## Safe Defaults

The default `.env.example` values are intended for local use:

```env
ENV=public
HOST=127.0.0.1
PORT=8002
RELOAD=false
ENABLE_IMPORT_REBUILD_API=false
ENABLE_DATA_SYNC_API=false
MANAGEMENT_API_TOKEN=
```

The service listens only on `127.0.0.1` by default.

## Database and Logs

Runtime files are created locally and are ignored by Git:

```env
DATA_DIR=../data
LOG_DIR=../logs
DB_NAME=GeniusStroke_v2.db
```

## External Data Source Tokens

Token variables are empty by default:

```env
LIXINREN_MODE=global
LIXINREN_TOKEN=
LIXINREN_TOKEN_DAILY_BAR=
LIXINREN_TOKEN_FUNDAMENTAL=
LIXINREN_TOKEN_NET_VALUE=
```

Basic startup does not require these tokens. Fill them only when you need the related external data source features.
