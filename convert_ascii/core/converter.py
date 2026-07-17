# Convert_ASCII_V1.1/src/core/converter.py
# 核心转换模块 - V2.0 优化版

import re
from typing import Optional, List, Tuple, Dict


class ASCIIConverter:
    """ASCII码转换核心类"""

    def __init__(self):
        self.special_chars = {0: "[NULL]", 7: "[BEL]", 8: "[BS]", 9: "[TAB]",
                              10: "[LF]", 13: "[CR]", 27: "[ESC]", 32: "[SPACE]",
                              127: "[DEL]"}
        self._special_chars_cache = {chr(k): v for k, v in self.special_chars.items()}

    def _normalize_input(self, text: str, base_type: str = None) -> str:
        text = text.strip()
        prefixes = {'binary': r'^0[bB]', 'octal': r'^0[oO]',
                    'hexadecimal': r'^0[xX]', 'decimal': r'^0[dD]'}
        if base_type and base_type in prefixes:
            text = re.sub(prefixes[base_type], '', text)
        return ' '.join(text.split())

    _BASE_MAP = {"二进制": 2, "八进制": 8, "十进制": 10, "十六进制": 16,
                  "binary": 2, "octal": 8, "decimal": 10, "hexadecimal": 16}

    def _validate_and_split(self, text: str, pattern: str, base_name: str,
                            max_val: int = 255) -> List[str]:
        clean = self._normalize_input(text, base_name)
        if not clean:
            return []
        parts = clean.split()
        base = self._BASE_MAP.get(base_name, 10)
        for p in parts:
            if not re.match(pattern, p):
                raise ValueError(f"无效{base_name}输入: '{p}'")
            if int(p, base) > max_val:
                raise ValueError(f"{base_name}值超出范围(0-{max_val}): '{p}'")
        return parts

    def _codes_to_str(self, codes: List[int]) -> str:
        return ''.join(self._special_chars_cache.get(chr(c), chr(c)) for c in codes)

    def binary_to_str(self, binary_text: str) -> Tuple[str, List[int]]:
        parts = self._validate_and_split(binary_text, r'^[01]+$', '二进制')
        codes = []
        for p in parts:
            if len(p) < 8:
                p = p.zfill(8)
            for i in range(0, len(p), 8):
                byte_s = p[i:i+8]
                if len(byte_s) < 8:
                    byte_s = byte_s.zfill(8)
                codes.append(int(byte_s, 2))
        return self._codes_to_str(codes), codes

    def hex_to_str(self, hex_text: str) -> Tuple[str, List[int]]:
        clean = self._normalize_input(hex_text, 'hexadecimal')
        parts = clean.split()
        codes = []
        for p in parts:
            if not re.match(r'^[0-9A-Fa-f]+$', p):
                raise ValueError(f"无效十六进制输入: '{p}'")
            if len(p) % 2 != 0:
                p = '0' + p
            for i in range(0, len(p), 2):
                codes.append(int(p[i:i+2], 16))
        return self._codes_to_str(codes), codes

    def octal_to_str(self, octal_text: str) -> Tuple[str, List[int]]:
        parts = self._validate_and_split(octal_text, r'^[0-7]+$', '八进制')
        codes = [int(p, 8) for p in parts]
        return self._codes_to_str(codes), codes

    def decimal_to_str(self, decimal_text: str) -> Tuple[str, List[int]]:
        parts = self._validate_and_split(decimal_text, r'^[0-9]+$', '十进制', 255)
        codes = [int(p, 10) for p in parts]
        return self._codes_to_str(codes), codes

    def str_to_all(self, text: str) -> Dict[str, str]:
        if not text:
            return {'binary': '', 'hex': '', 'octal': '',
                    'decimal': '', 'ascii_codes': ''}
        bin_parts = []; hex_parts = []; oct_parts = []; dec_parts = []; asc_parts = []
        for ch in text:
            c = ord(ch)
            bin_parts.append(format(c, '08b'))
            hex_parts.append(format(c, '02X'))
            oct_parts.append(format(c, '03o'))
            dec_parts.append(str(c))
            display = self._special_chars_cache.get(ch, ch)
            asc_parts.append(f"{c:3d}: {display}")
        return {'binary': ' '.join(bin_parts), 'hex': ' '.join(hex_parts),
                'octal': ' '.join(oct_parts), 'decimal': ' '.join(dec_parts),
                'ascii_codes': '\n'.join(asc_parts)}

    def format_output(self, value: str, base_type: str) -> str:
        if not value:
            return ""
        value = value.replace(' ', '')
        if base_type == 'binary':
            return ' '.join(value[i:i+4] for i in range(0, len(value), 4))
        elif base_type == 'hex':
            return ' '.join(value[i:i+2] for i in range(0, len(value), 2))
        return value

    @staticmethod
    def detect_type(text: str) -> Optional[str]:
        t = text.strip()
        if not t:
            return None

        lower = t.lower()
        if lower.startswith('0x'):
            return "十六进制"
        if lower.startswith('0b'):
            return "二进制"
        if lower.startswith('0o'):
            return "八进制"

        parts = t.split()
        if not parts:
            return None

        re_bin = re.compile(r'^[01]+$')
        re_hex = re.compile(r'^[0-9a-fA-F]+$')
        re_dec = re.compile(r'^[0-9]+$')

        if all(re_bin.match(p) for p in parts):
            return "二进制"

        if any(re_hex.match(p) and re.search(r'[a-fA-F]', p) for p in parts):
            return "十六进制"

        if any('8' in p or '9' in p for p in parts) and all(re_dec.match(p) for p in parts):
            return "十进制"

        if all(re_dec.match(p) for p in parts):
            try:
                vals = [int(p) for p in parts]
                if any(v > 127 for v in vals):
                    return "十六进制"
            except ValueError:
                pass
            if len(parts) >= 2:
                return "十六进制"
            return "十进制"

        if all(re_hex.match(p) for p in parts):
            return "十六进制"

        return "字符串"

    @staticmethod
    def clean_hex_input(hex_str: str) -> str:
        h = hex_str.strip().replace(' ', '').replace('0x', '').replace('0X', '')
        h = re.sub(r'^0[xX]', '', h)
        if not re.match(r'^[0-9A-Fa-f]*$', h):
            raise ValueError(f"无效的十六进制数据: '{hex_str}'")
        if len(h) % 2:
            h = '0' + h
        return h
