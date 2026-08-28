"""
测试结果数据模型
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime


class CheckType(Enum):
    """检查类型"""
    FAULT_INJECTION = "故障注入"
    FAULT_CLEAR = "故障清除"
    INTERNAL_VERIFICATION = "内部验证"
    EXTERNAL_VERIFICATION = "外部验证"
    THRESHOLD_SET = "阈值设置"
    THRESHOLD_VERIFICATION = "阈值验证"
    THRESHOLD_RESTORE = "阈值恢复"
    CAN_COMMUNICATION = "CAN通信"
    TIMEOUT = "超时"
    OTHER = "其他"
    
    # 向后兼容别名（旧代码使用的内部/外部检查类型）
    INNER_SYS_FAIL_STA = "内部系统故障状态"
    INNER_ERR_TAB = "内部错误表"
    INNER_SPECIFIC = "内部特定故障"
    OUTER_SPECIFIC = "外部特定故障"
    OUTER_WARNING = "外部告警"
    OUTER_SYS_FAIL_STA = "外部系统故障状态"


class CheckStatus(Enum):
    """检查状态"""
    PENDING = "待执行"
    RUNNING = "执行中"
    PASSED = "通过"
    FAILED = "失败"
    SKIPPED = "跳过"
    ERROR = "错误"
    TIMEOUT = "超时"
    
    # 向后兼容别名
    PASS = PASSED
    FAIL = FAILED


@dataclass
class Check:
    """检查项"""
    
    name: str = ""
    check_type: CheckType = CheckType.OTHER
    description: str = ""
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None
    tolerance: Optional[float] = None
    status: CheckStatus = CheckStatus.PENDING
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0  # 耗时(秒)
    
    def __post_init__(self):
        """后初始化处理"""
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError("容差必须为非负数")
    
    def start(self) -> None:
        """开始检查"""
        self.status = CheckStatus.RUNNING
        self.timestamp = datetime.now()
        self.message = ""
    
    def complete(self, passed: bool, actual_value: Any = None, message: str = "") -> None:
        """
        完成检查
        
        Args:
            passed: 是否通过
            actual_value: 实际值
            message: 消息
        """
        self.actual_value = actual_value
        self.message = message
        self.duration = (datetime.now() - self.timestamp).total_seconds()
        
        if passed:
            self.status = CheckStatus.PASSED
        else:
            self.status = CheckStatus.FAILED
    
    def fail(self, message: str = "", actual_value: Any = None) -> None:
        """标记为失败"""
        self.complete(False, actual_value=actual_value, message=message)

    def pass_check(self, message: str = "", actual_value: Any = None) -> None:
        """标记为通过"""
        self.complete(True, actual_value=actual_value, message=message)
    
    def skip(self, reason: str = "") -> None:
        """跳过检查"""
        self.status = CheckStatus.SKIPPED
        self.message = reason
        self.timestamp = datetime.now()
    
    def error(self, error_message: str = "") -> None:
        """标记为错误"""
        self.status = CheckStatus.ERROR
        self.message = error_message
        self.duration = (datetime.now() - self.timestamp).total_seconds()
    
    def timeout(self) -> None:
        """标记为超时"""
        self.status = CheckStatus.TIMEOUT
        self.message = "检查超时"
        self.duration = (datetime.now() - self.timestamp).total_seconds()
    
    def is_completed(self) -> bool:
        """检查是否已完成"""
        return self.status in [CheckStatus.PASSED, CheckStatus.FAILED, 
                              CheckStatus.SKIPPED, CheckStatus.ERROR, CheckStatus.TIMEOUT]
    
    def is_passed(self) -> bool:
        """检查是否通过"""
        return self.status == CheckStatus.PASSED
    
    def is_failed(self) -> bool:
        """检查是否失败"""
        return self.status == CheckStatus.FAILED
    
    def __str__(self) -> str:
        """字符串表示"""
        status_icon = {
            CheckStatus.PENDING: "⏳",
            CheckStatus.RUNNING: "🔄",
            CheckStatus.PASSED: "✅",
            CheckStatus.FAILED: "❌",
            CheckStatus.SKIPPED: "⏭️",
            CheckStatus.ERROR: "⚠️",
            CheckStatus.TIMEOUT: "⏰"
        }.get(self.status, "❓")
        
        return f"{status_icon} {self.name}: {self.status.value}"


@dataclass
class TestResult:
    """测试结果"""
    
    test_id: str
    test_type: str  # "fault" 或 "threshold"
    fault_name: Optional[str] = None
    pid_name: Optional[str] = None
    bms_address: int = 1
    domain_type: str = "NBCMU"  # "NBCMU" 或 "SBCMU"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    checks: List[Check] = field(default_factory=list)
    overall_status: CheckStatus = CheckStatus.PENDING
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """后初始化处理"""
        # 生成测试ID（如果未提供）
        if not self.test_id:
            timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
            if self.test_type == "fault" and self.fault_name:
                self.test_id = f"fault_{self.fault_name}_{timestamp}"
            elif self.test_type == "threshold" and self.pid_name:
                self.test_id = f"threshold_{self.pid_name}_{timestamp}"
            else:
                self.test_id = f"{self.test_type}_{timestamp}"
    
    def add_check(self, check: Check) -> None:
        """添加检查项"""
        self.checks.append(check)
    
    def start(self) -> None:
        """开始测试"""
        self.overall_status = CheckStatus.RUNNING
        self.start_time = datetime.now()
        self.end_time = None
        self.error_message = ""
    
    def complete(self) -> None:
        """完成测试"""
        self.end_time = datetime.now()
        
        # 计算总体状态
        if not self.checks:
            self.overall_status = CheckStatus.PASSED
            return
        
        # 检查是否有失败的检查
        failed_checks = [c for c in self.checks if c.is_failed()]
        if failed_checks:
            self.overall_status = CheckStatus.FAILED
            return
        
        # 检查是否有错误的检查
        error_checks = [c for c in self.checks if c.status == CheckStatus.ERROR]
        if error_checks:
            self.overall_status = CheckStatus.ERROR
            return
        
        # 检查是否有超时的检查
        timeout_checks = [c for c in self.checks if c.status == CheckStatus.TIMEOUT]
        if timeout_checks:
            self.overall_status = CheckStatus.TIMEOUT
            return
        
        # 检查是否所有检查都通过
        all_passed = all(c.is_passed() for c in self.checks if c.is_completed())
        if all_passed:
            self.overall_status = CheckStatus.PASSED
        else:
            self.overall_status = CheckStatus.FAILED
    
    def fail(self, error_message: str = "") -> None:
        """标记测试为失败"""
        self.overall_status = CheckStatus.FAILED
        self.error_message = error_message
        self.end_time = datetime.now()
    
    def get_duration(self) -> float:
        """获取测试耗时(秒)"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_passed_checks(self) -> List[Check]:
        """获取通过的检查"""
        return [c for c in self.checks if c.is_passed()]
    
    def get_failed_checks(self) -> List[Check]:
        """获取失败的检查"""
        return [c for c in self.checks if c.is_failed()]
    
    def get_passed_count(self) -> int:
        """获取通过的检查数量"""
        return len(self.get_passed_checks())
    
    def get_failed_count(self) -> int:
        """获取失败的检查数量"""
        return len(self.get_failed_checks())
    
    def get_total_count(self) -> int:
        """获取总检查数量"""
        return len(self.checks)
    
    def get_pass_rate(self) -> float:
        """获取通过率"""
        total = self.get_total_count()
        if total == 0:
            return 0.0
        return self.get_passed_count() / total * 100
    
    def is_completed(self) -> bool:
        """检查测试是否已完成"""
        return self.overall_status in [CheckStatus.PASSED, CheckStatus.FAILED, 
                                      CheckStatus.ERROR, CheckStatus.TIMEOUT]
    
    def is_passed(self) -> bool:
        """检查测试是否通过"""
        return self.overall_status == CheckStatus.PASSED
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "test_id": self.test_id,
            "test_type": self.test_type,
            "fault_name": self.fault_name,
            "pid_name": self.pid_name,
            "bms_address": self.bms_address,
            "domain_type": self.domain_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.get_duration(),
            "overall_status": self.overall_status.value,
            "error_message": self.error_message,
            "passed_count": self.get_passed_count(),
            "failed_count": self.get_failed_count(),
            "total_count": self.get_total_count(),
            "pass_rate": self.get_pass_rate(),
            "checks": [
                {
                    "name": c.name,
                    "type": c.check_type.value,
                    "description": c.description,
                    "status": c.status.value,
                    "expected_value": c.expected_value,
                    "actual_value": c.actual_value,
                    "message": c.message,
                    "timestamp": c.timestamp.isoformat(),
                    "duration": c.duration
                }
                for c in self.checks
            ],
            "metadata": self.metadata
        }
    
    def __str__(self) -> str:
        """字符串表示"""
        status_icon = {
            CheckStatus.PENDING: "⏳",
            CheckStatus.RUNNING: "🔄",
            CheckStatus.PASSED: "✅",
            CheckStatus.FAILED: "❌",
            CheckStatus.ERROR: "⚠️",
            CheckStatus.TIMEOUT: "⏰"
        }.get(self.overall_status, "❓")
        
        duration = self.get_duration()
        passed = self.get_passed_count()
        total = self.get_total_count()
        
        if self.test_type == "fault":
            name = self.fault_name or "未知故障"
        else:
            name = self.pid_name or "未知PID"
        
        return f"{status_icon} {name}: {self.overall_status.value} ({passed}/{total} 通过, {duration:.1f}s)"


