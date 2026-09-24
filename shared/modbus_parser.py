"""
Modbus RTU协议解析器
CRC16计算、帧构建、响应解析、寄存器解码
"""

from typing import Any, Dict, List, Optional, Union


def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def verify_crc(frame: bytes) -> bool:
    if len(frame) < 3:
        return False
    data = frame[:-2]
    received_crc = frame[-2:]
    calculated_crc = crc16_modbus(data)
    return received_crc == calculated_crc


def build_read_request(slave_id: int, start_addr: int, quantity: int) -> bytes:
    frame = bytes([
        slave_id & 0xFF,
        0x03,
        (start_addr >> 8) & 0xFF,
        start_addr & 0xFF,
        (quantity >> 8) & 0xFF,
        quantity & 0xFF
    ])
    return frame + crc16_modbus(frame)


def build_write_request(slave_id: int, addr: int, value: int) -> bytes:
    frame = bytes([
        slave_id & 0xFF,
        0x06,
        (addr >> 8) & 0xFF,
        addr & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF
    ])
    return frame + crc16_modbus(frame)


def parse_read_response(response: bytes) -> Optional[dict]:
    if response is None or len(response) < 5:
        return None
    result = {
        'slave_id': response[0],
        'function_code': response[1],
        'byte_count': response[2],
        'registers': [],
        'crc_valid': verify_crc(response),
        'raw_hex': ' '.join(f'{b:02X}' for b in response)
    }
    if result['function_code'] & 0x80:
        result['exception_code'] = response[2] if len(response) > 2 else 0
        return result
    byte_count = result['byte_count']
    for i in range(3, 3 + byte_count, 2):
        if i + 1 < len(response):
            reg_val = (response[i] << 8) | response[i + 1]
            result['registers'].append(reg_val)
    return result


def decode_register(value: int, data_type: str, bit_start: int, bit_length: int,
                    factor: float, offset: float, enum_map: dict = None) -> any:
    mask = (1 << bit_length) - 1
    raw = (value >> bit_start) & mask
    if data_type == "int16" and raw >= 32768:
        raw -= 65536
    physical = raw * factor + offset
    if enum_map and raw in enum_map:
        return enum_map[raw]
    if isinstance(physical, float):
        if physical == int(physical):
            return int(physical)
        return round(physical, 2)
    return physical


def decode_registers(raw_registers: list, register_defs: list, start_addr: Optional[int] = None) -> dict:
    result = {}
    addr_to_regs = {}
    for reg in register_defs:
        addr = reg[0]
        if addr not in addr_to_regs:
            addr_to_regs[addr] = []
        addr_to_regs[addr].append(reg)

    if start_addr is None:
        if not register_defs:
            return {}
        start_addr = register_defs[0][0]

    for i, raw_val in enumerate(raw_registers):
        current_addr = start_addr + i
        if current_addr in addr_to_regs:
            for reg_def in addr_to_regs[current_addr]:
                name = reg_def[1]
                data_type = reg_def[2]
                bit_start = reg_def[3]
                bit_length = reg_def[4]
                factor = reg_def[5]
                offset = reg_def[6]
                enum_map = reg_def[9]
                decoded = decode_register(raw_val, data_type, bit_start, bit_length,
                                          factor, offset, enum_map)
                result[name] = decoded
    return result


def parse_batch_response(response: bytes, start_addr: int, reg_defs: list) -> Optional[dict]:
    parsed = parse_read_response(response)
    if parsed is None or not parsed['crc_valid']:
        return None
    if parsed['function_code'] & 0x80:
        return None
    return decode_registers(parsed['registers'], reg_defs, start_addr)


def bytes_to_hex(data: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in data)
