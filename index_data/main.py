# 文件: main.py
import os
import sys
import webbrowser
from pathlib import Path

# ==============================================================================
# [跨平台启动引导]
# 在导入任何内部模块前，先将项目根目录加入系统路径
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("GENIUSSTROKE_LOG_TARGET", "runtime")

from config import settings
from core.db_engine import db_engine
from core.sync_models import SyncTaskStatus
from core.sync_runner import sync_runner
from utils.logger import logger


def resolve_exit_code(status: SyncTaskStatus) -> int:
    """CLI 兼容口径：仅硬失败返回非零退出码。"""
    if status == SyncTaskStatus.FAILED:
        return 1
    return 0


def maybe_open_dashboard() -> None:
    dashboard_url = settings.DASHBOARD_URL
    if not dashboard_url:
        return

    try:
        logger.info(f"正在打开看板地址: {dashboard_url}")
        webbrowser.open(dashboard_url)
    except Exception as exc:
        logger.error(f"打开看板失败: {exc}", exc_info=True)


def main() -> int:
    try:
        result = sync_runner.run()
        if result.status != SyncTaskStatus.FAILED:
            maybe_open_dashboard()
        return resolve_exit_code(result.status)
    finally:
        # CLI 场景下，进程退出前可释放全局只读连接；服务化调用不走这里。
        db_engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
