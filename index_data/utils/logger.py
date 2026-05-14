# 文件: utils/logger.py
import logging
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from time import time
from typing import Any, Callable
from config.settings import LOG_DIR, CALC_LOG_NAME

RUNTIME_LOG_NAME = "runtime.log"
SERVICE_LOG_NAME = "service.log"
IMPORT_LOG_NAME = "import.log"
_RUNTIME_SINK_LOCK = threading.RLock()
_RUNTIME_SINKS: dict[int, Callable[[dict[str, Any]], None]] = {}
_RUNTIME_SINK_SEQ = 0


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Windows 下文件被占用时，跳过本次轮转，避免服务台持续刷 Logging error。"""

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            # reload/多进程场景下，其他进程可能仍持有日志文件句柄。
            # 跳过本次轮转并推迟到下一个周期，避免每次写日志都重复报错。
            current_time = int(time())
            self.rolloverAt = self.computeRollover(current_time)


class RuntimeLogHandler(logging.Handler):
    """将标准 logging 输出旁路复制到运行时 sink，不影响原有文件/控制台行为。"""

    def __init__(self, source: str):
        super().__init__(level=logging.INFO)
        self.source = source
        self._geniusstroke_runtime_source = source

    def emit(self, record: logging.LogRecord) -> None:
        dispatch_runtime_log_event(
            build_runtime_log_event(
                level=record.levelname,
                message=record.getMessage(),
                logger_name=record.name,
                source=self.source,
                created_at=record.created,
            )
        )


def build_runtime_log_event(
    level: str,
    message: str,
    logger_name: str,
    source: str,
    created_at: float | None = None,
) -> dict[str, Any]:
    event_time = datetime.fromtimestamp(created_at or time()).strftime("%H:%M:%S")
    return {
        "event": "log",
        "time": event_time,
        "level": level,
        "message": message,
        "logger_name": logger_name,
        "source": source,
    }


def dispatch_runtime_log_event(event: dict[str, Any]) -> None:
    with _RUNTIME_SINK_LOCK:
        sinks = list(_RUNTIME_SINKS.values())
    for sink in sinks:
        try:
            sink(dict(event))
        except Exception:
            continue


def register_runtime_log_sink(sink: Callable[[dict[str, Any]], None]) -> int:
    global _RUNTIME_SINK_SEQ
    with _RUNTIME_SINK_LOCK:
        _RUNTIME_SINK_SEQ += 1
        token = _RUNTIME_SINK_SEQ
        _RUNTIME_SINKS[token] = sink
    return token


def unregister_runtime_log_sink(token: int) -> None:
    with _RUNTIME_SINK_LOCK:
        _RUNTIME_SINKS.pop(token, None)


@contextmanager
def capture_runtime_logs(sink: Callable[[dict[str, Any]], None]):
    token = register_runtime_log_sink(sink)
    try:
        yield token
    finally:
        unregister_runtime_log_sink(token)


def _resolve_default_log_name() -> str:
    target = os.getenv("GENIUSSTROKE_LOG_TARGET", "runtime").strip().lower()
    if target == "service":
        return SERVICE_LOG_NAME
    if target == "import":
        return IMPORT_LOG_NAME
    return RUNTIME_LOG_NAME


def _build_file_handler(log_file_name: str, with_lineno: bool = True) -> TimedRotatingFileHandler:
    log_file = LOG_DIR / log_file_name
    file_handler = SafeTimedRotatingFileHandler(
        filename=log_file,
        when="MIDNIGHT",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    fmt = '%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s'
    if not with_lineno:
        fmt = '%(asctime)s | %(levelname)s | %(module)s | %(message)s'
    file_handler.setFormatter(
        logging.Formatter(fmt=fmt, datefmt='%Y-%m-%d %H:%M:%S')
    )
    return file_handler

def _create_console_handler():
    """
    创建控制台处理器 (极简模式)
    控制台只显示 message，不显示时间戳和日志级别，打造 CLI 风格体验
    """
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(
        fmt='%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    console_handler._geniusstroke_console = True
    return console_handler


def _ensure_runtime_handler(target_logger: logging.Logger, source: str) -> None:
    for handler in target_logger.handlers:
        if (
            isinstance(handler, RuntimeLogHandler)
            and getattr(handler, "_geniusstroke_runtime_source", None) == source
        ):
            return
    target_logger.addHandler(RuntimeLogHandler(source))


def write_console_lines(*lines: str, source: str = "asset_refresh_console") -> None:
    """向当前控制台逐行输出纯文本，不影响文件日志。"""
    for line in lines:
        print(line)
        dispatch_runtime_log_event(
            build_runtime_log_event(
                level="INFO",
                message=line,
                logger_name="console",
                source=source,
            )
        )


def setup_logger(name="GeniusStroke", log_file_name: str | None = None):
    """配置通用日志器，默认按进程角色写入不同日志文件。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        # 1. 控制台输出 (极简)
        logger.addHandler(_create_console_handler())

        # 2. 文件输出 (详细) - 保留时间、级别、行号，用于排查问题
        logger.addHandler(_build_file_handler(log_file_name or _resolve_default_log_name()))

    _ensure_runtime_handler(logger, "main_logger")

    return logger

