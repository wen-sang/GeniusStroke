# 文件: api/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
os.environ.setdefault("GENIUSSTROKE_LOG_TARGET", "service")

# 导入路由
from api.routers import (
    market,
    fundamental,
    indicator,
    trade,
    trade_orders,
    account,
    assets,
    corporate_action,
    account_ledger,
)
from config.settings import APP_NAME, ENABLE_DATA_SYNC_API, ENV, HOST, PORT, RELOAD, VERSION
from utils.logger import configure_uvicorn_file_logging

if ENABLE_DATA_SYNC_API:
    from api.routers import data_sync

# 创建 FastAPI 应用
app = FastAPI(
    title=f"{APP_NAME} 数据看板 API ({ENV.upper()})",
    description="提供行情、基本面、技术指标、交易管理的 REST API",
    version=VERSION
)
configure_uvicorn_file_logging()

# 注册路由
app.include_router(market.router)
app.include_router(fundamental.router)
app.include_router(indicator.router)
app.include_router(trade.router)
app.include_router(trade_orders.router)
app.include_router(account.router)
app.include_router(assets.router)
app.include_router(corporate_action.router)
app.include_router(account_ledger.router)
if ENABLE_DATA_SYNC_API:
    app.include_router(data_sync.router)

# 获取项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
async def root():
    """返回前端首页"""
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "ok",
        "message": "GeniusStroke API is running",
        "environment": ENV,
        "version": VERSION,
        "port": PORT
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(app, host=HOST, port=PORT, reload=RELOAD)

