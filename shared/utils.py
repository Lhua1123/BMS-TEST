"""
通用工具函数
"""

import os
import sys


def infer_datatype(bit_length: int, bit_start: int, factor: float, description: str) -> str:
    """
    根据位长度、起始位、因子和描述推断数据类型

    Args:
        bit_length: 位长度
        bit_start: 起始位
        factor: 精度因子
        description: 信号描述

    Returns:
        数据类型字符串: "uint8", "int16", "uint16", "bitfield"
    """
    # 位字段：长度<=8且起始位>0
    if bit_length <= 8 and bit_start is not None and bit_start > 0:
        return "bitfield"

    # 8位及以下
    if bit_length <= 8:
        # 包含位字段描述格式（如"0:xxx"）
        if description and ('0:' in description or '0：' in description):
            return "bitfield"
        return "uint8"

    # 16位
    if bit_length == 16:
        # 包含负值描述或充电标志
        if description and ('负值' in description or '正值为充电' in description):
            return "int16"
        return "uint16"

    # 介于8-16位之间
    if bit_length < 16:
        return "bitfield"

    # 默认16位无符号
    return "uint16"


def get_protocol_config_path() -> str:
    """
    获取 protocol_user_config.json 的路径。
    exe 环境下优先读取 exe 同目录，源码环境回退到项目根目录。
    """
    filename = 'protocol_user_config.json'
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(exe_dir, filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        filename
    )
