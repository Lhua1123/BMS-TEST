"""
故障数据模型
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


from bms_alarm_test.config.constants import BMSAddressConstants

class FaultType(Enum):
    """故障类型"""
    NBCMU = "NBCMU"  # 非电池管理单元故障
    SBCMU = "SBCMU"  # 电池管理单元故障
    COMMON = "COMMON"  # 共有故障


class FaultSeverity(Enum):
    """故障严重程度"""
    INFO = "信息"
    WARNING = "警告"
    ERROR = "错误"
    CRITICAL = "严重"


@dataclass
class FaultSignal:
    """故障信号定义"""
    
    name: str
    message_name: str
    signal_name: str
    expected_value: Any
    tolerance: Optional[float] = None
    description: str = ""
    channel: str = "CH1"  # "CH1" 或 "CH2"
    
    def __post_init__(self):
        """后初始化处理"""
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError("容差必须为非负数")
    
    def matches(self, actual_value: Any) -> bool:
        """
        检查实际值是否匹配期望值
        
        Args:
            actual_value: 实际值
            
        Returns:
            是否匹配
        """
        if self.tolerance is None:
            return actual_value == self.expected_value
        
        try:
            # 尝试数值比较
            expected = float(self.expected_value)
            actual = float(actual_value)
            return abs(actual - expected) <= self.tolerance
        except (ValueError, TypeError):
            # 非数值比较
            return actual_value == self.expected_value
    
    def __str__(self) -> str:
        """字符串表示"""
        if self.tolerance is not None:
            return f"{self.name}: {self.message_name}.{self.signal_name} = {self.expected_value} ± {self.tolerance}"
        return f"{self.name}: {self.message_name}.{self.signal_name} = {self.expected_value}"


@dataclass
class Fault:
    """故障定义"""
    
    fault_id: str
    name: str
    fault_type: FaultType
    severity: FaultSeverity
    description: str = ""
    bms_address: int = BMSAddressConstants.DEFAULT_NBCMU_ADDRESS
    domain_type: str = "NBCMU"  # "NBCMU" 或 "SBCMU"
    
    # 故障注入信号
    injection_signals: List[FaultSignal] = field(default_factory=list)
    
    # 内部验证信号（CH1）
    internal_verification_signals: List[FaultSignal] = field(default_factory=list)
    
    # 外部验证信号（CH2）
    external_verification_signals: List[FaultSignal] = field(default_factory=list)
    
    # 故障清除信号
    clear_signals: List[FaultSignal] = field(default_factory=list)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """后初始化处理"""
        # 确保BMS地址有效
        if not 1 <= self.bms_address <= 255:
            raise ValueError(f"BMS地址必须在1-255之间: {self.fault_id}")
    
    def add_injection_signal(self, signal: FaultSignal) -> None:
        """添加故障注入信号"""
        self.injection_signals.append(signal)
    
    def add_internal_verification_signal(self, signal: FaultSignal) -> None:
        """添加内部验证信号"""
        self.internal_verification_signals.append(signal)
    
    def add_external_verification_signal(self, signal: FaultSignal) -> None:
        """添加外部验证信号"""
        self.external_verification_signals.append(signal)
    
    def add_clear_signal(self, signal: FaultSignal) -> None:
        """添加故障清除信号"""
        self.clear_signals.append(signal)
    
    def get_all_signals(self) -> List[FaultSignal]:
        """获取所有信号"""
        all_signals = []
        all_signals.extend(self.injection_signals)
        all_signals.extend(self.internal_verification_signals)
        all_signals.extend(self.external_verification_signals)
        all_signals.extend(self.clear_signals)
        return all_signals
    
    def get_signals_by_channel(self, channel: str) -> List[FaultSignal]:
        """
        获取指定通道的信号
        
        Args:
            channel: 通道 ("CH1" 或 "CH2")
            
        Returns:
            信号列表
        """
        return [s for s in self.get_all_signals() if s.channel == channel]
    
    def get_injection_data(self) -> Dict[str, Dict[str, Any]]:
        """
        获取故障注入数据
        
        Returns:
            注入数据字典 {报文名: {信号名: 值}}
        """
        return self._signals_to_data(self.injection_signals)
    
    def get_clear_data(self) -> Dict[str, Dict[str, Any]]:
        """
        获取故障清除数据
        
        Returns:
            清除数据字典 {报文名: {信号名: 值}}
        """
        return self._signals_to_data(self.clear_signals)
    
    def _signals_to_data(self, signals: List[FaultSignal]) -> Dict[str, Dict[str, Any]]:
        """
        将信号列表转换为数据字典
        
        Args:
            signals: 信号列表
            
        Returns:
            数据字典 {报文名: {信号名: 值}}
        """
        data: Dict[str, Dict[str, Any]] = {}
        for signal in signals:
            if signal.message_name not in data:
                data[signal.message_name] = {}
            data[signal.message_name][signal.signal_name] = signal.expected_value
        return data
    
    def get_verification_checks(self) -> List[Dict[str, Any]]:
        """
        获取验证检查项
        
        Returns:
            检查项列表
        """
        checks = []
        
        # 内部验证检查
        for signal in self.internal_verification_signals:
            checks.append({
                "name": f"内部验证: {signal.name}",
                "type": "internal_verification",
                "message_name": signal.message_name,
                "signal_name": signal.signal_name,
                "expected_value": signal.expected_value,
                "tolerance": signal.tolerance,
                "channel": "CH1",
                "description": signal.description
            })
        
        # 外部验证检查
        for signal in self.external_verification_signals:
            checks.append({
                "name": f"外部验证: {signal.name}",
                "type": "external_verification",
                "message_name": signal.message_name,
                "signal_name": signal.signal_name,
                "expected_value": signal.expected_value,
                "tolerance": signal.tolerance,
                "channel": "CH2",
                "description": signal.description
            })
        
        return checks
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "fault_id": self.fault_id,
            "name": self.name,
            "fault_type": self.fault_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "bms_address": self.bms_address,
            "domain_type": self.domain_type,
            "injection_signals": [
                {
                    "name": s.name,
                    "message_name": s.message_name,
                    "signal_name": s.signal_name,
                    "expected_value": s.expected_value,
                    "tolerance": s.tolerance,
                    "description": s.description,
                    "channel": s.channel
                }
                for s in self.injection_signals
            ],
            "internal_verification_signals": [
                {
                    "name": s.name,
                    "message_name": s.message_name,
                    "signal_name": s.signal_name,
                    "expected_value": s.expected_value,
                    "tolerance": s.tolerance,
                    "description": s.description,
                    "channel": s.channel
                }
                for s in self.internal_verification_signals
            ],
            "external_verification_signals": [
                {
                    "name": s.name,
                    "message_name": s.message_name,
                    "signal_name": s.signal_name,
                    "expected_value": s.expected_value,
                    "tolerance": s.tolerance,
                    "description": s.description,
                    "channel": s.channel
                }
                for s in self.external_verification_signals
            ],
            "clear_signals": [
                {
                    "name": s.name,
                    "message_name": s.message_name,
                    "signal_name": s.signal_name,
                    "expected_value": s.expected_value,
                    "tolerance": s.tolerance,
                    "description": s.description,
                    "channel": s.channel
                }
                for s in self.clear_signals
            ],
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Fault':
        """从字典创建故障"""
        fault = cls(
            fault_id=data["fault_id"],
            name=data["name"],
            fault_type=FaultType(data["fault_type"]),
            severity=FaultSeverity(data["severity"]),
            description=data.get("description", ""),
            bms_address=data.get("bms_address", BMSAddressConstants.DEFAULT_NBCMU_ADDRESS),
            domain_type=data.get("domain_type", "NBCMU"),
            metadata=data.get("metadata", {})
        )
        
        # 添加信号
        for signal_data in data.get("injection_signals", []):
            signal = FaultSignal(**signal_data)
            fault.add_injection_signal(signal)
        
        for signal_data in data.get("internal_verification_signals", []):
            signal = FaultSignal(**signal_data)
            fault.add_internal_verification_signal(signal)
        
        for signal_data in data.get("external_verification_signals", []):
            signal = FaultSignal(**signal_data)
            fault.add_external_verification_signal(signal)
        
        for signal_data in data.get("clear_signals", []):
            signal = FaultSignal(**signal_data)
            fault.add_clear_signal(signal)
        
        return fault
    
    def __str__(self) -> str:
        """字符串表示"""
        severity_icon = {
            FaultSeverity.INFO: "ℹ️",
            FaultSeverity.WARNING: "⚠️",
            FaultSeverity.ERROR: "❌",
            FaultSeverity.CRITICAL: "💀"
        }.get(self.severity, "❓")
        
        injection_count = len(self.injection_signals)
        internal_count = len(self.internal_verification_signals)
        external_count = len(self.external_verification_signals)
        clear_count = len(self.clear_signals)
        
        return f"{severity_icon} {self.name} ({self.fault_type.value}): {injection_count}注入, {internal_count}内验, {external_count}外验, {clear_count}清除"


@dataclass
class FaultLibrary:
    """故障库"""
    
    faults: Dict[str, Fault] = field(default_factory=dict)
    
    def add_fault(self, fault: Fault) -> None:
        """添加故障"""
        self.faults[fault.fault_id] = fault
    
    def get_fault(self, fault_id: str) -> Optional[Fault]:
        """获取故障"""
        return self.faults.get(fault_id)
    
    def get_fault_by_name(self, name: str) -> Optional[Fault]:
        """根据名称获取故障"""
        for fault in self.faults.values():
            if fault.name == name:
                return fault
        return None
    
    def get_faults_by_type(self, fault_type: FaultType) -> List[Fault]:
        """根据类型获取故障"""
        return [f for f in self.faults.values() if f.fault_type == fault_type]
    
    def get_faults_by_domain(self, domain_type: str) -> List[Fault]:
        """根据域类型获取故障"""
        return [f for f in self.faults.values() if f.domain_type == domain_type]
    
    def get_all_faults(self) -> List[Fault]:
        """获取所有故障"""
        return list(self.faults.values())
    
    def get_fault_count(self) -> int:
        """获取故障数量"""
        return len(self.faults)
    
    def get_fault_count_by_type(self) -> Dict[FaultType, int]:
        """按类型统计故障数量"""
        counts = {ft: 0 for ft in FaultType}
        for fault in self.faults.values():
            counts[fault.fault_type] += 1
        return counts
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "faults": {fault_id: fault.to_dict() for fault_id, fault in self.faults.items()},
            "total_count": self.get_fault_count(),
            "count_by_type": {ft.value: count for ft, count in self.get_fault_count_by_type().items()}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FaultLibrary':
        """从字典创建故障库"""
        library = cls()
        
        for fault_id, fault_data in data.get("faults", {}).items():
            fault = Fault.from_dict(fault_data)
            library.add_fault(fault)
        
        return library
    
    def __str__(self) -> str:
        """字符串表示"""
        total = self.get_fault_count()
        counts = self.get_fault_count_by_type()
        count_str = ", ".join([f"{ft.value}: {count}" for ft, count in counts.items()])
        return f"故障库: {total}个故障 ({count_str})"