"""
数据库连接池
SQLite连接池，提高数据库操作性能
"""

import sqlite3
import logging
import threading
from typing import Optional
from contextlib import contextmanager
from queue import Queue, Full, Empty
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseConnectionPool:
    """SQLite连接池"""

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = str(Path(db_path).resolve())
        self.pool_size = pool_size
        self._pool: Queue = Queue(maxsize=pool_size)
        self._created_connections = 0
        self._lock = threading.Lock()

        # 初始化连接池
        self._initialize_pool()

    def _initialize_pool(self):
        """初始化连接池"""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self._pool.put(conn)
            self._created_connections += 1

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def get_connection(self, timeout: float = 5.0):
        """获取连接（上下文管理器）"""
        conn = None
        try:
            conn = self._pool.get(timeout=timeout)
            yield conn
        except Empty:
            # 池中无连接，创建临时连接
            logger.warning("连接池耗尽，创建临时连接")
            conn = self._create_connection()
            try:
                yield conn
            finally:
                # 临时连接用完即关
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception:
            if conn:
                self._return_connection(conn)
            raise
        else:
            self._return_connection(conn)

    def _return_connection(self, conn: sqlite3.Connection):
        """归还连接到池"""
        try:
            self._pool.put_nowait(conn)
        except Full:
            # 池已满，关闭连接
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created_connections -= 1

    def close_all(self):
        """关闭所有连接"""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
        logger.info("连接池已关闭")

    def get_stats(self) -> dict:
        """获取连接池统计"""
        return {
            "pool_size": self.pool_size,
            "available": self._pool.qsize(),
            "created": self._created_connections,
        }
