"""协议核对 Tab 的 ZLG 实时采集（独立开关，不依赖报警测试）"""

import logging
import threading
import time
from typing import Callable, List, Optional

from protocol_check.models import CanFrame

logger = logging.getLogger(__name__)


class LiveCanCollector:
    """独立打开 ZLG 通道收帧，停止时关闭。与报警测试互不共享状态。"""

    def __init__(self):
        self._manager = None
        self._adapter = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frames: List[CanFrame] = []
        self._on_frame: Optional[Callable[[CanFrame], None]] = None
        self.channel = 1
        self.baudrate = None
        self.last_error = ""

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_on_frame(self, cb: Optional[Callable[[CanFrame], None]]) -> None:
        self._on_frame = cb

    def start(self, channel: int, baudrate) -> bool:
        self.stop()
        self.last_error = ""
        self.channel = channel
        self.baudrate = baudrate
        try:
            from bms_alarm_test.can.zlg_adapter import ZLGAdapterManager, ZLGAdapterError
            from bms_alarm_test.config.settings import BaudRate
        except Exception as e:
            self.last_error = f"导入 ZLG 驱动失败: {e}"
            logger.error(self.last_error)
            return False

        if not isinstance(baudrate, BaudRate):
            try:
                baudrate = BaudRate.from_string(str(baudrate))
            except Exception:
                baudrate = BaudRate.BAUD_500K
            self.baudrate = baudrate

        try:
            self._manager = ZLGAdapterManager()
            results = self._manager.open_and_init_all({channel: baudrate})
            adapter = results.get(channel)
            if adapter is None:
                self.last_error = (
                    f"通道{channel}初始化失败：请确认 ZLG 已连接、驱动可用，"
                    f"且未被 CANTest/报警测试等程序占用"
                )
                logger.error(self.last_error)
                try:
                    self._manager.shutdown()
                except Exception:
                    pass
                self._manager = None
                return False
            self._adapter = adapter
        except Exception as e:
            self.last_error = f"打开 CAN 设备失败: {e}"
            logger.error(self.last_error)
            self._manager = None
            self._adapter = None
            return False

        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="protocol-check-live", daemon=True)
        self._thread.start()
        logger.info(f"协议核对实时采集已启动 CH{channel} baud={baudrate}")
        return True

    def _loop(self):
        ts0 = time.time()
        while not self._stop.is_set():
            adapter = self._adapter
            if adapter is None:
                break
            try:
                msg = adapter.receive(timeout=0.05)
            except Exception as e:
                logger.warning(f"实时收帧异常: {e}")
                time.sleep(0.1)
                continue
            if not msg:
                continue
            frame = CanFrame(
                timestamp=time.time() - ts0,
                arbitration_id=int(msg.get("id", 0)),
                data=bytes(msg.get("data", b"")),
                dlc=len(msg.get("data", b"")),
                is_extended=bool(msg.get("eff", True)),
                channel=self.channel,
                source="live",
            )
            with self._lock:
                self._frames.append(frame)
            if self._on_frame:
                try:
                    self._on_frame(frame)
                except Exception as e:
                    logger.debug(f"on_frame 回调异常: {e}")

    def take_frames(self) -> List[CanFrame]:
        with self._lock:
            frames = list(self._frames)
            self._frames.clear()
            return frames

    def peek_frames(self) -> List[CanFrame]:
        with self._lock:
            return list(self._frames)

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None
        try:
            if self._manager is not None:
                self._manager.shutdown()
        except Exception as e:
            logger.warning(f"关闭 ZLG 设备异常: {e}")
        self._manager = None
        self._adapter = None
        logger.info("协议核对实时采集已停止")
