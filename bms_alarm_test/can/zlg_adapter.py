"""
ZLG USBCAN-II 驱动封装
基于 ControlCAN.dll 的 VCI API（32位Python专用）
"""

import ctypes
import logging
import os
import time
from typing import Dict, Optional
from dataclasses import dataclass

from bms_alarm_test.config.settings import BaudRate

logger = logging.getLogger(__name__)

# ── 常量 ──
VCI_USBCAN2 = 4
VCI_USBCAN2A = 3
STATUS_OK = 1
STATUS_ERR = 0

# VCI_OpenDevice 返回值
ERR_DEVICE_NOT_FOUND = 0
ERR_DEVICE_OPENED = 2
ERR_DEVICE_OPEN_FAIL = 3

# BTR0/BTR1 波特率定时值（基于8MHz晶振）
_BAUDRATE_TIMING = {
    BaudRate.BAUD_10K:  (0x31, 0x1C),
    BaudRate.BAUD_20K:  (0x18, 0x1C),
    BaudRate.BAUD_50K:  (0x09, 0x1C),
    BaudRate.BAUD_100K: (0x04, 0x1C),
    BaudRate.BAUD_125K: (0x03, 0x1C),
    BaudRate.BAUD_250K: (0x01, 0x1C),
    BaudRate.BAUD_500K: (0x00, 0x1C),
    BaudRate.BAUD_800K: (0x00, 0x16),
    BaudRate.BAUD_1M:   (0x00, 0x14),
}

# ControlCAN.dll 搜索路径（优先有依赖文件的目录）
_DLL_SEARCH_PATHS = [
    r'D:\programfiles\JDI\BMS\ControlCAN.dll',
    r'D:\programfiles\CANTest\ControlCAN.dll',
    os.path.join(os.path.dirname(__file__), '..', '..', 'ControlCAN.dll'),
]

# 日志文件路径
_LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
_LOG_FILE = os.path.join(_LOG_DIR, 'can_driver.log')


def _ensure_log_dir():
    """确保日志目录存在"""
    if not os.path.exists(_LOG_DIR):
        try:
            os.makedirs(_LOG_DIR)
        except OSError:
            pass


# ── VCI 数据结构 ──
class VCI_INIT_CONFIG(ctypes.Structure):
    _fields_ = [
        ('AccCode', ctypes.c_uint),
        ('AccMask', ctypes.c_uint),
        ('Reserved', ctypes.c_uint),
        ('Filter', ctypes.c_ubyte),
        ('Timing0', ctypes.c_ubyte),
        ('Timing1', ctypes.c_ubyte),
        ('Mode', ctypes.c_ubyte),
    ]


class VCI_INIT_CONFIG_EX(ctypes.Structure):
    _fields_ = [
        ('AccCode', ctypes.c_uint),
        ('AccMask', ctypes.c_uint),
        ('Reserved', ctypes.c_uint),
        ('Filter', ctypes.c_ubyte),
        ('Timing0', ctypes.c_ubyte),
        ('Timing1', ctypes.c_ubyte),
        ('Mode', ctypes.c_ubyte),
        ('CAN_NET', ctypes.c_ubyte),
    ]


class VCI_BOARD_INFO(ctypes.Structure):
    _fields_ = [
        ('hw_Version', ctypes.c_ushort),
        ('fw_Version', ctypes.c_ushort),
        ('dr_Version', ctypes.c_ushort),
        ('in_Version', ctypes.c_ushort),
        ('irq_Num', ctypes.c_ushort),
        ('can_Num', ctypes.c_ubyte),
        ('str_Serial_Num', ctypes.c_ubyte * 20),
        ('str_hw_Type', ctypes.c_ubyte * 40),
        ('reserved', ctypes.c_ushort * 4),
    ]


class VCI_ERR_INFO(ctypes.Structure):
    _fields_ = [
        ('ErrCode', ctypes.c_uint),
        ('Passive_ErrData', ctypes.c_ubyte * 3),
        ('Arv_Lost_ErrData', ctypes.c_ubyte),
    ]


