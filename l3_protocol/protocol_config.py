"""
BMS 485 Protocol Configuration - L3
优先从Excel文件自动加载，失败时回退到内置配置
"""

import os
import sys
import glob as _glob

# 添加父目录到路径以导入shared模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.excel_parser import parse_excel

PROTOCOL_SOURCE = ""


def _load_from_excel():
    global PROTOCOL_SOURCE
    xlsx_files = _glob.glob(os.path.join(os.path.dirname(__file__), '*.xlsx'))
    xlsx_files = [f for f in xlsx_files if not os.path.basename(f).startswith('~')]
    if not xlsx_files:
        return False
    target = None
    for f in xlsx_files:
        name = os.path.basename(f)
        if '通讯信号' in name or 'MODBUS' in name or 'modbus' in name:
            target = f
            break
    if not target:
        target = xlsx_files[0]
    result = parse_excel(target)
    if result is None:
        return False
    PROTOCOL_SOURCE = result['source_info']
    return result


_excel_data = _load_from_excel()

if _excel_data:
    REGISTER_GROUPS = _excel_data['register_groups']
    POLL_GROUPS = _excel_data['poll_groups']
    STATUS_TABS = _excel_data['status_tabs']
else:
    PROTOCOL_SOURCE = "内置配置 V1.1"
    REGISTER_GROUPS = {}
    POLL_GROUPS = []
    STATUS_TABS = []