def get_calc_logger(name="GeniusStroke_Calc"):
    """
    [v2.1] 计算层独立日志 (calculation.log)
    """
    calc_logger = logging.getLogger(name)
    calc_logger.setLevel(logging.INFO)
    
    if not calc_logger.handlers:
        # 1. 控制台输出 (极简)
        calc_logger.addHandler(_create_console_handler())
        
        # 2. 独立文件输出 (详细)
        calc_logger.addHandler(_build_file_handler(CALC_LOG_NAME, with_lineno=False))
    _ensure_runtime_handler(calc_logger, "calc_logger")
    return calc_logger


def get_import_logger(name: str = "GeniusStroke_Import") -> logging.Logger:
    """
    [v2.6] 导入脚本独立日志 (import.log)
    
    避免与主应用 app.log 冲突，支持独立的日志轮转。
    
    :param name: 日志器名称
    :return: 配置好的 Logger 实例
    """
    import_logger = logging.getLogger(name)
    import_logger.setLevel(logging.INFO)
    
    if not import_logger.handlers:
        # 1. 控制台输出 (极简)
        import_logger.addHandler(_create_console_handler())
        
        # 2. 独立文件输出 (详细)
        import_logger.addHandler(_build_file_handler(IMPORT_LOG_NAME))
    _ensure_runtime_handler(import_logger, "import_logger")
    
    return import_logger


def configure_uvicorn_file_logging(log_file_name: str = SERVICE_LOG_NAME) -> None:
    """为 uvicorn access/error 日志追加文件输出，保留现有控制台行为。"""
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        target_logger = logging.getLogger(logger_name)
        target_logger.setLevel(logging.INFO)
        if any(
            isinstance(handler, TimedRotatingFileHandler)
            and getattr(handler, "baseFilename", "").endswith(log_file_name)
            for handler in target_logger.handlers
        ):
            continue
        target_logger.addHandler(_build_file_handler(log_file_name))


class _MessageBlockFilter(logging.Filter):
    def __init__(self, blocked_fragments: list[str]):
        super().__init__()
        self.blocked_fragments = [item for item in blocked_fragments if item]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(fragment in message for fragment in self.blocked_fragments)


@contextmanager
def suppress_console_messages(blocked_fragments: list[str], logger_name: str = "GeniusStroke"):
    """临时屏蔽指定日志器在控制台上的部分消息，不影响文件输出。"""
    target_logger = logging.getLogger(logger_name)
    console_handlers = [
        handler
        for handler in target_logger.handlers
        if getattr(handler, "_geniusstroke_console", False)
    ]
    message_filter = _MessageBlockFilter(blocked_fragments)
    for handler in console_handlers:
        handler.addFilter(message_filter)
    try:
        yield
    finally:
        for handler in console_handlers:
            handler.removeFilter(message_filter)


# 全局单例
logger = setup_logger()
