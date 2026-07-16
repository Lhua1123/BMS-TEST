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


class ModbusComm:
    """Modbus RTU串口通信处理器"""

    def __init__(self, port='COM4', baudrate=9600, slave_id=1, poll_interval=1.0):
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
        self.max_log_size = 1000

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
                timeout=1.0
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
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.is_connected_flag = False
        self.logger.info("已断开连接")

    @property
    def is_connected(self) -> bool:
        return self.is_connected_flag and self.serial and self.serial.is_open

    def send_request(self, frame: bytes) -> bool:
        if not self.is_connected:
            return False
        with self.lock:
            try:
                self.serial.write(frame)
                self.stats['frames_sent'] += 1
                self.log_traffic('TX', frame)
                return True
            except serial.SerialException as e:
                self.stats['last_error'] = str(e)
                self.logger.error(f"发送失败: {e}")
                return False

    def receive_response(self, timeout: float = 1.0) -> bytes:
        if not self.is_connected:
            return b''
        with self.lock:
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

    def read_registers(self, start_addr: int, quantity: int, timeout: float = 1.0) -> bytes:
        frame = build_read_request(self.slave_id, start_addr, quantity)
        if not self.send_request(frame):
            return None
        time.sleep(0.05)
        response = self.receive_response(timeout)
        if not response:
            self.stats['timeouts'] += 1
            return None
        return response

    def write_register(self, addr: int, value: int, timeout: float = 1.0) -> bytes:
        frame = build_write_request(self.slave_id, addr, value)
        if not self.send_request(frame):
            return None
        time.sleep(0.05)
        response = self.receive_response(timeout)
        if not response:
            self.stats['timeouts'] += 1
            return None
        return response

    def start_polling(self, poll_groups: list, callback):
        if self.poll_thread and self.poll_thread.is_alive():
            return
        self.stop_event.clear()

        def poll_loop():
            group_index = 0
            while not self.stop_event.is_set():
                if not self.is_connected:
                    time.sleep(0.5)
                    continue
                start_addr, quantity = poll_groups[group_index]
                response = self.read_registers(start_addr, quantity)
                timestamp = datetime.now()
                if response:
                    callback(group_index, response, timestamp)
                else:
                    callback(group_index, None, timestamp)
                group_index = (group_index + 1) % len(poll_groups)
                time.sleep(self.poll_interval)

        self.poll_thread = threading.Thread(target=poll_loop, daemon=True)
        self.poll_thread.start()
        self.logger.info("轮询已启动")

    def stop_polling(self):
        self.stop_event.set()
        if self.poll_thread:
            self.poll_thread.join(timeout=2.0)
        self.logger.info("轮询已停止")

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
