"""
CAN消息数据模型
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


class SignalType(Enum):
    """信号类型"""
    BOOL = "bool"
    UINT8 = "uint8"
    UINT16 = "uint16"
    UINT32 = "uint32"
    INT8 = "int8"
    INT16 = "int16"
    INT32 = "int32"
    FLOAT = "float"
    DOUBLE = "double"


@dataclass
class CANSignal:
    """CAN信号定义"""
    
    name: str
    start_bit: int
    length: int
    byte_order: str  # 'little_endian' or 'big_endian'
    is_signed: bool
    factor: float
    offset: float
    minimum: Optional[float]
    maximum: Optional[float]
    unit: str
    comment: str
    
    def __post_init__(self):
        """后初始化处理"""
        # 确保长度为正数
        if self.length <= 0:
            raise ValueError(f"信号长度必须为正数: {self.name}")
        
        # 确保起始位有效
        if self.start_bit < 0:
            raise ValueError(f"起始位必须为非负数: {self.name}")
    
    def get_physical_value(self, raw_value: int) -> float:
        """
        计算物理值
        
        Args:
            raw_value: 原始值
            
        Returns:
            物理值
        """
        return raw_value * self.factor + self.offset
    
    def get_raw_value(self, physical_value: float) -> int:
        """
        计算原始值
        
        Args:
            physical_value: 物理值
            
        Returns:
            原始值
        """
        raw = (physical_value - self.offset) / self.factor
        
        # 根据是否有符号进行舍入
        if self.is_signed:
            return int(round(raw))
        else:
            return int(round(max(0, raw)))
    
    def validate_value(self, physical_value: float) -> bool:
        """
        验证物理值是否在有效范围内
        
        Args:
            physical_value: 物理值
            
        Returns:
            是否有效
        """
        if self.minimum is not None and physical_value < self.minimum:
            return False
        if self.maximum is not None and physical_value > self.maximum:
            return False
        return True
    
    def __str__(self) -> str:
        """字符串表示"""
        signed_str = "signed" if self.is_signed else "unsigned"
        range_str = ""
        if self.minimum is not None and self.maximum is not None:
            range_str = f" [{self.minimum:.2f}..{self.maximum:.2f}]"
        return f"{self.name}: {self.length}bit {signed_str}{range_str} {self.unit}"


@dataclass
class CANMessage:
    """CAN消息定义"""
    
    name: str
    frame_id: int
    is_extended: bool
    length: int  # DLC
    signals: Dict[str, CANSignal]
    comment: str
    cycle_time: Optional[int] = None  # 周期时间(ms)
    send_node: Optional[str] = None   # 发送节点
    
    def __post_init__(self):
        """后初始化处理"""
        # 确保长度在0-8之间
        if not 0 <= self.length <= 8:
            raise ValueError(f"DLC必须在0-8之间: {self.name}")
        
        # 确保ID有效
        if self.is_extended:
            if not 0 <= self.frame_id <= 0x1FFFFFFF:
                raise ValueError(f"扩展帧ID必须在0-0x1FFFFFFF之间: {self.name}")
        else:
            if not 0 <= self.frame_id <= 0x7FF:
                raise ValueError(f"标准帧ID必须在0-0x7FF之间: {self.name}")
    
    def get_signal(self, signal_name: str) -> Optional[CANSignal]:
        """
        获取信号
        
        Args:
            signal_name: 信号名称
            
        Returns:
            CAN信号，未找到返回None
        """
        return self.signals.get(signal_name)
    
    def has_signal(self, signal_name: str) -> bool:
        """
        检查是否有指定信号
        
        Args:
            signal_name: 信号名称
            
        Returns:
            是否有该信号
        """
        return signal_name in self.signals
    
    def get_signal_names(self) -> List[str]:
        """
        获取所有信号名称
        
        Returns:
            信号名称列表
        """
        return list(self.signals.keys())
    
    def encode(self, signal_values: Dict[str, Any]) -> bytes:
        """
        编码信号值为CAN数据
        
        Args:
            signal_values: 信号值字典 {信号名: 值}
            
        Returns:
            CAN数据字节
        """
        # 初始化数据字节
        data = bytearray(self.length)
        
        for signal_name, value in signal_values.items():
            signal = self.signals.get(signal_name)
            if not signal:
                raise ValueError(f"未知信号: {signal_name}")
            
            # 计算原始值
            raw_value = signal.get_raw_value(float(value))
            
            # 编码到数据中
            self._encode_signal(data, signal, raw_value)
        
        return bytes(data)
    
    def _encode_signal(self, data: bytearray, signal: CANSignal, raw_value: int):
        """
        编码单个信号
        
        Args:
            data: 数据字节数组
            signal: 信号定义
            raw_value: 原始值
        """
        # 计算掩码
        mask = (1 << signal.length) - 1
        
        # 确保值在范围内
        raw_value &= mask
        
        # 编码到数据中
        if signal.byte_order == 'little_endian':
            self._encode_little_endian(data, signal, raw_value)
        else:
            self._encode_big_endian(data, signal, raw_value)
    
    def _encode_little_endian(self, data: bytearray, signal: CANSignal, raw_value: int):
        """小端序编码"""
        bit_position = signal.start_bit
        
        for i in range(signal.length):
            byte_index = bit_position // 8
            bit_index = bit_position % 8
            
            if raw_value & (1 << i):
                data[byte_index] |= (1 << bit_index)
            else:
                data[byte_index] &= ~(1 << bit_index)
            
            bit_position += 1
    
    def _encode_big_endian(self, data: bytearray, signal: CANSignal, raw_value: int):
        """大端序编码"""
        bit_position = signal.start_bit
        
        for i in range(signal.length - 1, -1, -1):
            byte_index = bit_position // 8
            bit_index = bit_position % 8
            
            if raw_value & (1 << i):
                data[byte_index] |= (1 << bit_index)
            else:
                data[byte_index] &= ~(1 << bit_index)
            
            bit_position += 1
    
    def decode(self, data: bytes) -> Dict[str, float]:
        """
        解码CAN数据为信号值
        
        Args:
            data: CAN数据字节
            
        Returns:
            信号值字典 {信号名: 物理值}
        """
        if len(data) < self.length:
            raise ValueError(f"数据长度不足: 需要{self.length}字节，实际{len(data)}字节")
        
        result = {}
        
        for signal_name, signal in self.signals.items():
            # 解码原始值
            raw_value = self._decode_signal(data, signal)
            
            # 计算物理值
            physical_value = signal.get_physical_value(raw_value)
            
            result[signal_name] = physical_value
        
        return result
    
    def _decode_signal(self, data: bytes, signal: CANSignal) -> int:
        """
        解码单个信号
        
        Args:
            data: 数据字节
            signal: 信号定义
            
        Returns:
            原始值
        """
        if signal.byte_order == 'little_endian':
            return self._decode_little_endian(data, signal)
        else:
            return self._decode_big_endian(data, signal)
    
    def _decode_little_endian(self, data: bytes, signal: CANSignal) -> int:
        """小端序解码"""
        raw_value = 0
        bit_position = signal.start_bit
        
        for i in range(signal.length):
            byte_index = bit_position // 8
            bit_index = bit_position % 8
            
            if byte_index < len(data) and (data[byte_index] >> bit_index) & 1:
                raw_value |= (1 << i)
            
            bit_position += 1
        
        return raw_value
    
    def _decode_big_endian(self, data: bytes, signal: CANSignal) -> int:
        """大端序解码"""
        raw_value = 0
        bit_position = signal.start_bit
        
        for i in range(signal.length):
            byte_index = bit_position // 8
            bit_index = bit_position % 8
            
            if byte_index < len(data) and (data[byte_index] >> bit_index) & 1:
                raw_value |= (1 << (signal.length - 1 - i))
            
            bit_position += 1
        
        return raw_value
    
    def validate_data(self, data: bytes) -> bool:
        """
        验证数据是否有效
        
        Args:
            data: CAN数据
            
        Returns:
            是否有效
        """
        if len(data) < self.length:
            return False
        
        try:
            decoded = self.decode(data)
            
            # 验证每个信号的值
            for signal_name, value in decoded.items():
                signal = self.signals[signal_name]
                if not signal.validate_value(value):
                    return False
            
            return True
            
        except Exception:
            return False
    
    def __str__(self) -> str:
        """字符串表示"""
        extended_str = "extended" if self.is_extended else "standard"
        signal_count = len(self.signals)
        cycle_str = f" {self.cycle_time}ms" if self.cycle_time else ""
        return f"{self.name}: 0x{self.frame_id:X} ({extended_str}, {self.length} bytes, {signal_count} signals{cycle_str})"


@dataclass
class RuntimeCANSignal:
    """运行时CAN信号（监控面板使用的动态信号值）"""
    name: str
    physical_value: float
    raw_value: int
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    scale: float = 1.0
    offset: float = 0.0


@dataclass
class RuntimeCANMessage:
    """运行时CAN报文（监控面板使用的动态报文）"""
    channel: int                # 逻辑通道号 1/2
    message_id: int             # CAN ID
    name: str                   # 报文名（DBC 解码后）
    data: bytes                 # 原始数据
    timestamp: float            # 接收时间戳
    data_length: int = 0        # 数据长度
    period_ms: int = 0          # 周期(ms)，0 表示未知
    count: int = 1              # 计数
    signals: Dict[str, RuntimeCANSignal] = field(default_factory=dict)
    is_extended: bool = True


@dataclass
class CANBus:
    """CAN总线定义"""
    
    name: str
    baudrate: int
    messages: Dict[str, CANMessage]
    nodes: List[str]
    
    def get_message_by_id(self, frame_id: int) -> Optional[CANMessage]:
        """
        根据ID获取消息
        
        Args:
            frame_id: 帧ID
            
        Returns:
            CAN消息，未找到返回None
        """
        for message in self.messages.values():
            if message.frame_id == frame_id:
                return message
        return None
    
    def get_message_by_name(self, name: str) -> Optional[CANMessage]:
        """
        根据名称获取消息
        
        Args:
            name: 消息名称
            
        Returns:
            CAN消息，未找到返回None
        """
        return self.messages.get(name)
    
    def get_signal(self, message_name: str, signal_name: str) -> Optional[CANSignal]:
        """
        获取信号
        
        Args:
            message_name: 消息名称
            signal_name: 信号名称
            
        Returns:
            CAN信号，未找到返回None
        """
        message = self.get_message_by_name(message_name)
        if not message:
            return None
        return message.get_signal(signal_name)
    
    def __str__(self) -> str:
        """字符串表示"""
        message_count = len(self.messages)
        node_count = len(self.nodes)
        return f"{self.name}: {self.baudrate} bps, {message_count} messages, {node_count} nodes"