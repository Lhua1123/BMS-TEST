"""
实时监听与信号解码
异步监听CH1和CH2的报文，基于cantools解码信号
移植自 报警测试/src/can/can_listener.py
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty
from collections import deque

from bms_alarm_test.config.dbc_loader import DBCLoader
from bms_alarm_test.models.can_message import CANSignal, CANMessage as ModelCANMessage
from bms_alarm_test.config.constants import CANConstants, TimingConstants


logger = logging.getLogger(__name__)


# 硬件实际报文ID与DBC定义不一致时的归一化映射（硬件ID → DBC报文名）
# 硬件CAN ID与DBC定义一致，无需额外映射
# DBC中NBCMU01 WarningInfo的CAN ID:
#   WarningInfo1: 0x18B1FFA1
#   WarningInfo2: 0x18BBFFA1
#   WarningInfo3: 0x18A3FFA1
HARDWARE_ID_TO_DBC_NAME = {}


class CANChannel(Enum):
    """CAN通道枚举（逻辑通道号，对应 CAN 盒物理 0/1）"""
    CH1 = "CH1"  # 逻辑通道1 → 物理通道0
    CH2 = "CH2"  # 逻辑通道2 → 物理通道1

    def to_int(self) -> int:
        """逻辑通道号 1/2"""
        return 1 if self == self.CH1 else 2

    @classmethod
    def from_int(cls, channel: int) -> 'CANChannel':
        return cls.CH1 if channel == 1 else cls.CH2

    def get_dbc_type(self) -> str:
        """按当前配置的角色获取 DBC 类型（对内=inner / 对外=outer）"""
        try:
            from bms_alarm_test.config.settings import get_global_settings
            role = get_global_settings().get_channel_role(self.to_int())
            return 'inner' if role == 'inner' else 'outer'
        except Exception:
            # 回退：CH1=对内, CH2=对外
            return "inner" if self == self.CH1 else "outer"


@dataclass
class SignalUpdate:
    """信号更新"""
    channel: CANChannel
    message_name: str
    signal_name: str
    value: Any
    timestamp: float
    raw_message: Any

    def __str__(self) -> str:
        return f"{self.channel.value}.{self.message_name}.{self.signal_name} = {self.value}"


class SignalCallback:
    """信号回调包装器"""

    def __init__(self, callback: Callable[[SignalUpdate], None], filter_message: Optional[str] = None,
                 filter_signal: Optional[str] = None):
        self.callback = callback
        self.filter_message = filter_message
        self.filter_signal = filter_signal

    def matches(self, message_name: str, signal_name: str) -> bool:
        """检查是否匹配过滤条件"""
        if self.filter_message and self.filter_message != message_name:
            return False
        if self.filter_signal and self.filter_signal != signal_name:
            return False
        return True

    def invoke(self, update: SignalUpdate) -> None:
        """调用回调"""
        try:
            self.callback(update)
        except Exception as e:
            logger.error(f"信号回调执行失败: {e}")


class CANListener:
    """CAN监听器"""

    def __init__(self, dbc_loader: DBCLoader):
        self.dbc_loader = dbc_loader
        self._running = False
        self._listener_threads: Dict[CANChannel, threading.Thread] = {}
        self._message_queues: Dict[CANChannel, Queue] = {}
        self._signal_cache: Dict[CANChannel, Dict[str, Dict[str, Any]]] = {
            CANChannel.CH1: {},
            CANChannel.CH2: {},
        }
        self._callbacks: List[SignalCallback] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        # 报文计数
        self._rx_counts: Dict[CANChannel, int] = {
            CANChannel.CH1: 0,
            CANChannel.CH2: 0,
        }

        # 关注的报文ID：按当前通道角色分配（对内=内部报文ID，对外=外部报文ID）
        self._monitored_message_ids: Dict[CANChannel, Set[int]] = {}
        self._init_monitored_ids()

    def _init_monitored_ids(self) -> None:
        """按角色初始化各通道监控报文ID集合"""
        try:
            from bms_alarm_test.config.settings import get_global_settings
            inner_ch = get_global_settings().get_inner_channel()
            outer_ch = get_global_settings().get_outer_channel()
        except Exception:
            inner_ch, outer_ch = 1, 2

        self._monitored_message_ids[CANChannel.from_int(inner_ch)] = CANConstants.CH0_MONITORED_IDS.copy()
        self._monitored_message_ids[CANChannel.from_int(outer_ch)] = CANConstants.CH1_MONITORED_BASE_IDS.copy()

        # 最近报文环形缓冲（每通道最多保留 RECENT_MESSAGE_LIMIT 条）
        self._recent_messages: Dict[CANChannel, deque] = {
            CANChannel.CH1: deque(maxlen=CANConstants.RECENT_MESSAGE_LIMIT),
            CANChannel.CH2: deque(maxlen=CANConstants.RECENT_MESSAGE_LIMIT),
        }

    def start(self, bus_ch1, bus_ch2) -> bool:
        """启动监听"""
        if self._running:
            logger.warning("监听器已在运行")
            return False

        try:
            self._running = True
            # 每次启动按当前角色重建监控ID，支持对内/对外通道对调
            self._init_monitored_ids()

            self._message_queues[CANChannel.CH1] = Queue()
            self._message_queues[CANChannel.CH2] = Queue()

            if bus_ch1 is not None:
                ch1_thread = threading.Thread(
                    target=self._listen_channel,
                    args=(CANChannel.CH1, bus_ch1),
                    name="CANListener-CH1",
                    daemon=True
                )
                ch1_thread.start()
                self._listener_threads[CANChannel.CH1] = ch1_thread
            else:
                logger.info("CH1 适配器为 None，跳过硬件监听（模拟模式）")

            if bus_ch2 is not None:
                ch2_thread = threading.Thread(
                    target=self._listen_channel,
                    args=(CANChannel.CH2, bus_ch2),
                    name="CANListener-CH2",
                    daemon=True
                )
                ch2_thread.start()
                self._listener_threads[CANChannel.CH2] = ch2_thread
            else:
                logger.info("CH2 适配器为 None，跳过硬件监听（模拟模式）")

            processor_thread = threading.Thread(
                target=self._process_messages,
                name="CANSignalProcessor",
                daemon=True
            )
            processor_thread.start()

            logger.info("CAN监听器已启动")
            return True

        except Exception as e:
            logger.error(f"启动监听器失败: {e}")
            self._running = False
            return False

    def stop(self) -> None:
        """停止监听"""
        self._running = False

        # 等待线程结束
        for channel, thread in self._listener_threads.items():
            if thread.is_alive():
                thread.join(timeout=2.0)
                if thread.is_alive():
                    logger.warning(f"{channel.value}监听线程未正常结束")

        self._listener_threads.clear()
        self._message_queues.clear()
        for ch in self._recent_messages:
            self._recent_messages[ch].clear()
        logger.info("CAN监听器已停止")

    def set_stop(self) -> None:
        """请求中断正在进行的信号等待"""
        self._stop_event.set()

    def clear_stop(self) -> None:
        """清除停止请求"""
        self._stop_event.clear()

    def _listen_channel(self, channel: CANChannel, bus) -> None:
        """监听指定通道"""
        logger.info(f"开始监听{channel.value}")
        rx_count = 0
        last_debug_time = 0
        loop_count = 0

        while self._running:
            loop_count += 1
            try:
                # 每3秒打印一次接收缓冲区状态
                now = time.time()
                if now - last_debug_time > 3.0:
                    try:
                        buf = bus._dll.VCI_GetReceiveNum(bus._dev_type, bus._dev_index, bus.channel)
                        logger.debug(f"[{channel.value}] 接收缓冲区: {buf}, 累计收到: {rx_count}, 循环次数: {loop_count}")
                    except Exception as e:
                        logger.debug(f"[{channel.value}] 查询缓冲区异常: {e}")
                    last_debug_time = now

                message = bus.recv(timeout=0.1)
                if message:
                    self._rx_counts[channel] += 1
                    rx_count += 1
                    # 报文级数据量大，降到DEBUG避免刷屏（常规运行看INFO即可）
                    logger.debug(f"[{channel.value}] 收到CAN报文: ID=0x{message.arbitration_id:08X}, 数据={' '.join(f'{b:02X}' for b in message.data)}")
                    ts = time.time()
                    queue = self._message_queues.get(channel)
                    if queue:
                        queue.put((message, ts))
                    # 存入最近报文缓冲（供 CAN 监控面板读取）
                    self._recent_messages[channel].append((message, ts))

            except Exception as e:
                logger.error(f"{channel.value}监听异常: {e}")
                if self._running:
                    time.sleep(0.1)

        logger.info(f"停止监听{channel.value}, 共收到{rx_count}条报文")

    def get_rx_counts(self) -> Dict[CANChannel, int]:
        """获取各通道累计接收报文数"""
        return self._rx_counts.copy()

    def get_recent_messages(self, channel: CANChannel, count: int = 100) -> List[Tuple[Any, float]]:
        """获取指定通道最近接收的报文列表 [(message, timestamp), ...]"""
        recent = self._recent_messages.get(channel)
        if not recent:
            return []
        return list(recent)[-count:]

    def _process_messages(self) -> None:
        """处理接收到的报文"""
        logger.info("开始处理CAN报文")
        processed = 0

        while self._running:
            try:
                for channel in [CANChannel.CH1, CANChannel.CH2]:
                    queue = self._message_queues.get(channel)
                    if not queue:
                        continue

                    while not queue.empty():
                        try:
                            message, timestamp = queue.get_nowait()
                            self._process_single_message(channel, message, timestamp)
                            processed += 1
                        except Empty:
                            break

                time.sleep(0.01)

            except Exception as e:
                logger.error(f"处理报文异常: {e}")
                if self._running:
                    time.sleep(0.1)

        logger.info(f"停止处理CAN报文, 共处理{processed}条")

    def _process_single_message(self, channel: CANChannel, message, timestamp: float) -> None:
        """处理单个报文"""
        try:
            can_id = message.arbitration_id
            dbc_type = channel.get_dbc_type()

            # 硬件实际ID与DBC不一致时，按映射报文解码（仅CH1内DBC）
            mapped_name = HARDWARE_ID_TO_DBC_NAME.get(can_id) if channel == CANChannel.CH1 else None

            if mapped_name is None and not self._is_monitored_message(channel, can_id):
                logger.debug(f"[{channel.value}] 忽略未监控报文: ID=0x{can_id:08X}")
                return

            decode_id = can_id
            message_name = None
            if mapped_name:
                dbc_info = self.dbc_loader.get_inner_dbc()
                target_msg = dbc_info.db.get_message_by_name(mapped_name) if dbc_info else None
                if target_msg is None:
                    logger.debug(f"[{channel.value}] 映射报文不存在: {mapped_name} (ID=0x{can_id:08X})")
                    return
                decode_id = target_msg.frame_id
                message_name = mapped_name

            decoded = self.dbc_loader.decode_message(dbc_type, decode_id, message.data)

            if not decoded:
                logger.debug(f"[{channel.value}] 解码失败: ID=0x{can_id:08X} -> 0x{decode_id:08X}")
                return

            if not message_name:
                message_name = self._get_message_name(channel, can_id)
            if not message_name:
                logger.debug(f"[{channel.value}] 未找到报文名: ID=0x{can_id:08X}")
                return

            # DEBUG: 打印 WarningInfo1 的完整解码结果
            if "WarningInfo1" in message_name:
                logger.info(f"[{channel.value}] {message_name} 解码结果: {dict(decoded)}")

            with self._lock:
                if message_name not in self._signal_cache[channel]:
                    self._signal_cache[channel][message_name] = {}

                for signal_name, signal_value in decoded.items():
                    # 归一化NamedSignalValue为原始数值
                    if hasattr(signal_value, 'value'):
                        signal_value = signal_value.value

                    old_value = self._signal_cache[channel][message_name].get(signal_name)

                    if old_value != signal_value:
                        self._signal_cache[channel][message_name][signal_name] = signal_value

                        update = SignalUpdate(
                            channel=channel,
                            message_name=message_name,
                            signal_name=signal_name,
                            value=signal_value,
                            timestamp=timestamp,
                            raw_message=message
                        )

                        self._trigger_callbacks(update)

        except Exception as e:
            logger.error(f"处理报文失败: ID=0x{message.arbitration_id:X}, 错误: {e}")

    def _is_monitored_message(self, channel: CANChannel, can_id: int) -> bool:
        """检查是否为关注的报文"""
        monitored_ids = self._monitored_message_ids[channel]

        if can_id in monitored_ids:
            return True

        base_id = can_id & 0xFFFFFF00
        for mid in monitored_ids:
            if (mid & 0xFFFFFF00) == base_id:
                return True

        return False

    def _get_message_name(self, channel: CANChannel, can_id: int) -> Optional[str]:
        """根据CAN ID获取报文名称（支持基地址匹配和NBICU地址归一化）"""
        try:
            dbc_type = channel.get_dbc_type()
            dbc_info = self.dbc_loader.get_inner_dbc() if dbc_type == "inner" else self.dbc_loader.get_outer_dbc()

            if not dbc_info:
                return None

            # 硬件ID与DBC定义不匹配的特殊处理
            # 根据日志分析，硬件使用不同的ID模式
            if dbc_type == "inner":
                # 硬件ID到DBC报文名的映射表（基于日志分析）
                # 注意：0x18A2F2F2 对应 WarningInfo3（含 CurrentLoop_HighWarning），
                # 不能映射到 WarningInfo2，否则环流信号读不到
                hardware_id_to_dbc_name = HARDWARE_ID_TO_DBC_NAME
                
                if can_id in hardware_id_to_dbc_name:
                    target_name = hardware_id_to_dbc_name[can_id]
                    for message in dbc_info.db.messages:
                        if message.name == target_name:
                            logger.debug(f"硬件ID-DBC映射: 0x{can_id:08X} -> {target_name} (原DBC ID=0x{message.frame_id:08X})")
                            return message.name
            
            # 先尝试精确匹配
            for message in dbc_info.db.messages:
                if message.frame_id == can_id:
                    return message.name

            # 再尝试基地址匹配
            base_id = can_id & 0xFFFFFF00
            for message in dbc_info.db.messages:
                msg_base = message.frame_id & 0xFFFFFF00
                if msg_base == base_id:
                    return message.name

            return None

        except Exception as e:
            logger.error(f"获取报文名称失败: ID=0x{can_id:X}, 错误: {e}")
            return None

    def _trigger_callbacks(self, update: SignalUpdate) -> None:
        """触发回调"""
        for callback in self._callbacks:
            if callback.matches(update.message_name, update.signal_name):
                callback.invoke(update)

    def subscribe(self, callback: Callable[[SignalUpdate], None],
                  channel: Optional[CANChannel] = None,
                  message_name: Optional[str] = None,
                  signal_name: Optional[str] = None) -> None:
        """订阅信号更新"""
        with self._lock:
            callback_wrapper = SignalCallback(callback, message_name, signal_name)
            self._callbacks.append(callback_wrapper)

    def unsubscribe(self, callback: Callable[[SignalUpdate], None]) -> None:
        """取消订阅"""
        with self._lock:
            self._callbacks = [cb for cb in self._callbacks if cb.callback != callback]

    def get_signal_value(self, channel: CANChannel, message_name: str, signal_name: str) -> Optional[Any]:
        """获取信号值"""
        with self._lock:
            channel_cache = self._signal_cache.get(channel)
            if not channel_cache:
                return None

            message_cache = channel_cache.get(message_name)
            if not message_cache:
                return None

            return message_cache.get(signal_name)

    def get_all_signal_values(self, channel: CANChannel) -> Dict[str, Dict[str, Any]]:
        """获取指定通道的所有信号值"""
        with self._lock:
            return self._signal_cache[channel].copy()

    def get_message_values(self, channel: CANChannel, message_name: str) -> Dict[str, Any]:
        """获取指定报文的所有信号值"""
        with self._lock:
            channel_cache = self._signal_cache.get(channel)
            if not channel_cache:
                return {}

            return channel_cache.get(message_name, {}).copy()

    def clear_cache(self, channel: Optional[CANChannel] = None) -> None:
        """清除信号缓存"""
        with self._lock:
            if channel:
                self._signal_cache[channel].clear()
            else:
                for ch in self._signal_cache:
                    self._signal_cache[ch].clear()

    def is_running(self) -> bool:
        """检查是否在运行"""
        return self._running

    def add_monitored_message(self, channel: CANChannel, can_id: int) -> None:
        """添加关注的报文ID"""
        with self._lock:
            self._monitored_message_ids[channel].add(can_id)

    def remove_monitored_message(self, channel: CANChannel, can_id: int) -> None:
        """移除关注的报文ID"""
        with self._lock:
            self._monitored_message_ids[channel].discard(can_id)

    def get_monitored_messages(self, channel: CANChannel) -> Set[int]:
        """获取关注的报文ID"""
        with self._lock:
            return self._monitored_message_ids[channel].copy()

    def wait_for_signal(self, channel: CANChannel, message_name: str, signal_name: str,
                       timeout: float = 5.0) -> Optional[Any]:
        """等待信号出现"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._stop_event.is_set():
                return None
            value = self.get_signal_value(channel, message_name, signal_name)
            if value is not None:
                return value
            time.sleep(0.01)

        return None

    def wait_for_signal_change(self, channel: CANChannel, message_name: str, signal_name: str,
                              old_value: Any, timeout: float = 5.0) -> Optional[Any]:
        """等待信号变化"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._stop_event.is_set():
                return None
            new_value = self.get_signal_value(channel, message_name, signal_name)
            if new_value is not None and new_value != old_value:
                return new_value
            time.sleep(0.01)

        return None