class VCI_CAN_OBJ(ctypes.Structure):
    _fields_ = [
        ('ID', ctypes.c_uint),
        ('TimeStamp', ctypes.c_uint),
        ('TimeFlag', ctypes.c_ubyte),
        ('SendType', ctypes.c_ubyte),
        ('RemoteFlag', ctypes.c_ubyte),
        ('ExternFlag', ctypes.c_ubyte),
        ('DataLen', ctypes.c_ubyte),
        ('Data', ctypes.c_ubyte * 8),
        ('Reserved', ctypes.c_ubyte * 3),
    ]


class VCI_FILTER_RECORD(ctypes.Structure):
    _fields_ = [
        ('ExtFrame', ctypes.c_uint),
        ('Start', ctypes.c_uint),
        ('End', ctypes.c_uint),
    ]


# ── 兼容消息类 ──
class _CompatMessage:
    """兼容 can.Message 接口"""
    __slots__ = ('arbitration_id', 'data', 'is_extended_id', 'timestamp')

    def __init__(self, arbitration_id: int, data: bytes, is_extended_id: bool = True, timestamp: float = 0):
        self.arbitration_id = arbitration_id
        self.data = data
        self.is_extended_id = is_extended_id
        self.timestamp = timestamp


# ── 设备信息 ──
@dataclass
class ZLGDeviceInfo:
    device_type: str
    device_index: int
    channel_count: int
    serial_number: str
    hardware_version: str
    firmware_version: str


class ZLGAdapterError(Exception):
    pass


