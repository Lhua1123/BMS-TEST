"""
双CAN总线管理器
封装通道0（双向）和通道1（只读），对应CAN盒物理通道
提供统一的send/subscribe/read_signal接口
移植自 报警测试/src/can/can_manager.py
"""

import logging
import time
import threading
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from bms_alarm_test.can.zlg_adapter import ZLGAdapter, ZLGAdapterManager, BaudRate
from bms_alarm_test.can.can_listener import CANListener, CANChannel, SignalUpdate
from bms_alarm_test.config.settings import get_global_settings, CANConfig
from bms_alarm_test.config.dbc_loader import DBCLoader
from bms_alarm_test.models.can_message import (
    CANMessage as ModelCANMessage,
    RuntimeCANMessage,
    RuntimeCANSignal,
)
from bms_alarm_test.utils.exceptions import CANError

logger = logging.getLogger(__name__)


class CANManagerError(Exception):
    """CAN管理器错误"""
    pass


class CANState(Enum):
    """CAN状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class CANStatus:
    """CAN状态信息"""
    channel: int
    state: CANState
    baud_rate: BaudRate
    error_count: int
    last_error: Optional[str]
    message_count: Dict[str, int]
    connected_since: Optional[float]

    def __str__(self) -> str:
        return f"CH{self.channel}: {self.state.value} @ {self.baud_rate}"


class CANManager:
    """双CAN总线管理器"""

    def __init__(self, dbc_loader: DBCLoader):
        self.dbc_loader = dbc_loader
        self.settings = get_global_settings()

        # 适配器和监听器
        self._adapter_manager = ZLGAdapterManager()
        self._listener: Optional[CANListener] = None

        # 总线实例
        self._buses: Dict[int, Optional[ZLGAdapter]] = {}

        # 状态管理
        self._states: Dict[int, CANState] = {1: CANState.DISCONNECTED, 2: CANState.DISCONNECTED}
        self._status: Dict[int, CANStatus] = {}
        self._error_counts: Dict[int, int] = {1: 0, 2: 0}
        self._message_counts: Dict[int, Dict[str, int]] = {
            1: {"tx": 0, "rx": 0},
            2: {"tx": 0, "rx": 0},
        }

        # 连接时间
        self._connected_times: Dict[int, Optional[float]] = {1: None, 2: None}

        # 锁
        self._lock = threading.RLock()

        # 初始化状态
        self._init_status()

    def _init_status(self):
        """初始化状态"""
        for channel in [1, 2]:
            can_config = self.settings.get_can_config(channel)
            baud_rate = can_config.baud_rate if can_config else BaudRate.BAUD_500K

            self._status[channel] = CANStatus(
                channel=channel,
                state=CANState.DISCONNECTED,
                baud_rate=baud_rate,
                error_count=0,
                last_error=None,
                message_count={"tx": 0, "rx": 0},
                connected_since=None
            )

    def connect(self) -> bool:
        """
        连接CAN（一键初始化+启动）
        """
        try:
            if not self.initialize():
                return False
            if not self.start():
                return False
            logger.info("CAN连接成功")
            return True
        except CANError as e:
            logger.error(f"CAN连接失败: {e}")
            return False
        except Exception as e:
            logger.error(f"CAN连接失败（未知错误）: {e}", exc_info=True)
            return False

    def disconnect(self):
        """断开CAN连接"""
        try:
            self.stop()
            self.shutdown()
            logger.info("CAN已断开")
        except Exception as e:
            logger.error(f"CAN断开失败: {e}")

    def initialize(self) -> bool:
        """初始化CAN管理器"""
        try:
            if not self._adapter_manager.initialize():
                logger.warning("适配器初始化失败（硬件可能未连接）")

            # 创建监听器
            self._listener = CANListener(self.dbc_loader)

            logger.info("CAN管理器初始化成功")
            return True

        except CANError as e:
            logger.error(f"CAN管理器初始化失败: {e}")
            return False
        except Exception as e:
            logger.error(f"CAN管理器初始化失败（未知错误）: {e}", exc_info=True)
            return False

    def start(self) -> bool:
        """启动CAN通信（统一打开设备→初始化所有通道）"""
        try:
            with self._lock:
                # 收集启用的通道配置
                channels_config: Dict[int, BaudRate] = {}
                for channel in [1, 2]:
                    can_config = self.settings.get_can_config(channel)
                    if can_config and can_config.enabled:
                        channels_config[channel] = can_config.baud_rate

                if not channels_config:
                    logger.warning("没有启用任何CAN通道")
                    return False

                # 统一打开设备并初始化所有通道
                results = self._adapter_manager.open_and_init_all(channels_config)

                any_connected = False
                for channel, adapter in results.items():
                    if adapter is not None:
                        self._buses[channel] = adapter
                        self._states[channel] = CANState.CONNECTED
                        self._connected_times[channel] = time.time()
                        self._status[channel].state = CANState.CONNECTED
                        self._status[channel].connected_since = time.time()
                        self._status[channel].last_error = None
                        any_connected = True
                        logger.info(f"通道{channel}连接成功（硬件模式）")
                    else:
                        self._states[channel] = CANState.ERROR
                        self._status[channel].state = CANState.ERROR
                        self._status[channel].last_error = "硬件初始化失败"
                        self._buses[channel] = None
                        logger.error(f"通道{channel}硬件初始化失败")

                if not any_connected:
                    logger.error("所有CAN通道均连接失败，请检查硬件和驱动")
                    return False

                # 启动监听器（模拟模式下跳过None总线通道）
                if self._listener:
                    bus1 = self._buses.get(1)
                    bus2 = self._buses.get(2)
                    self._listener.start(bus1, bus2)

                logger.info("CAN通信已启动")
                return True

        except CANError as e:
            logger.error(f"启动CAN通信失败: {e}")
            with self._lock:
                for channel in [1, 2]:
                    self._states[channel] = CANState.ERROR
                    self._status[channel].state = CANState.ERROR
                    self._status[channel].last_error = str(e)
            return False
        except Exception as e:
            logger.error(f"启动CAN通信失败（未知错误）: {e}", exc_info=True)
            with self._lock:
                for channel in [1, 2]:
                    self._states[channel] = CANState.ERROR
                    self._status[channel].state = CANState.ERROR
                    self._status[channel].last_error = str(e)
            return False

    def stop(self) -> None:
        """停止CAN通信"""
        try:
            with self._lock:
                if self._listener:
                    self._listener.stop()

                self._adapter_manager.stop_can()

                for channel in [1, 2]:
                    self._states[channel] = CANState.STOPPED
                    self._status[channel].state = CANState.STOPPED
                    self._connected_times[channel] = None

                logger.info("CAN通信已停止")

        except Exception as e:
            logger.error(f"停止CAN通信失败: {e}")

    def shutdown(self) -> None:
        """关闭CAN管理器"""
        self.stop()
        self._adapter_manager.shutdown()

        with self._lock:
            for channel in [1, 2]:
                self._states[channel] = CANState.DISCONNECTED
                self._status[channel].state = CANState.DISCONNECTED

        logger.info("CAN管理器已关闭")

    def send_message(self, channel: int, can_id: int = None, data: bytes = b'',
                     is_extended: bool = True, message_id: int = None,
                     is_extended_id: bool = None) -> bool:
        """
        发送CAN报文（仅CH1）
        """
        if can_id is None:
            can_id = message_id
        if is_extended_id is not None:
            is_extended = is_extended_id

        if channel != 1:
            logger.error(f"通道{channel}为只读，不能发送报文")
            return False

        with self._lock:
            if self._states[channel] != CANState.CONNECTED:
                logger.error(f"通道{channel}未连接")
                return False

            try:
                adapter = self._adapter_manager.get_adapter(channel)
                if not adapter or not adapter.is_connected:
                    logger.warning(f"模拟模式: 无法发送 CAN 报文 ID=0x{can_id:X}（硬件未连接）")
                    self._message_counts[channel]["tx"] += 1
                    self._status[channel].message_count["tx"] += 1
                    return False

                success = adapter.send(can_id, data, is_extended)

                if success:
                    self._message_counts[channel]["tx"] += 1
                    self._status[channel].message_count["tx"] += 1
                    # 发出的报文记录为INFO（发送量小，便于排查测试报文）
                    logger.info(f"CH{channel}发送报文: ID=0x{can_id:X} 数据={' '.join(f'{b:02X}' for b in data)}")
                else:
                    logger.warning(f"CH{channel}发送失败: ID=0x{can_id:X}")

                return success

            except Exception as e:
                logger.error(f"CH{channel}发送报文异常: ID=0x{can_id:X}, 错误: {e}")
                return False

    def send_messages(self, channel: int, messages: List[Tuple[int, bytes]],
                     interval_ms: float = 50) -> bool:
        """发送多个CAN报文"""
        if channel != 1:
            logger.error(f"通道{channel}为只读，不能发送报文")
            return False

        all_success = True
        for can_id, data in messages:
            success = self.send_message(channel, can_id, data)
            if not success:
                all_success = False

            if interval_ms > 0:
                time.sleep(interval_ms / 1000.0)

        return all_success

    def subscribe(self, callback: Callable[[SignalUpdate], None],
                  channel: Optional[CANChannel] = None,
                  message_name: Optional[str] = None,
                  signal_name: Optional[str] = None) -> None:
        """订阅信号更新"""
        if self._listener:
            self._listener.subscribe(callback, channel, message_name, signal_name)

    def unsubscribe(self, callback: Callable[[SignalUpdate], None]) -> None:
        """取消订阅"""
        if self._listener:
            self._listener.unsubscribe(callback)

    def read_signal(self, channel: int, message_name: str, signal_name: str) -> Optional[Any]:
        """读取信号值"""
        if not self._listener:
            return None

        can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
        return self._listener.get_signal_value(can_channel, message_name, signal_name)

    def read_all_signals(self, channel: int) -> Dict[str, Dict[str, Any]]:
        """读取指定通道的所有信号值"""
        if not self._listener:
            return {}

        can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
        return self._listener.get_all_signal_values(can_channel)

    def set_baud_rate(self, channel: int, baud_rate: BaudRate) -> bool:
        """设置波特率"""
        with self._lock:
            if self._states[channel] != CANState.CONNECTED:
                logger.error(f"通道{channel}未连接")
                return False

            try:
                adapter = self._adapter_manager.get_adapter(channel)
                if not adapter:
                    return False

                success = adapter.set_baud_rate(channel, baud_rate)

                if success:
                    self._status[channel].baud_rate = baud_rate
                    logger.info(f"CH{channel}波特率设置为: {baud_rate}")

                return success

            except Exception as e:
                logger.error(f"设置波特率失败: {e}")
                return False

    def get_status(self, channel: int) -> CANStatus:
        """获取通道状态"""
        with self._lock:
            status = self._status[channel]
            # 同步监听器的 RX 计数到状态对象
            if self._listener:
                rx_counts = self._listener.get_rx_counts()
                can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
                status.message_count["rx"] = rx_counts.get(can_channel, 0)
            return status

    def get_all_status(self) -> Dict[int, CANStatus]:
        """获取所有通道状态"""
        with self._lock:
            return self._status.copy()

    def is_connected(self, channel: Optional[int] = None) -> bool:
        """检查是否已连接"""
        with self._lock:
            if channel:
                return self._states.get(channel) == CANState.CONNECTED
            else:
                return all(state == CANState.CONNECTED for state in self._states.values())

    def get_connected_channels(self) -> List[int]:
        """获取已连接的通道列表"""
        with self._lock:
            return [ch for ch, state in self._states.items() if state == CANState.CONNECTED]

    def reconnect(self, channel: Optional[int] = None) -> bool:
        """重新连接"""
        try:
            self.stop()
            time.sleep(1.0)
            return self.start()
        except Exception as e:
            logger.error(f"重新连接失败: {e}")
            return False

    def wait_for_signal(self, channel: int, message_name: str, signal_name: str,
                       timeout: float = 5.0) -> Optional[Any]:
        """等待信号出现"""
        if not self._listener:
            return None

        can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
        return self._listener.wait_for_signal(can_channel, message_name, signal_name, timeout)

    def wait_for_signal_change(self, channel: int, message_name: str, signal_name: str,
                              old_value: Any, timeout: float = 5.0) -> Optional[Any]:
        """等待信号变化"""
        if not self._listener:
            return None

        can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
        return self._listener.wait_for_signal_change(can_channel, message_name, signal_name, old_value, timeout)

    def clear_signal_cache(self, channel: Optional[int] = None) -> None:
        """清除信号缓存"""
        if self._listener:
            can_channel = None
            if channel:
                can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
            self._listener.clear_cache(can_channel)

    def get_recent_messages(self, channel: int, count: int = 100) -> List[RuntimeCANMessage]:
        """
        获取最近的CAN报文（监控面板用）
        返回 RuntimeCANMessage 列表，包含 DBC 解码后的信号
        """
        if not self._listener:
            return []

        can_channel = CANChannel.CH1 if channel == 1 else CANChannel.CH2
        recent = self._listener.get_recent_messages(can_channel, count)
        dbc_type = "inner" if channel == 1 else "outer"

        result: List[RuntimeCANMessage] = []
        for message, ts in recent:
            try:
                name = self._listener._get_message_name(can_channel, message.arbitration_id) or "未知"
                signals: Dict[str, RuntimeCANSignal] = {}
                decoded = self.dbc_loader.decode_message(dbc_type, message.arbitration_id, message.data)
                if decoded:
                    # 获取 DBC 信号定义（scale/offset/unit/min/max）
                    sig_defs = {}
                    if name and name != "未知":
                        try:
                            dbc_msg = self.dbc_loader.get_message(dbc_type, name)
                            if dbc_msg:
                                sig_defs = {sig.name: sig for sig in dbc_msg.signals}
                        except Exception:
                            pass
                    for sig_name, val in decoded.items():
                        if hasattr(val, 'value'):
                            val = val.value
                        sig_def = sig_defs.get(sig_name)
                        scale = float(sig_def.scale) if sig_def else 1.0
                        offset = float(sig_def.offset) if sig_def else 0.0
                        unit = str(sig_def.unit) if sig_def and sig_def.unit else ""
                        minimum = sig_def.minimum if sig_def else None
                        maximum = sig_def.maximum if sig_def else None
                        physical = float(val)
                        raw = int(round((physical - offset) / scale)) if scale else int(round(physical))
                        signals[sig_name] = RuntimeCANSignal(
                            name=sig_name,
                            physical_value=physical,
                            raw_value=raw,
                            unit=unit,
                            minimum=minimum,
                            maximum=maximum,
                            scale=scale,
                            offset=offset,
                        )

                result.append(RuntimeCANMessage(
                    channel=channel,
                    message_id=message.arbitration_id,
                    name=name,
                    data=bytes(message.data),
                    timestamp=ts if ts is not None else getattr(message, 'timestamp', 0),
                    data_length=len(message.data),
                    count=1,
                    signals=signals,
                    is_extended=bool(getattr(message, 'is_extended_id', True)),
                ))
            except Exception as e:
                logger.debug(f"构建监控报文失败: ID=0x{message.arbitration_id:X}, 错误: {e}")
                result.append(RuntimeCANMessage(
                    channel=channel,
                    message_id=message.arbitration_id,
                    name="未知",
                    data=bytes(message.data),
                    timestamp=ts if ts is not None else getattr(message, 'timestamp', 0),
                    data_length=len(message.data),
                    count=1,
                    is_extended=bool(getattr(message, 'is_extended_id', True)),
                ))

        return result

    def request_stop(self) -> None:
        """请求中断正在进行的信号等待"""
        if self._listener:
            self._listener.set_stop()

    def clear_stop(self) -> None:
        """清除停止请求"""
        if self._listener:
            self._listener.clear_stop()

    def is_stop_requested(self) -> bool:
        """测试是否请求停止"""
        return self._listener is not None and self._listener._stop_event.is_set()

    def test_connection(self, channel: int) -> bool:
        """测试连接"""
        adapter = self._adapter_manager.get_adapter(channel)
        if not adapter:
            return False
        return adapter.test_connection(channel)


# 全局CAN管理器实例
_global_can_manager: Optional[CANManager] = None


def get_global_can_manager(dbc_loader: Optional[DBCLoader] = None) -> CANManager:
    """获取全局CAN管理器实例"""
    global _global_can_manager
    if _global_can_manager is None and dbc_loader:
        _global_can_manager = CANManager(dbc_loader)
    return _global_can_manager


def set_global_can_manager(manager: CANManager) -> None:
    """设置全局CAN管理器实例"""
    global _global_can_manager
    _global_can_manager = manager
