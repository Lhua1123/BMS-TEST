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


def get_app_dir() -> str:
    """
    程序数据根目录（日志、数据库、用户配置都放这里）。
    exe 环境：exe 所在目录（PyInstaller 单文件运行时 _MEIPASS 是临时目录，退出即删，
    不能用来存日志/配置）；源码环境：项目根目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_log_dir() -> str:
    """日志目录：始终在程序数据根目录下的 logs/。"""
    return os.path.join(get_app_dir(), 'logs')


def get_db_path() -> str:
    """测试结果数据库：程序数据根目录下的 data/test_results.db。"""
    return os.path.join(get_app_dir(), 'data', 'test_results.db')


def get_protocol_config_path() -> str:
    """
    protocol_user_config.json 的可写路径（保存用户配置用）。
    exe 环境下始终使用 exe 同目录，源码环境使用项目根目录。
    """
    return os.path.join(get_app_dir(), 'protocol_user_config.json')


def get_protocol_config_read_path() -> str:
    """
    protocol_user_config.json 的读取路径。
    优先用可写位置上的用户配置；exe 环境下该文件还不存在时，回退到打包进
    _MEIPASS 的默认配置（首次运行即可带上默认覆盖值，而不是全部按内置默认）。
    """
    path = get_protocol_config_path()
    if os.path.exists(path):
        return path
    bundled = getattr(sys, '_MEIPASS', None)
    if bundled:
        candidate = os.path.join(bundled, 'protocol_user_config.json')
        if os.path.exists(candidate):
            return candidate
    return path
