"""
SQLite测试记录系统（使用连接池）
"""

import sqlite3
import logging
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from bms_alarm_test.models.test_result import TestResult, CheckStatus
from bms_alarm_test.logger.connection_pool import DatabaseConnectionPool
from bms_alarm_test.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class TestLogger:
    """测试日志管理器"""

    def __init__(self, db_path: str = "data/test_results.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 使用连接池
        self._pool = DatabaseConnectionPool(str(self.db_path), pool_size=5)
        self._init_database()

    def _init_database(self):
        """初始化数据库表"""
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()

                # 创建测试结果表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS test_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        fault_code TEXT NOT NULL,
                        fault_name TEXT NOT NULL,
                        test_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        inner_checks_json TEXT,
                        outer_checks_json TEXT,
                        error_message TEXT,
                        bms_address INTEGER,
                        domain TEXT,
                        duration_sec REAL
                    )
                """)

                # 创建检查项表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS test_checks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        test_result_id INTEGER NOT NULL,
                        check_type TEXT NOT NULL,
                        check_domain TEXT NOT NULL,
                        expected TEXT,
                        actual TEXT,
                        passed INTEGER NOT NULL,
                        FOREIGN KEY (test_result_id) REFERENCES test_results (id) ON DELETE CASCADE
                    )
                """)

                # 创建索引
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS test_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_timestamp REAL NOT NULL,
                        end_timestamp REAL NOT NULL,
                        test_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        total_count INTEGER NOT NULL,
                        passed_count INTEGER NOT NULL,
                        failed_count INTEGER NOT NULL,
                        duration_sec REAL NOT NULL,
                        details_json TEXT NOT NULL
                    )
                """)

                cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON test_results (timestamp)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_fault_code ON test_results (fault_code)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON test_results (status)")

                conn.commit()
                logger.info(f"数据库初始化完成: {self.db_path}")

        except DatabaseError as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
        except Exception as e:
            logger.error(f"数据库初始化失败（未知错误）: {e}", exc_info=True)
            raise DatabaseError(f"数据库初始化失败: {e}") from e

    def log_test_batch(self, results: List[TestResult], test_type: str,
                       start_time: Optional[float] = None,
                       end_time: Optional[float] = None) -> Optional[int]:
        """Persist one report row for a completed fault/threshold test batch."""
        if not results:
            return None

        def to_timestamp(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            return value.timestamp()

        def result_status(result):
            value = getattr(result.overall_status, "value", result.overall_status)
            return "PASS" if value in ("PASS", "PASSED", "??") else "FAIL"

        try:
            detail_payload = [result.to_dict() for result in results]
            statuses = [result_status(result) for result in results]
            passed_count = sum(status == "PASS" for status in statuses)
            total_count = len(results)
            failed_count = total_count - passed_count
            start_candidates = [
                to_timestamp(getattr(result, "start_time", None))
                for result in results
                if getattr(result, "start_time", None) is not None
            ]
            end_candidates = [
                to_timestamp(getattr(result, "end_time", None))
                for result in results
                if getattr(result, "end_time", None) is not None
            ]
            start_timestamp = to_timestamp(start_time) or (min(start_candidates) if start_candidates else time.time())
            end_timestamp = to_timestamp(end_time) or (max(end_candidates) if end_candidates else time.time())
            duration_sec = max(0.0, end_timestamp - start_timestamp)
            details_json = json.dumps(detail_payload, ensure_ascii=False, default=str)

            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO test_runs (
                        start_timestamp, end_timestamp, test_type, status,
                        total_count, passed_count, failed_count, duration_sec, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    start_timestamp, end_timestamp, test_type,
                    "PASS" if failed_count == 0 else "FAIL",
                    total_count, passed_count, failed_count, duration_sec, details_json
                ))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"??????????: {e}", exc_info=True)
            return None

    def get_test_batches(self, limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        """Return report summaries, newest first."""
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, start_timestamp, end_timestamp, test_type, status,
                           total_count, passed_count, failed_count, duration_sec
                    FROM test_runs
                    ORDER BY start_timestamp DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                columns = [
                    "id", "start_timestamp", "end_timestamp", "test_type", "status",
                    "total_count", "passed_count", "failed_count", "duration_sec"
                ]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"??????????: {e}", exc_info=True)
            return []

    def get_test_batch(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Return one report summary with all serialized details."""
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, start_timestamp, end_timestamp, test_type, status,
                           total_count, passed_count, failed_count, duration_sec, details_json
                    FROM test_runs WHERE id = ?
                """, (run_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                return {
                    "id": row[0],
                    "start_timestamp": row[1],
                    "end_timestamp": row[2],
                    "test_type": row[3],
                    "status": row[4],
                    "total_count": row[5],
                    "passed_count": row[6],
                    "failed_count": row[7],
                    "duration_sec": row[8],
                    "details": json.loads(row[9]) if row[9] else [],
                }
        except Exception as e:
            logger.error(f"????????????: {e}", exc_info=True)
            return None

    def clear_report_batches(self) -> int:
        """Delete only the new one-row-per-batch reports."""
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM test_runs")
                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count
        except Exception as e:
            logger.error(f"??????????: {e}", exc_info=True)
            return 0

    def log_test_result(self, result: TestResult, bms_address: int = 1,
                       domain: str = "NBCMU", duration_sec: float = 0.0) -> int:
        """
        记录测试结果

        Args:
            result: 测试结果
            bms_address: BMS地址
            domain: 域类型
            duration_sec: 测试持续时间

        Returns:
            记录ID
        """
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()

                # 确定测试类型
                if result.test_type == "threshold" or (result.pid_name and "故障" not in (result.fault_name or "")):
                    test_type = "阈值"
                else:
                    test_type = "故障码"

                # 序列化检查项：非对外检查项归入 inner（含阈值测试的阈值设置/验证/恢复）
                outer_checks = [c for c in result.checks if c.check_type.name.startswith("OUTER")]
                inner_checks = [c for c in result.checks if not c.check_type.name.startswith("OUTER")]

                inner_checks_json = json.dumps([
                    {
                        "check_type": check.check_type.value,
                        "expected": check.expected_value,
                        "actual": check.actual_value,
                        "passed": check.is_passed()
                    }
                    for check in inner_checks
                ]) if inner_checks else None

                outer_checks_json = json.dumps([
                    {
                        "check_type": check.check_type.value,
                        "expected": check.expected_value,
                        "actual": check.actual_value,
                        "passed": check.is_passed()
                    }
                    for check in outer_checks
                ]) if outer_checks else None

                # 归一化状态：中文显示值 → 英文查询值（PASS/FAIL）
                status_value = result.overall_status.value
                if status_value == "通过":
                    status_value = "PASS"
                elif status_value in ("失败", "错误", "超时"):
                    status_value = "FAIL"

                # 插入测试结果
                cursor.execute("""
                    INSERT INTO test_results (
                        timestamp, fault_code, fault_name, test_type, status,
                        inner_checks_json, outer_checks_json, error_message,
                        bms_address, domain, duration_sec
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    result.start_time.timestamp() if result.start_time else time.time(),
                    str(result.metadata.get("fault_code", result.metadata.get("pid", ""))),
                    result.fault_name,
                    test_type,
                    status_value,
                    inner_checks_json,
                    outer_checks_json,
                    result.error_message,
                    bms_address,
                    domain,
                    duration_sec
                ))

                test_id = cursor.lastrowid

                # 插入检查项
                if inner_checks:
                    for check in inner_checks:
                        cursor.execute("""
                            INSERT INTO test_checks (
                                test_result_id, check_type, check_domain,
                                expected, actual, passed
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            test_id,
                            check.check_type.value,
                            "inner",
                            check.expected_value,
                            check.actual_value,
                            1 if check.is_passed() else 0
                        ))

                if outer_checks:
                    for check in outer_checks:
                        cursor.execute("""
                            INSERT INTO test_checks (
                                test_result_id, check_type, check_domain,
                                expected, actual, passed
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            test_id,
                            check.check_type.value,
                            "outer",
                            check.expected_value,
                            check.actual_value,
                            1 if check.is_passed() else 0
                        ))

                conn.commit()
                logger.debug(f"测试结果已记录: ID={test_id}")
                return test_id

        except DatabaseError as e:
            logger.error(f"记录测试结果失败: {e}")
            raise
        except Exception as e:
            logger.error(f"记录测试结果失败（未知错误）: {e}", exc_info=True)
            raise DatabaseError(f"记录测试结果失败: {e}") from e

    def get_test_results(self, limit: int = 100, offset: int = 0,
                        fault_code: Optional[str] = None,
                        status: Optional[str] = None,
                        start_time: Optional[float] = None,
                        end_time: Optional[float] = None,
                        bms_address: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        获取测试结果

        Args:
            limit: 返回数量限制
            offset: 偏移量
            fault_code: 故障码过滤
            status: 状态过滤
            start_time: 开始时间过滤
            end_time: 结束时间过滤
            bms_address: BMS地址过滤

        Returns:
            测试结果列表
        """
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()

                # 构建查询条件
                conditions = []
                params = []

                if fault_code:
                    conditions.append("fault_code = ?")
                    params.append(fault_code)

                if status:
                    conditions.append("status = ?")
                    params.append(status)

                if start_time:
                    conditions.append("timestamp >= ?")
                    params.append(start_time)

                if end_time:
                    conditions.append("timestamp <= ?")
                    params.append(end_time)

                if bms_address:
                    conditions.append("bms_address = ?")
                    params.append(bms_address)

                where_clause = " AND ".join(conditions) if conditions else "1=1"

                # 执行查询
                cursor.execute(f"""
                    SELECT
                        id, timestamp, fault_code, fault_name, test_type, status,
                        inner_checks_json, outer_checks_json, error_message,
                        bms_address, domain, duration_sec
                    FROM test_results
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """, params + [limit, offset])

                results = []
                for row in cursor.fetchall():
                    result = {
                        "id": row[0],
                        "timestamp": row[1],
                        "fault_code": row[2],
                        "fault_name": row[3],
                        "test_type": row[4],
                        "status": row[5],
                        "inner_checks": json.loads(row[6]) if row[6] else [],
                        "outer_checks": json.loads(row[7]) if row[7] else [],
                        "error_message": row[8],
                        "bms_address": row[9],
                        "domain": row[10],
                        "duration_sec": row[11]
                    }
                    results.append(result)

                return results

        except DatabaseError as e:
            logger.error(f"获取测试结果失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取测试结果失败（未知错误）: {e}", exc_info=True)
            return []

    def get_test_statistics(self, start_time: Optional[float] = None,
                           end_time: Optional[float] = None) -> Dict[str, Any]:
        """
        获取测试统计信息

        Args:
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            统计信息
        """
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()

                # 构建时间条件
                conditions = []
                params = []

                if start_time:
                    conditions.append("timestamp >= ?")
                    params.append(start_time)

                if end_time:
                    conditions.append("timestamp <= ?")
                    params.append(end_time)

                where_clause = " AND ".join(conditions) if conditions else "1=1"

                # 获取总体统计
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) as passed,
                        SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) as failed,
                        AVG(duration_sec) as avg_duration
                    FROM test_results
                    WHERE {where_clause}
                """, params)

                row = cursor.fetchone()
                total = row[0] or 0
                passed = row[1] or 0
                failed = row[2] or 0
                avg_duration = row[3] or 0.0

                # 获取按故障码统计
                cursor.execute(f"""
                    SELECT
                        fault_code,
                        fault_name,
                        COUNT(*) as count,
                        SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) as passed
                    FROM test_results
                    WHERE {where_clause}
                    GROUP BY fault_code, fault_name
                    ORDER BY count DESC
                    LIMIT 10
                """, params)

                fault_stats = []
                for fault_row in cursor.fetchall():
                    fault_stats.append({
                        "fault_code": fault_row[0],
                        "fault_name": fault_row[1],
                        "count": fault_row[2],
                        "passed": fault_row[3],
                        "pass_rate": fault_row[3] / fault_row[2] * 100 if fault_row[2] > 0 else 0
                    })

                # 获取按时间统计
                cursor.execute(f"""
                    SELECT
                        strftime('%Y-%m-%d', datetime(timestamp, 'unixepoch')) as date,
                        COUNT(*) as count,
                        SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) as passed
                    FROM test_results
                    WHERE {where_clause}
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT 7
                """, params)

                daily_stats = []
                for daily_row in cursor.fetchall():
                    daily_stats.append({
                        "date": daily_row[0],
                        "count": daily_row[1],
                        "passed": daily_row[2],
                        "pass_rate": daily_row[2] / daily_row[1] * 100 if daily_row[1] > 0 else 0
                    })

                return {
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": passed / total * 100 if total > 0 else 0,
                    "avg_duration": avg_duration,
                    "fault_statistics": fault_stats,
                    "daily_statistics": daily_stats
                }

        except DatabaseError as e:
            logger.error(f"获取测试统计失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"获取测试统计失败（未知错误）: {e}", exc_info=True)
            return {}

    def get_bms_addresses(self) -> List[int]:
        """获取数据库中出现的 BMS 地址列表（升序）"""
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT bms_address FROM test_results "
                               "WHERE bms_address IS NOT NULL ORDER BY bms_address")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取BMS地址列表失败: {e}")
            return []

    def clear_all(self) -> int:
        """
        清空全部测试记录（含检查项表）

        Returns:
            删除的记录数
        """
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM test_checks")
                cursor.execute("DELETE FROM test_results")
                cursor.execute("DELETE FROM test_runs")
                deleted_count = cursor.rowcount
                conn.commit()
                logger.info(f"已清空全部测试记录: {deleted_count} 条")
                return deleted_count
        except DatabaseError as e:
            logger.error(f"清空测试记录失败: {e}")
            return 0
        except Exception as e:
            logger.error(f"清空测试记录失败（未知错误）: {e}", exc_info=True)
            return 0

    def export_to_csv(self, output_path: str, start_time: Optional[float] = None,
                     end_time: Optional[float] = None) -> bool:
        """
        导出测试结果到CSV

        Args:
            output_path: 输出文件路径
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            是否成功
        """
        try:
            import csv

            # 获取测试结果
            results = self.get_test_results(limit=10000, start_time=start_time, end_time=end_time)

            if not results:
                logger.warning("没有测试结果可导出")
                return False

            # 写入CSV文件
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "时间", "故障码", "故障名称", "测试类型", "状态",
                    "BMS地址", "域类型", "持续时间(秒)", "错误信息"
                ])

                writer.writeheader()

                for result in results:
                    # 格式化时间
                    dt = datetime.fromtimestamp(result["timestamp"])
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

                    writer.writerow({
                        "时间": time_str,
                        "故障码": result["fault_code"],
                        "故障名称": result["fault_name"],
                        "测试类型": result["test_type"],
                        "状态": result["status"],
                        "BMS地址": result["bms_address"],
                        "域类型": result["domain"],
                        "持续时间(秒)": f"{result['duration_sec']:.2f}",
                        "错误信息": result["error_message"] or ""
                    })

            logger.info(f"测试结果已导出到: {output_path}")
            return True

        except DatabaseError as e:
            logger.error(f"导出CSV失败: {e}")
            return False
        except Exception as e:
            logger.error(f"导出CSV失败（未知错误）: {e}", exc_info=True)
            return False

    def clear_old_records(self, days_to_keep: int = 30) -> int:
        """
        清理旧记录

        Args:
            days_to_keep: 保留天数

        Returns:
            删除的记录数
        """
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()

                # 计算截止时间
                cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 3600)

                # 删除旧记录
                cursor.execute("DELETE FROM test_results WHERE timestamp < ?", (cutoff_time,))
                deleted_count = cursor.rowcount

                conn.commit()

                if deleted_count > 0:
                    logger.info(f"清理了 {deleted_count} 条旧记录（保留 {days_to_keep} 天）")

                return deleted_count

        except DatabaseError as e:
            logger.error(f"清理旧记录失败: {e}")
            return 0
        except Exception as e:
            logger.error(f"清理旧记录失败（未知错误）: {e}", exc_info=True)
            return 0

    def close(self):
        """关闭数据库连接池"""
        self._pool.close_all()
        logger.debug("数据库连接池已关闭")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