class ZLGAdapter:
    """ZLG USBCAN 单个通道适配器（只负责初始化/关闭自己的通道）"""

    def __init__(self, channel: int = 0, baudrate: BaudRate = BaudRate.BAUD_500K):
        self.channel = channel
        self.baudrate = baudrate
        self.is_connected = False
        self.device_info: Optional[ZLGDeviceInfo] = None

        self._dll = None
        self._dev_type = VCI_USBCAN2
        self._dev_index = 0

    def _load_dll(self):
        """加载 ControlCAN.dll，多种回退策略"""
        if self._dll is not None:
            return
        import ctypes, os
        loaders = [
            lambda p: ctypes.WinDLL(p),
            lambda p: ctypes.cdll.LoadLibrary(p),
        ]
        last_err = None
        for path in _DLL_SEARCH_PATHS:
            if not os.path.exists(path):
                logger.debug(f"ControlCAN.dll 不存在: {path}")
                continue
            dll_dir = os.path.dirname(path)
            if dll_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')
            for i, loader in enumerate(loaders):
                try:
                    self._dll = loader(path)
                    logger.info(f"ControlCAN.dll 加载成功({i}): {path}")
                    return
                except Exception as e:
                    last_err = e
                    logger.debug(f"ControlCAN.dll 加载方式{i}失败: {path}, {e}")
        raise ZLGAdapterError(
            f"无法加载 ControlCAN.dll（最后错误: {last_err}）"
        )

    def init_channel(self, dll, dev_type, dev_index) -> bool:
        """初始化单个CAN通道（设备已由 Manager 打开）"""
        self._dll = dll
        self._dev_type = dev_type
        self._dev_index = dev_index

        btr0, btr1 = _BAUDRATE_TIMING.get(self.baudrate, (0x00, 0x1C))

        cfg = VCI_INIT_CONFIG()
        cfg.AccCode = 0x00000000
        cfg.AccMask = 0xFFFFFFFF
        cfg.Filter = 0
        cfg.Timing0 = btr0
        cfg.Timing1 = btr1
        cfg.Mode = 0

        ret = self._dll.VCI_InitCAN(self._dev_type, self._dev_index, self.channel, ctypes.byref(cfg))
        if ret != STATUS_OK:
            raise ZLGAdapterError(f"VCI_InitCAN 通道{self.channel} 失败，返回={ret}")

        ret = self._dll.VCI_StartCAN(self._dev_type, self._dev_index, self.channel)
        if ret != STATUS_OK:
            stop_fn = getattr(self._dll, 'VCI_StopCAN', None) or self._dll.VCI_ResetCAN
            stop_fn(self._dev_type, self._dev_index, self.channel)
            raise ZLGAdapterError(f"VCI_StartCAN 通道{self.channel} 失败，返回={ret}")

        self.is_connected = True
        logger.info(f"CAN通道{self.channel}启动成功 (波特率={self.baudrate})")
        return True

    def close_channel(self):
        """关闭单个通道"""
        try:
            if self._dll and self.is_connected:
                if hasattr(self._dll, 'VCI_StopCAN'):
                    self._dll.VCI_StopCAN(self._dev_type, self._dev_index, self.channel)
                else:
                    self._dll.VCI_ResetCAN(self._dev_type, self._dev_index, self.channel)
                logger.info(f"CAN通道{self.channel}已停止")
        except Exception as e:
            logger.warning(f"关闭通道{self.channel}异常: {e}")
        finally:
            self.is_connected = False

    def send(self, arbitration_id: int, data: bytes, extended_id: bool = True) -> bool:
        if not self.is_connected:
            raise ZLGAdapterError("未连接")

        msg = VCI_CAN_OBJ()
        msg.ID = arbitration_id
        msg.SendType = 0
        msg.RemoteFlag = 0
        msg.ExternFlag = 1 if extended_id else 0
        msg.DataLen = min(len(data), 8)
        for i in range(msg.DataLen):
            msg.Data[i] = data[i]

        data_hex = ' '.join(f'{msg.Data[i]:02X}' for i in range(msg.DataLen))
        logger.debug(f"[ZLGAdapter] 发送报文: ID=0x{arbitration_id:08X} "
                     f"帧={'扩展' if extended_id else '标准'} "
                     f"数据=[{data_hex}] 长度={msg.DataLen}")

        ret = self._dll.VCI_Transmit(self._dev_type, self._dev_index, self.channel, ctypes.byref(msg), 1)
        if not ret:
            logger.warning(f"[ZLGAdapter] VCI_Transmit 返回={ret}, 报文发送失败")
        return ret > 0

    def recv(self, timeout: float = 0.1):
        """接收一条CAN报文（兼容 can_listener 接口）"""
        buf_count = self._dll.VCI_GetReceiveNum(self._dev_type, self._dev_index, self.channel)
        if buf_count > 0:
            logger.debug(f"[ZLGAdapter] CH{self.channel} 接收缓冲区内有 {buf_count} 条报文")
        result = self.receive(timeout=timeout)
        if result is None:
            return None
        return _CompatMessage(
            arbitration_id=result['id'],
            data=result['data'],
            is_extended_id=result.get('eff', True),
            timestamp=result.get('timestamp', 0),
        )

    def receive(self, timeout: float = 0.1) -> Optional[dict]:
        if not self.is_connected:
            return None

        buf_count = self._dll.VCI_GetReceiveNum(self._dev_type, self._dev_index, self.channel)
        if buf_count == 0 and timeout > 0:
            time.sleep(timeout)
            buf_count = self._dll.VCI_GetReceiveNum(self._dev_type, self._dev_index, self.channel)

        if buf_count > 0:
            count = min(buf_count, 1)
            msgs = (VCI_CAN_OBJ * count)()
            actual = self._dll.VCI_Receive(self._dev_type, self._dev_index, self.channel, ctypes.byref(msgs), count, int(timeout * 1000))
            if actual > 0:
                m = msgs[0]
                return {
                    'id': m.ID,
                    'data': bytes(m.Data[:m.DataLen]),
                    'eff': m.ExternFlag == 1,
                    'timestamp': m.TimeStamp / 1000.0 if m.TimeFlag else 0,
                }
        return None

    def set_baud_rate(self, channel: int, baud_rate: BaudRate) -> bool:
        self.baudrate = baud_rate
        return True

    def test_connection(self, channel: int) -> bool:
        return self.is_connected

    def get_status(self) -> Dict:
        return {
            "connected": self.is_connected,
            "channel": self.channel,
            "baudrate": self.baudrate.value,
            "device_info": str(self.device_info) if self.device_info else "Unknown",
        }


