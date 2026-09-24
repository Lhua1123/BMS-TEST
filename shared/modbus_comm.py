"""
Modbus RTU串口通信模块
管理串口连接、帧发送/接收、连续轮询、写寄存器
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging
from datetime import datetime

from shared.modbus_parser import build_read_request, build_write_request, crc16_modbus, bytes_to_hex
from shared.constants import (
    SERIAL_WRITE_DELAY,
    MAX_LOG_ENTRIES,
    SERIAL_READ_TIMEOUT,
    POLL_THREAD_STOP_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    HEARTBEAT_REGISTER_ADDR,
    DEFAULT_HEARTBEAT_INTERVAL
)


class ModbusComm:
    """Modbus RTU串口通信处理器"""

    def __init__(self, port='COM4', baudrate=9600, slave_id=1, poll_interval=DEFAULT_POLL_INTERVAL):
        self.port = port
        self.baudrate = baudrate
        self.slave_id = slave_id
        self.poll_interval = poll_interval

        self.serial = None
        self.is_connected_flag = False
        self.lock = threading.Lock()
        self.poll_thread = None
        self.stop_event = threading.Event()

        self.stats = {
            'frames_sent': 0,
            'frames_received': 0,
            'crc_errors': 0,
            'timeouts': 0,
            'last_error': None
        }

        self.traffic_log = []
        self.max_log_size = MAX_LOG_ENTRIES

        # 心跳相关
        self.heartbeat_thread = None
        self.heartbeat_stop_event = threading.Event()
        self.heartbeat_interval = DEFAULT_HEARTBEAT_INTERVAL
        self.heartbeat_addr = HEARTBEAT_REGISTER_ADDR
        self._heartbeat_counter = 0
        self._active_poll_groups = []

        self.logger = logging.getLogger('ModbusComm')
        self.logger.setLevel(logging.DEBUG)

    @staticmethod
    def list_available_ports() -> list:
        ports = serial.tools.list_ports.comports()
        return [p.device for p in sorted(ports)]

    def connect(self) -> bool:
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_READ_TIMEOUT
            )
            self.is_connected_flag = True
            self.logger.info(f"已连接 {self.port} @ {self.baudrate}")
            return True
        except serial.SerialException as e:
            self.stats['last_error'] = str(e)
            self.logger.error(f"连接失败: {e}")
            return False

    def disconnect(self):
        self.stop_polling()
        self.stop_heartbeat()
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.is_connected_flag = False
        self.logger.info("已断开连接")

    @property
    def is_connected(self) -> bool:
        return self.is_connected_flag and self.serial and self.serial.is_open

    def _send_request_unlocked(self, frame: bytes) -> bool:
        if not self.is_connected:
            return False
        try:
            self.serial.write(frame)
            self.stats['frames_sent'] += 1
            self.log_traffic('TX', frame)
            return True
        except serial.SerialException as e:
            self.stats['last_error'] = str(e)
            self.logger.error(f"发送失败: {e}")
            return False

    def _receive_response_unlocked(self, timeout: float = SERIAL_READ_TIMEOUT) -> bytes:
        if not self.is_connected:
            return b''
        try:
            self.serial.timeout = timeout
            response = self.serial.read(256)
            if response:
                self.stats['frames_received'] += 1
                self.log_traffic('RX', response)
            return response
        except serial.SerialException as e:
            self.stats['last_error'] = str(e)
            self.logger.error(f"接收失败: {e}")
            return b''

    def send_request(self, frame: bytes) -> bool:
        if not self.is_connected:
            return False
        with self.lock:
            return self._send_request_unlocked(frame)

    def receive_response(self, timeout: float = SERIAL_READ_TIMEOUT) -> bytes:
        if not self.is_connected:
            return b''
        with self.lock:
            return self._receive_response_unlocked(timeout)

    def read_registers(self, start_addr: int, quantity: int, timeout: float = SERIAL_READ_TIMEOUT) -> bytes:
        frame = build_read_request(self.slave_id, start_addr, quantity)
        # 整帧事务持锁，避免心跳/轮询/手动指令交叉占用总线
        with self.lock:
            if not self._send_request_unlocked(frame):
                return None
            time.sleep(SERIAL_WRITE_DELAY)
            response = self._receive_response_unlocked(timeout)
            if not response:
                self.stats['timeouts'] += 1
                return None
            return response

    def write_register(self, addr: int, value: int, timeout: float = SERIAL_READ_TIMEOUT) -> bytes:
        frame = build_write_request(self.slave_id, addr, value)
        # 整帧事务持锁：发送 → 等待 → 收响应，中途不被心跳插队
        with self.lock:
            if not self._send_request_unlocked(frame):
                return None
            time.sleep(SERIAL_WRITE_DELAY)
            response = self._receive_response_unlocked(timeout)
            if not response:
                self.stats['timeouts'] += 1
                return None
            return response

    def start_polling(self, poll_groups: list, callback):
        if self.poll_thread and self.poll_thread.is_alive():
            return
        self.stop_event.clear()
        self._active_poll_groups = list(poll_groups or [])

        def poll_loop():
            group_index = 0
            while not self.stop_event.is_set():
                if not self.is_connected:
                    time.sleep(SERIAL_WRITE_DELAY * 10)  # 断开时等待0.5秒
                    continue
                groups = self._active_poll_groups
                if not groups:
                    time.sleep(SERIAL_WRITE_DELAY * 10)
                    continue
                group_index %= len(groups)
                start_addr, quantity = groups[group_index]
                response = self.read_registers(start_addr, quantity)
                timestamp = datetime.now()
                if response:
                    callback(group_index, response, timestamp)
                else:
                    callback(group_index, None, timestamp)
                group_index = (group_index + 1) % len(groups)
                time.sleep(self.poll_interval)

        self.poll_thread = threading.Thread(target=poll_loop, daemon=True)
        self.poll_thread.start()
        self.logger.info("轮询已启动")

    def update_poll_groups(self, poll_groups: list):
        """热更新轮询地址组（切换监控分组标签时用），不重启线程"""
        self._active_poll_groups = list(poll_groups or [])
        self.logger.info(f"轮询组已更新: {self._active_poll_groups}")

    def stop_polling(self):
        self.stop_event.set()
        if self.poll_thread:
            self.poll_thread.join(timeout=POLL_THREAD_STOP_TIMEOUT)
        self.logger.info("轮询已停止")

    def start_heartbeat(self, addr=HEARTBEAT_REGISTER_ADDR,
                        interval=DEFAULT_HEARTBEAT_INTERVAL):
        """
        启动心跳：周期写「心跳信号(写)」寄存器。
        协议要求 30s 内不能只出现相同值，故每次发送 0-255 循环递增。
        """
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
        self.heartbeat_addr = addr
        self.heartbeat_interval = interval
        self.heartbeat_stop_event.clear()
        self._heartbeat_counter = 0

        def heartbeat_loop():
            while not self.heartbeat_stop_event.is_set():
                if not self.is_connected:
                    time.sleep(SERIAL_WRITE_DELAY * 10)
                    continue
                value = self._heartbeat_counter & 0xFF
                response = self.write_register(self.heartbeat_addr, value)
                if response:
                    self.logger.debug(
                        f"心跳 TX: 地址{self.heartbeat_addr}=0x{value:02X} ({value})"
                    )
                self._heartbeat_counter = (self._heartbeat_counter + 1) & 0xFF
                self.heartbeat_stop_event.wait(self.heartbeat_interval)

        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        self.logger.info(
            f"心跳已启动: 写地址{self.heartbeat_addr}(心跳信号写), 值0-255循环, 间隔{self.heartbeat_interval}s"
        )

    def stop_heartbeat(self):
        """停止心跳写指令线程"""
        self.heartbeat_stop_event.set()
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=POLL_THREAD_STOP_TIMEOUT)
        self.logger.info("心跳已停止")

    def log_traffic(self, direction: str, data: bytes):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        hex_str = bytes_to_hex(data)
        entry = f"[{timestamp}] {direction}> {hex_str}"
        self.traffic_log.append(entry)
        if len(self.traffic_log) > self.max_log_size:
            self.traffic_log.pop(0)
        self.logger.debug(entry)

    def get_stats(self) -> dict:
        return self.stats.copy()

    def clear_log(self):
        self.traffic_log.clear()
