"""
日志与测试记录定时清理模块
- 删除超过保留天数的旧日志文件
- 超大日志文件（超过大小上限）直接删除，避免单文件无限膨胀占用磁盘
  （bms_test.log / can_driver.log 每次运行都以 mode='w' 重新打开，旧内容无保留价值；
   运行中的文件因 Windows 占用会删除失败，被安全跳过）
- 清理数据库中超过保留天数的旧测试记录
"""

import logging
import os
import time
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def cleanup_log_directory(
    log_dir: str,
    days_to_keep: int = 7,
    max_file_size_mb: float = 100.0,
) -> Tuple[int, int]:
    """
    清理日志目录

    Args:
        log_dir: 日志目录路径
        days_to_keep: 保留天数，超过该天数的 .log/.log.* 文件将被删除
        max_file_size_mb: 单文件大小上限（MB），超过上限的文件将被删除

    Returns:
        (删除的文件数, 释放的字节数)
    """
    log_path = Path(log_dir)
    if not log_path.is_dir():
        return 0, 0

    cutoff = time.time() - days_to_keep * 24 * 3600
    max_bytes = int(max_file_size_mb * 1024 * 1024)

    deleted = 0
    freed = 0

    for f in log_path.iterdir():
        if not f.is_file():
            continue
        # 只处理日志文件（含 .log 及 .log.1/.log.YYYYMMDD 等轮转文件）
        if not (f.suffix == '.log' or '.log.' in f.name or f.name.endswith('.log')):
            continue

        try:
            size = f.stat().st_size
            mtime = f.stat().st_mtime

            # 1) 超过保留天数 → 删除
            if mtime < cutoff:
                f.unlink()
                deleted += 1
                freed += size
                logger.info(f"清理过期日志: {f.name} ({size/1024:.0f} KB)")
                continue

            # 2) 未过期但文件过大 → 直接删除（运行中文件会因占用失败而被跳过）
            if max_bytes > 0 and size > max_bytes:
                try:
                    f.unlink()
                    deleted += 1
                    freed += size
                    logger.info(f"清理超大日志: {f.name} ({size/1024/1024:.1f} MB)")
                except OSError as e:
                    logger.warning(f"日志文件被占用，跳过: {f.name}: {e}")
        except OSError as e:
            logger.warning(f"处理日志文件失败: {f.name}: {e}")

    return deleted, freed


def cleanup_old_records(db_path: str = "data/test_results.db", days_to_keep: int = 7) -> int:
    """
    清理数据库中超过保留天数的测试记录

    Args:
        db_path: 数据库文件路径
        days_to_keep: 保留天数

    Returns:
        删除的记录数（失败时返回 -1）
    """
    try:
        from bms_alarm_test.logger.test_logger import TestLogger

        test_logger = TestLogger(db_path)
        try:
            return test_logger.clear_old_records(days_to_keep=days_to_keep)
        finally:
            test_logger.close()
    except Exception as e:
        logger.warning(f"清理测试记录失败: {e}")
        return -1


def run_cleanup(
    log_dir: str = "logs",
    db_path: str = "data/test_results.db",
    days_to_keep: int = 7,
    max_file_size_mb: float = 100.0,
) -> dict:
    """
    执行一次完整清理（日志 + 数据库记录）

    Returns:
        清理结果摘要字典
    """
    deleted, freed = cleanup_log_directory(log_dir, days_to_keep, max_file_size_mb)
    db_deleted = cleanup_old_records(db_path, days_to_keep)

    summary = {
        "deleted_logs": deleted,
        "freed_bytes": freed,
        "deleted_db_records": db_deleted,
        "days_to_keep": days_to_keep,
    }
    logger.info(
        f"清理完成: 删除日志 {deleted} 个, 释放 {freed/1024/1024:.1f} MB, "
        f"清理数据库记录 {db_deleted} 条"
    )
    return summary