class ZLGAdapterManager:
    """管理物理设备（只开一次 VCI_OpenDevice，关闭时一起关）"""

    # 支持的设备类型，按优先级排列
    DEVICE_TYPES = [
        (4, "USBCAN-II"),
        (3, "USBCAN-IIA"),
    ]

    def __init__(self):
        self.adapters: Dict[int, ZLGAdapter] = {}
        self._dll = None
        self._dev_type = VCI_USBCAN2
        self._dev_type_name = "USBCAN-II"
        self._dev_index = 0
        self._device_opened = False

    def initialize(self) -> bool:
        return True

    def _load_dll(self):
        if self._dll is not None:
            return
        import ctypes, os
        loaders = [
            lambda p: ctypes.WinDLL(p),
            lambda p: ctypes.cdll.LoadLibrary(p),
        ]
        last_err = None
        for path in _DLL_SEARCH_PATHS:
            if not os.path.exists(path):
                logger.debug(f"[Manager] ControlCAN.dll 不存在: {path}")
                continue
            dll_dir = os.path.dirname(path)
            if dll_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')
            for i, loader in enumerate(loaders):
                try:
                    self._dll = loader(path)
                    logger.info(f"[Manager] ControlCAN.dll 加载成功({i}): {path}")
                    return
                except Exception as e:
                    last_err = e
                    logger.debug(f"[Manager] 加载方式{i}失败: {path}, {e}")
        raise ZLGAdapterError(
            f"[Manager] 无法加载 ControlCAN.dll（最后错误: {last_err}）"
        )

    def _find_usb_device(self) -> int:
        """检测连接的USB设备数量，返回找到的设备数"""
        try:
            buf_size = 50
            buf = (ctypes.c_uint * buf_size)()
            count = self._dll.VCI_FindUsbDevice(buf, buf_size)
            logger.info(f"[Manager] VCI_FindUsbDevice: 找到 {count} 个USB设备")
            if count > 0:
                for i in range(min(count, buf_size)):
                    info = VCI_BOARD_INFO()
                    self._dll.VCI_GetBoardInfo(i, ctypes.byref(info))
                    serial = ''.join(chr(c) for c in info.str_Serial_Num if c > 0)
                    hw_type = ''.join(chr(c) for c in info.str_hw_Type if c > 0).strip()
                    logger.info(f"[Manager] 设备{i}: 类型={hw_type}, 串号={serial}, CAN口={info.can_Num}")
            return count
        except Exception as e:
            logger.warning(f"[Manager] VCI_FindUsbDevice 异常: {e}")
            return -1

    def _try_open_device(self, dev_type, dev_type_name, dev_index=0) -> bool:
        """尝试用指定设备类型打开设备"""
        ret = self._dll.VCI_OpenDevice(dev_type, dev_index, 0)
        if ret == STATUS_OK:
            self._dev_type = dev_type
            self._dev_type_name = dev_type_name
            self._dev_index = dev_index
            logger.info(f"[Manager] VCI_OpenDevice 成功 (类型={dev_type_name}, 索引={dev_index})")
            return True

        logger.warning(f"[Manager] VCI_OpenDevice 失败 (类型={dev_type_name}, 索引={dev_index}), 返回={ret}")
        return False

    def _open_device(self) -> bool:
        """打开物理设备（尝试多种设备类型，只执行一次）"""
        if self._device_opened:
            return True

        self._load_dll()

        # 尝试检测USB设备（部分旧版本DLL没有此函数，跳过即可）
        found = self._find_usb_device()
        if found == 0:
            logger.warning("[Manager] VCI_FindUsbDevice 未检测到设备（旧版DLL可能不支持此函数），将直接尝试 VCI_OpenDevice")
        elif found < 0:
            logger.warning("[Manager] VCI_FindUsbDevice 执行失败（旧版DLL可能不支持），将直接尝试 VCI_OpenDevice")

        # 关闭之前可能残留的打开状态
        try:
            self._dll.VCI_CloseDevice(self._dev_type, 0)
            time.sleep(0.3)
        except Exception:
            pass

        # 尝试每种设备类型
        for dev_type, dev_type_name in self.DEVICE_TYPES:
            if self._try_open_device(dev_type, dev_type_name):
                self._device_opened = True

                # 读取设备信息
                board_info = self._read_board_info()
                if board_info:
                    for adapter in self.adapters.values():
                        if adapter.device_info is None:
                            adapter.device_info = board_info

                return True

        # 所有类型都失败，检查常见原因
        logger.error("[Manager] 所有设备类型都无法打开，可能原因：")
        logger.error("  1. 设备已被CANTest/ZCANpro等软件占用 → 请先关闭其他程序")
        logger.error("  2. USB驱动未正确安装 → 请重新安装ControlCAN驱动")
        logger.error("  3. 设备被拔出 → 请检查USB连接")
        logger.error("  4. 需要管理员权限 → 请右键以管理员身份运行")
        return False

    def _close_device(self):
        """关闭物理设备（只执行一次）"""
        if not self._device_opened or not self._dll:
            return
        try:
            self._dll.VCI_CloseDevice(self._dev_type, self._dev_index)
            logger.info("[Manager] VCI_CloseDevice 成功")
        except Exception as e:
            logger.warning(f"[Manager] VCI_CloseDevice 异常: {e}")
        finally:
            self._device_opened = False

    def create_adapter(self, channel: int, baudrate: BaudRate = BaudRate.BAUD_500K) -> ZLGAdapter:
        """创建适配器，channel 为逻辑通道号(1,2)，内部映射到物理通道(0,1)"""
        phys_channel = channel - 1  # 逻辑通道1→物理0, 逻辑通道2→物理1
        if phys_channel in self.adapters:
            return self.adapters[phys_channel]
        adapter = ZLGAdapter(channel=phys_channel, baudrate=baudrate)
        self.adapters[phys_channel] = adapter
        return adapter

    def get_adapter(self, channel: int) -> Optional[ZLGAdapter]:
        """获取适配器，channel 为逻辑通道号(1,2)"""
        phys_channel = channel - 1
        return self.adapters.get(phys_channel)

    def open_and_init_all(self, channels_config: Dict[int, BaudRate]) -> Dict[int, Optional[ZLGAdapter]]:
        """统一打开设备并初始化所有通道"""
        results: Dict[int, Optional[ZLGAdapter]] = {}

        if not self._open_device():
            for ch in channels_config:
                results[ch] = None
            return results

        board_info = self._read_board_info()

        for ch, baudrate in channels_config.items():
            try:
                adapter = self.create_adapter(ch, baudrate)
                if board_info:
                    adapter.device_info = board_info
                adapter.init_channel(self._dll, self._dev_type, self._dev_index)
                results[ch] = adapter
            except Exception as e:
                logger.warning(f"通道{ch}初始化失败: {e}")
                results[ch] = None

        return results

    def _read_board_info(self) -> Optional[ZLGDeviceInfo]:
        try:
            info = VCI_BOARD_INFO()
            ret = self._dll.VCI_ReadBoardInfo(self._dev_type, self._dev_index, ctypes.byref(info))
            if ret == STATUS_OK:
                serial = ''.join(chr(c) for c in info.str_Serial_Num if c > 0)
                hw = info.hw_Version
                fw = info.fw_Version
                device_info = ZLGDeviceInfo(
                    device_type=self._dev_type_name,
                    device_index=self._dev_index,
                    channel_count=info.can_Num,
                    serial_number=serial,
                    hardware_version=f"V{hw >> 8}.{hw & 0xFF:02x}",
                    firmware_version=f"V{fw >> 8}.{fw & 0xFF:02x}",
                )
                logger.info(f"[Manager] 设备信息: {device_info}")
                return device_info
        except Exception as e:
            logger.warning(f"[Manager] 读取设备信息失败: {e}")
        return None

    def stop_can(self):
        for adapter in self.adapters.values():
            adapter.close_channel()
        self._close_device()

    def shutdown(self):
        self.stop_can()
        self.adapters.clear()
        self._dll = None


def _setup_file_logging():
    """配置文件日志（仅当根 logger 尚无文件输出时添加，避免与 main.py 重复写日志）"""
    try:
        # 若根 logger 已挂载任意 FileHandler（如 main.py 已配置 bms_test.log），
        # 则不再添加本模块的 can_driver.log handler，避免每条日志重复写两遍。
        root_logger = logging.getLogger()
        for h in root_logger.handlers:
            if isinstance(h, logging.FileHandler):
                logger.debug(f"根 logger 已有文件处理器 {h.baseFilename}，跳过 can_driver.log 独立配置")
                return
        _ensure_log_dir()
        file_handler = logging.FileHandler(_LOG_FILE, encoding='utf-8', mode='w')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)-5s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        logger.info(f"文件日志已配置: {_LOG_FILE}")
    except Exception as e:
        print(f"配置文件日志失败: {e}")


_setup_file_logging()
