# 文件: core/db_engine.py
import sqlite3
import threading
from contextlib import contextmanager
from config.settings import DB_PATH, DB_TIMEOUT
from utils.logger import logger
from utils.exceptions import DatabaseError
from utils.validators import ValidationError


class DatabaseEngine:
    def __init__(self):
        # [跨平台优化] 强制转换为字符串路径
        self.db_path = str(DB_PATH)
        self._read_conn = None
        self._read_conn_path = None
        self._read_lock = threading.Lock()
        self._wal_lock = threading.Lock()
        self._wal_initialized = False

    def _open_connection(self, isolation_level="", check_same_thread=True):
        """创建 SQLite 连接。"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=DB_TIMEOUT,
            isolation_level=isolation_level,
            check_same_thread=check_same_thread,
        )
        try:
            conn.execute("PRAGMA foreign_keys=ON;")
            return conn
        except Exception:
            conn.close()
            raise

    def _close_read_connection_if_needed(self):
        """关闭当前复用的只读连接。"""
        if self._read_conn is not None:
            self._read_conn.close()
            self._read_conn = None
            self._read_conn_path = None

    def _ensure_wal_mode(self):
        """确保数据库已开启 WAL 模式（只需执行一次）"""
        if self._wal_initialized:
            return

        with self._wal_lock:
            if self._wal_initialized:
                return
            conn = self._open_connection()
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.commit()
                self._wal_initialized = True
            finally:
                conn.close()

    def _create_read_connection(self):
        """创建并配置可复用的只读连接。"""
        conn = self._open_connection(
            isolation_level=None,    # 自动提交，避免读事务长时间持有旧快照
            check_same_thread=False,  # 允许跨线程复用
        )
        conn.execute("PRAGMA query_only=1;")
        return conn

    def _should_refresh_read_connection(self):
        """判断是否需要重建只读连接。"""
        return self._read_conn is None or self._read_conn_path != self.db_path

    def _create_write_connection(self):
        """创建写连接，并确保 WAL 模式已启用。"""
        self._ensure_wal_mode()
        return self._open_connection()

    def _rollback_write_connection(self, conn):
        """写连接异常时执行回滚。"""
        conn.rollback()

    def _raise_write_error(self, error):
        """统一记录并转换写连接异常。"""
        if isinstance(error, ValidationError):
            raise error
        if isinstance(error, sqlite3.IntegrityError):
            logger.error(f"Database integrity constraint violation: {error}")
            raise DatabaseError(f"Data integrity violation: {error}") from error
        if isinstance(error, sqlite3.OperationalError):
            logger.error(f"Database operational error: {error}")
            raise DatabaseError(f"Database operation failed: {error}") from error
        logger.error(f"Unexpected database error: {error}")
        raise DatabaseError(f"Database error: {error}") from error

    def get_read_connection(self):
        """
        获取只读连接（线程安全，可复用）

        性能优化：复用连接减少创建/关闭开销
        适用于查询操作，不支持事务
        """
        with self._read_lock:
            if self._should_refresh_read_connection():
                self._close_read_connection_if_needed()
                self._read_conn = self._create_read_connection()
                self._read_conn_path = self.db_path
            return self._read_conn

    @contextmanager
    def get_connection(self, readonly=False):
        """
        获取数据库连接的上下文管理器

        :param readonly: 是否为只读操作，True 时复用连接
        """
        if readonly:
            conn = self.get_read_connection()
            try:
                yield conn
            except Exception as error:
                logger.error(f"Database Query Error: {error}")
                raise
        else:
            conn = self._create_write_connection()
            try:
                yield conn
                conn.commit()
            except Exception as error:
                self._rollback_write_connection(conn)
                self._raise_write_error(error)
            finally:
                conn.close()

    def close(self):
        """关闭复用的只读连接（程序退出时调用）"""
        with self._read_lock:
            self._close_read_connection_if_needed()

    def execute_script(self, sql_script: str):
        """执行多条 SQL 脚本"""
        with self.get_connection() as conn:  # 写操作
            cursor = conn.cursor()
            cursor.executescript(sql_script)
            logger.info("SQL script executed successfully.")


# 全局单例
db_engine = DatabaseEngine()
