"""
BMS 485 Protocol Configuration - L2
优先从Excel文件自动加载，失败时回退到内置配置
"""

import os
import sys
import glob as _glob

# 添加父目录到路径以导入shared模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.excel_parser import parse_excel

PROTOCOL_SOURCE = ""
PROTOCOL_VERSION = ""


def _load_from_excel():
    global PROTOCOL_SOURCE, PROTOCOL_VERSION
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
    PROTOCOL_VERSION = result.get('protocol_version', '')
    return result


_excel_data = _load_from_excel()

if _excel_data:
    REGISTER_GROUPS = _excel_data['register_groups']
    POLL_GROUPS = _excel_data['poll_groups']
    CONTROL_SIGNALS = _excel_data.get('control_signals', [])

    # 合并"电流情况"、"电压情况"、"极值"为一个Tab
    merged_tabs = []
    merged_signals = []
    MERGE_NAMES = {"电流情况", "电压情况", "极值"}
    for tab_name, signals in _excel_data['status_tabs']:
        if tab_name in MERGE_NAMES:
            merged_signals.extend(signals)
        else:
            merged_tabs.append((tab_name, signals))
    if merged_signals:
        merged_tabs.insert(3, ("电气参数", merged_signals))
    STATUS_TABS = merged_tabs
else:
    PROTOCOL_SOURCE = "内置配置 V1.1"
    PROTOCOL_VERSION = "builtin"
    REGISTER_GROUPS = {}
    POLL_GROUPS = []
    STATUS_TABS = []
    CONTROL_SIGNALS = []
