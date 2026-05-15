# GeniusStroke

GeniusStroke 是一个本地运行的投资数据看板与 API 服务，用于管理行情、基本面、技术指标、组合持仓、交易记录和账户视图。

当前公开版面向 Windows、本地 Python 3.12 与 PowerShell 使用场景。默认只监听 `127.0.0.1:8002`，不会对外网开放服务。

## 许可证

本项目使用 MIT License 发布，详见 [LICENSE](LICENSE)。

## 快速开始

在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python scripts\init_empty_db.py
.\scripts\run_local.ps1
```

启动后访问：

```text
http://127.0.0.1:8002
```

健康检查：

```text
http://127.0.0.1:8002/health
```

## 配置

本地配置文件是 `.env`。请先从 `.env.example` 复制：

```powershell
Copy-Item .env.example .env
```

外部数据源 token 默认留空。基础启动不需要 token；需要调用理杏仁等外部数据源能力时，再填写对应变量，例如 `LIXINREN_TOKEN`。

## 本地检查

服务启动后可以运行：

```powershell
.\scripts\check_local.ps1
```

更多说明见 [快速开始](docs/quickstart.md) 和 [配置说明](docs/configuration.md)。