@dataclass
class BatchTestResult:
    """批量测试结果"""
    
    batch_id: str
    test_type: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    test_results: List[TestResult] = field(default_factory=list)
    overall_status: CheckStatus = CheckStatus.PENDING
    error_message: str = ""
    
    def __post_init__(self):
        """后初始化处理"""
        if not self.batch_id:
            timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
            self.batch_id = f"batch_{self.test_type}_{timestamp}"
    
    def add_test_result(self, result: TestResult) -> None:
        """添加测试结果"""
        self.test_results.append(result)
    
    def start(self) -> None:
        """开始批量测试"""
        self.overall_status = CheckStatus.RUNNING
        self.start_time = datetime.now()
        self.end_time = None
        self.error_message = ""
    
    def complete(self) -> None:
        """完成批量测试"""
        self.end_time = datetime.now()
        
        if not self.test_results:
            self.overall_status = CheckStatus.PASSED
            return
        
        # 计算总体状态
        failed_tests = [t for t in self.test_results if not t.is_passed()]
        if failed_tests:
            self.overall_status = CheckStatus.FAILED
        else:
            self.overall_status = CheckStatus.PASSED
    
    def get_duration(self) -> float:
        """获取批量测试耗时(秒)"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_passed_tests(self) -> List[TestResult]:
        """获取通过的测试"""
        return [t for t in self.test_results if t.is_passed()]
    
    def get_failed_tests(self) -> List[TestResult]:
        """获取失败的测试"""
        return [t for t in self.test_results if not t.is_passed()]
    
    def get_passed_count(self) -> int:
        """获取通过的测试数量"""
        return len(self.get_passed_tests())
    
    def get_failed_count(self) -> int:
        """获取失败的测试数量"""
        return len(self.get_failed_tests())
    
    def get_total_count(self) -> int:
        """获取总测试数量"""
        return len(self.test_results)
    
    def get_pass_rate(self) -> float:
        """获取通过率"""
        total = self.get_total_count()
        if total == 0:
            return 0.0
        return self.get_passed_count() / total * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "batch_id": self.batch_id,
            "test_type": self.test_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.get_duration(),
            "overall_status": self.overall_status.value,
            "error_message": self.error_message,
            "passed_count": self.get_passed_count(),
            "failed_count": self.get_failed_count(),
            "total_count": self.get_total_count(),
            "pass_rate": self.get_pass_rate(),
            "test_results": [r.to_dict() for r in self.test_results]
        }
    
    def __str__(self) -> str:
        """字符串表示"""
        status_icon = {
            CheckStatus.PENDING: "⏳",
            CheckStatus.RUNNING: "🔄",
            CheckStatus.PASSED: "✅",
            CheckStatus.FAILED: "❌",
            CheckStatus.ERROR: "⚠️",
            CheckStatus.TIMEOUT: "⏰"
        }.get(self.overall_status, "❓")
        
        duration = self.get_duration()
        passed = self.get_passed_count()
        total = self.get_total_count()
        
        return f"{status_icon} 批量测试: {self.overall_status.value} ({passed}/{total} 通过, {duration:.1f}s)"