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

# 数据类型常量
REG_UINT16 = "uint16"
REG_INT16 = "int16"
REG_UINT8 = "uint8"
REG_BITFIELD = "bitfield"

# 内置枚举定义
RUN_STATE_ENUM = {
    0: "无效", 1: "自检", 2: "放电", 3: "充电", 4: "充电完成",
    5: "急停", 6: "系统保护", 7: "充电保护", 8: "放电保护",
    9: "静置", 10: "关机", 11: "待机", 12: "预充", 13: "充电加热",
    14: "簇上电中", 15: "簇压均衡中"
}
ALARM_LEVEL_ENUM = {0: "无报警", 1: "一级报警", 2: "二级报警", 3: "三级报警"}
INSULATION_ENUM = {0: "正/负对地相等", 1: "正对地绝缘电阻小", 2: "负对地绝缘电阻小"}
RELAY_STATE_ENUM = {0: "断开", 1: "闭合"}
CHRG_GUN_ENUM = {0: "未插入", 1: "已插入"}
RELAY_FAULT_ENUM = {0: "无报警", 1: "开路", 2: "粘连", 3: "预留"}

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
