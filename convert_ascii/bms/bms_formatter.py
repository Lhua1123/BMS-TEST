# Convert_ASCII_V1.1/src/bms/bms_formatter.py
# BMS特定数据格式处理模块 - V2.0 优化版

import struct
import binascii
import re
import os
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

try:
    import cantools
    HAS_CANTOOLS = True
except ImportError:
    HAS_CANTOOLS = False

from convert_ascii.core.converter import ASCIIConverter

logger = logging.getLogger(__name__)

class BMSFormatter:
    """BMS数据格式化工具"""

    def __init__(self):
        self.bms_can_prefixes = {
            0x18A1: ("BGMU_RunState", "BGMU运行状态帧"),
            0x18A2: ("BGMU_DCChrgState", "BGMU直流充电状态"),
            0x18A3: ("BGMU_WarningInfo", "BGMU警告信息"),
            0x18A4: ("BGMU_TxTempInfo", "BGMU温度信息"),
            0x18A5: ("BGMU_BatInfo", "BGMU电池信息"),
            0x18B0: ("BCU_Standard_A1", "BCU标准数据A1"),
            0x18B1: ("BCU_Standard_A2", "BCU标准数据A2"),
            0x18B2: ("BCU_Standard_A3", "BCU标准数据A3"),
            0x18C0: ("BSU_RunState", "BSU运行状态"),
            0x18D0: ("BSU_CellData", "BSU电芯数据"),
            0x18F0: ("BSU_AlarmInfo", "BSU报警信息"),
            0x1801: ("ChargeCtrl", "充电控制"),
            0x1802: ("DischargeCtrl", "放电控制"),
            0x1A00: ("Insulation", "绝缘检测"),
        }

        self.data_types = {
            'uint8': ('B', 1), 'int8': ('b', 1),
            'uint16': ('H', 2), 'int16': ('h', 2),
            'uint32': ('I', 4), 'int32': ('i', 4),
            'float32': ('f', 4), 'double': ('d', 8),
        }

        # DBC 相关
        self.db_list = []
        self.dbc_files = []
        self.dbc_message_ids = set()
        self.signal_comments = {}

    def parse_can_id(self, can_id_hex: str) -> Dict[str, Any]:
        try:
            can_id_str = can_id_hex.lower().replace('0x', '')
            can_id_int = int(can_id_str, 16)
            priority = (can_id_int >> 26) & 0x07
            edp = (can_id_int >> 25) & 0x01
            dp = (can_id_int >> 24) & 0x01
            pf = (can_id_int >> 8) & 0xFF
            ps = can_id_int & 0xFF
            sa = can_id_int & 0xFF
            prefix = can_id_int >> 16

            # J1939 PGN
            if pf < 240:
                pgn = (dp << 16) | (pf << 8)
            else:
                pgn = (dp << 16) | (pf << 8) | ps

            info, chinese = "", ""
            for pfx_key in sorted(self.bms_can_prefixes.keys(), reverse=True):
                if (can_id_int & 0xFFFF0000) == (pfx_key << 16):
                    info, chinese = self.bms_can_prefixes[pfx_key]
                    break

            return {
                '原始值': can_id_hex,
                '十六进制': f"0x{can_id_int:08X}",
                '十进制': str(can_id_int),
                '二进制': f"{can_id_int:032b}",
                '八进制': f"0o{can_id_int:012o}",
                'ID前缀': f"0x{prefix:04X}",
                'SA地址': f"0x{sa:02X}",
                'PF(PDU格式)': f"0x{pf:02X} ({pf})",
                'PS(PDU特定)': f"0x{ps:02X} ({ps})",
                'PGN(参数组)': f"0x{pgn:04X} ({pgn})",
                '优先级': f"{priority}",
                'DP': str(dp),
                '功能说明': chinese if chinese else "未识别的CAN ID",
                '信息标识': info or "Unknown",
            }
        except Exception as e:
            return {'错误': f"CAN ID解析失败: {str(e)}"}

    def parse_can_data(self, hex_data: str) -> Dict[str, Any]:
        try:
            hex_data = hex_data.strip().replace(' ', '').replace('0x', '').replace('0X', '')
            if not re.match(r'^[0-9A-Fa-f]+$', hex_data):
                return {'错误': '无效的十六进制数据'}
            if len(hex_data) % 2 != 0:
                hex_data = '0' + hex_data

            bytes_data = bytes.fromhex(hex_data)
            data_len = len(bytes_data)

            results = {
                '原始数据': hex_data.upper(),
                '格式化十六进制': ' '.join(hex_data[i:i+2].upper() for i in range(0, len(hex_data), 2)),
                '字节数': data_len,
                '字节详情': []
            }

            for i, byte in enumerate(bytes_data):
                results['字节详情'].append({
                    '索引': i,
                    '十六进制': f"0x{byte:02X}",
                    '十进制': byte,
                    '二进制': f"{byte:08b}",
                    '有符号': struct.unpack('b', byte.to_bytes(1, 'little'))[0],
                    'ASCII': chr(byte) if 32 <= byte <= 126 else f"[{byte:02X}]",
                })

            if data_len >= 2:
                results['uint16_LE'] = struct.unpack('<H', bytes_data[:2])[0]
                results['uint16_BE'] = struct.unpack('>H', bytes_data[:2])[0]
            if data_len >= 4:
                results['uint32_LE'] = struct.unpack('<I', bytes_data[:4])[0]
                results['uint32_BE'] = struct.unpack('>I', bytes_data[:4])[0]
                try:
                    results['float32_LE'] = round(struct.unpack('<f', bytes_data[:4])[0], 4)
                    results['float32_BE'] = round(struct.unpack('>f', bytes_data[:4])[0], 4)
                except Exception:
                    pass
            if data_len >= 8:
                try:
                    results['double_LE'] = round(struct.unpack('<d', bytes_data[:8])[0], 4)
                except Exception:
                    pass

            return results
        except Exception as e:
            return {'错误': f"数据解析失败: {str(e)}"}

    def parse_can_data_display(self, hex_data: str) -> str:
        """解析CAN数据并以可读文本返回"""
        result = self.parse_can_data(hex_data)
        if '错误' in result:
            return f"❌ {result['错误']}"
        lines = []
        lines.append(f"📦 原始数据: {result['原始数据']}")
        lines.append(f"📐 字节数: {result['字节数']}")
        lines.append("")
        lines.append("📋 字节详情:")
        for b in result['字节详情']:
            lines.append(f"  Byte[{b['索引']:2d}]: {b['十六进制']}  {b['十进制']:3d}  {b['二进制']}  '{b['ASCII']}'")

        if 'uint16_LE' in result:
            lines.append("")
            lines.append("🔢 组合值:")
            lines.append(f"  uint16 LE: {result['uint16_LE']}  BE: {result['uint16_BE']}")
        if 'uint32_LE' in result:
            lines.append(f"  uint32 LE: {result['uint32_LE']}  BE: {result['uint32_BE']}")
        if 'float32_LE' in result:
            lines.append(f"  float32 LE: {result['float32_LE']}  BE: {result['float32_BE']}")
        return '\n'.join(lines)

    def format_bms_data(self, ascii_codes: List[int], format_type: str = 'standard') -> str:
        if not ascii_codes:
            return ""

        if format_type == 'hex_dump':
            lines = []
            for i in range(0, len(ascii_codes), 16):
                chunk = ascii_codes[i:i+16]
                offset = f"{i:08X}"
                hex_part = ' '.join(f"{b:02X}" for b in chunk)
                hex_part = hex_part.ljust(47)
                ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
                lines.append(f"{offset}  {hex_part}  |{ascii_part}|")
            return '\n'.join(lines)

        elif format_type == 'c_array':
            lines = []
            lines.append(f"// BMS数据 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"const uint8_t bms_data[{len(ascii_codes)}] = {{")
            for i in range(0, len(ascii_codes), 8):
                chunk = ascii_codes[i:i+8]
                hex_values = ', '.join(f"0x{b:02X}" for b in chunk)
                sep = ',' if i + 8 < len(ascii_codes) else ''
                lines.append(f"    {hex_values}{sep}")
            lines.append("};")
            return '\n'.join(lines)

        elif format_type == 'can_frame':
            lines = []
            for i, code in enumerate(ascii_codes):
                char = chr(code) if 32 <= code <= 126 else '.'
                lines.append(f"Byte[{i:2d}]: 0x{code:02X}  {code:3d}  {code:08b}  '{char}'")
            return '\n'.join(lines)

        else:
            lines = []
            lines.append(f"十六进制: {' '.join(f'{c:02X}' for c in ascii_codes)}")
            lines.append(f"十进制:   {' '.join(str(c) for c in ascii_codes)}")
            lines.append(f"二进制:   {' '.join(f'{c:08b}' for c in ascii_codes)}")
            lines.append(f"ASCII:    {''.join(chr(c) if 32 <= c <= 126 else f'[{c:02X}]' for c in ascii_codes)}")
            return '\n'.join(lines)

    def format_display_for_can_data(self, hex_data: str, fmt: str) -> str:
        """直接对十六进制字符串格式化为指定格式"""
        try:
            h = ASCIIConverter.clean_hex_input(hex_data)
        except ValueError:
            return f"错误: 无效的十六进制数据"
        codes = [int(h[i:i+2], 16) for i in range(0, len(h), 2)]
        return self.format_bms_data(codes, fmt)

    def create_bms_template(self, template_type: str) -> str:
        templates = {
            'standard_can': """--- 标准CAN数据模板 ---
CAN ID: 0x18A1FFF4
Data: 00 01 02 03 04 05 06 07
描述: BGMU运行状态帧

CAN ID: 0x18A5FFF4
Data: 64 00 32 00 03 E8 00 00
描述: BGMU电池信息 (SOC=100, SOH=50, 总电压=1000mV)

CAN ID: 0x18B0FFA1
Data: 0F A0 0E 10 0D 80 0C F0
描述: BCU标准数据A1 (电芯1~4电压)
""",
            'cell_data': """--- 电芯电压数据模板 ---
字节0-1: 最高电芯电压 (uint16, 单位: mV)
字节2-3: 最低电芯电压 (uint16, 单位: mV)
字节4:   最高电压电芯编号
字节5:   最低电压电芯编号
字节6-7: 平均电压 (uint16, 单位: mV)

示例数据: 0F A0 0E 10 01 02 0E D8
> 最高: 4000mV, 最低: 3600mV, 平均: 3800mV
""",
            'temp_data': """--- 温度数据模板 ---
字节0: 最高温度 (int8, 单位: °C)
字节1: 最低温度 (int8, 单位: °C)
字节2: 平均温度 (int8, 单位: °C)
字节3: 最高温度传感器编号
字节4: 最低温度传感器编号

示例数据: 2D 1E 26 01 05
> 最高: 45°C, 最低: 30°C, 平均: 38°C
""",
            'soc_data': """--- SOC数据模板 ---
字节0-1: SOC值 (uint16, 单位: 0.1%)
字节2-3: SOH值 (uint16, 单位: 0.1%)
字节4:   充放电状态 (0=停止, 1=充电, 2=放电)
字节5-6: 循环次数 (uint16)
字节7:   温度 (int8, 单位: °C)

示例数据: 03 E8 03 E8 01 00 0A 19
> SOC=100.0%, SOH=100.0%, 充电中, 循环10次, 25°C
""",
        }
        return templates.get(template_type, "未知模板类型")

    # ============================================================
    # DBC 导入与解码
    # ============================================================

    def load_dbc(self, dbc_file: str, encoding: str = None) -> bool:
        """加载单个 DBC 文件，自动尝试常见编码"""
        if not HAS_CANTOOLS:
            raise ImportError("cantools 未安装，请先安装依赖: pip install cantools")

        encodings = [encoding] if encoding else ['utf-8', 'gbk', 'gb2312', 'iso-8859-1']
        for enc in encodings:
            try:
                with open(dbc_file, 'r', encoding=enc) as f:
                    dbc_content = f.read()
                db = cantools.database.load_string(dbc_content)
                if not db.messages:
                    logger.warning("DBC 文件不包含任何消息: %s", dbc_file)
                    return False

                self.dbc_files.append(dbc_file)
                self.db_list.append(db)

                for message in db.messages:
                    logger.info("DBC消息: name=%s, frame_id=0x%X (%d)", message.name, message.frame_id, message.frame_id)
                    self.dbc_message_ids.add(message.frame_id)
                    for signal in message.signals:
                        if signal.comment:
                            self.signal_comments[f"{message.frame_id}_{signal.name}"] = signal.comment

                logger.info("成功加载 DBC: %s，消息数=%d", os.path.basename(dbc_file), len(db.messages))
                return True
            except UnicodeDecodeError:
                logger.warning("以 %s 编码加载 DBC 失败，尝试下一个编码", enc)
                continue
            except Exception as e:
                logger.error("加载 DBC 时出错 (编码 %s): %s", enc, e)
                continue

        raise ValueError(
            "无法加载 DBC 文件，请确保文件格式正确且使用支持的编码(UTF-8, GBK, GB2312, ISO-8859-1)"
        )

    def load_dbc_files(self, dbc_files: List[str]) -> List[str]:
        """批量加载 DBC 文件，返回成功加载的文件名列表"""
        success = []
        for dbc_file in dbc_files:
            try:
                if self.load_dbc(dbc_file):
                    success.append(os.path.basename(dbc_file))
            except Exception as e:
                logger.error("加载 DBC 文件失败: %s, 错误: %s", dbc_file, e)
        return success

    def get_loaded_dbc_files(self) -> List[Tuple[str, str]]:
        """返回已加载的 DBC 文件列表 [(文件名, 路径), ...]"""
        return [(os.path.basename(f), f) for f in self.dbc_files]

    def get_dbc_message_ids(self) -> List[str]:
        """返回所有已加载 DBC 的消息 ID 列表（格式化为 0xXXXXXXXX）"""
        return [f"0x{msg_id:08X}" for msg_id in sorted(self.dbc_message_ids)]

    def get_dbc_message_list(self) -> List[Tuple[str, str]]:
        """返回所有已加载 DBC 的消息列表 [(ID, 消息名), ...]"""
        result = []
        seen = set()
        for db in self.db_list:
            for msg in db.messages:
                if msg.frame_id not in seen:
                    seen.add(msg.frame_id)
                    result.append((f"0x{msg.frame_id:08X}", msg.name))
        return sorted(result, key=lambda x: x[0])

    def clear_dbc(self, dbc_file: str = None):
        """清空 DBC。如果指定 dbc_file，则只删除该文件；否则清空全部"""
        if dbc_file:
            if dbc_file in self.dbc_files:
                self.dbc_files.remove(dbc_file)
                # 重新构建索引
                self.db_list = []
                self.dbc_message_ids = set()
                self.signal_comments = {}
                for remaining in self.dbc_files:
                    try:
                        self.load_dbc(remaining)
                    except Exception:
                        pass
        else:
            self.db_list = []
            self.dbc_files = []
            self.dbc_message_ids = set()
            self.signal_comments = {}

    def _find_message(self, can_id: int):
        """在所有已加载 DBC 中查找匹配的消息，返回 (db, message)"""
        # 先尝试精确匹配
        for db in self.db_list:
            message = next((m for m in db.messages if m.frame_id == can_id), None)
            if message:
                return db, message

        # 尝试扩展帧掩码匹配（29位）
        masked_id = can_id & 0x1FFFFFFF
        if masked_id != can_id:
            for db in self.db_list:
                message = next((m for m in db.messages if m.frame_id == masked_id), None)
                if message:
                    logger.info("扩展帧掩码匹配: 0x%X -> 0x%X", can_id, masked_id)
                    return db, message

        return None, None

    def decode_with_dbc(self, can_id_hex: str, hex_data: str) -> Dict[str, Any]:
        """用 DBC 解码 CAN 数据，返回结构化结果"""
        if not self.db_list:
            return {'错误': '未加载 DBC 文件'}

        try:
            can_id_str = can_id_hex.lower().replace('0x', '')
            can_id_int = int(can_id_str, 16)
        except Exception as e:
            return {'错误': f"CAN ID 格式错误: {e}"}

        # 调试日志：打印所有DBC中的消息ID
        all_ids = [f"0x{m.frame_id:X}" for db in self.db_list for m in db.messages]
        logger.info("DBC中所有消息ID: %s", all_ids)
        logger.info("搜索CAN ID: 0x%X (%d)", can_id_int, can_id_int)

        db, message = self._find_message(can_id_int)
        if not message:
            return {
                'CAN ID': can_id_hex,
                '消息名': 'Unknown Message',
                '信号列表': [],
                '原始数据': hex_data,
                '提示': f'ID 0x{can_id_int:X} 在已加载的 DBC 中未找到匹配。DBC中有: {all_ids}'
            }

        try:
            h = ASCIIConverter.clean_hex_input(hex_data)
        except ValueError:
            return {'错误': f"无效的十六进制数据: {hex_data}"}

        try:
            data_bytes = bytes.fromhex(h)
        except Exception as e:
            return {'错误': f"数据转换失败: {e}"}

        try:
            decoded = db.decode_message(can_id_int, data_bytes)
        except Exception as e:
            return {'错误': f"DBC 解码失败: {e}"}

        if not decoded:
            return {
                'CAN ID': can_id_hex,
                '消息名': message.name,
                '信号列表': [],
                '原始数据': hex_data,
                '提示': '解码返回空结果'
            }

        # 按 start bit 升序排列（低位在上）
        sorted_signals = sorted(message.signals, key=lambda s: s.start)
        signal_list = []
        for signal in sorted_signals:
            if signal.name not in decoded:
                continue
            value = decoded[signal.name]
            if isinstance(value, float):
                formatted_value = "0" if abs(value) < 0.001 else f"{value:.3f}"
            else:
                formatted_value = str(value)

            signal_list.append({
                '信号名': signal.name,
                '值': formatted_value,
                '单位': signal.unit or '',
                '注释': self.signal_comments.get(f"{can_id_int}_{signal.name}", ""),
                '起始位': signal.start,
                '长度': signal.length,
            })

        return {
            'CAN ID': can_id_hex,
            '消息名': message.name,
            '信号列表': signal_list,
            '原始数据': hex_data,
            '字节数': len(data_bytes),
        }

    def parse_can_data_with_dbc(self, can_id_hex: str, hex_data: str) -> Dict[str, Any]:
        """结合 DBC 的 CAN 数据解析入口"""
        dbc_result = self.decode_with_dbc(can_id_hex, hex_data)
        if '错误' not in dbc_result and dbc_result.get('消息名') != 'Unknown Message':
            return dbc_result

        # DBC 未匹配或出错，回退到原始字节解析
        fallback = self.parse_can_data(hex_data)
        if '错误' not in fallback:
            fallback['DBC 提示'] = dbc_result.get('提示', 'DBC 未匹配，显示原始字节解析')
        return fallback
