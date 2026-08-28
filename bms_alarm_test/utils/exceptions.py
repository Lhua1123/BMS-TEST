"""
自定义异常层次结构
提供清晰、具体的异常类型，便于错误处理和调试
"""


class BMSTestError(Exception):
    """
    BMS测试系统基础异常

    所有自定义异常的基类，用于捕获所有BMS测试系统相关的异常
    """
    pass


class CANError(BMSTestError):
    """CAN通信错误（连接、发送、接收失败）"""
    pass


class ConfigError(BMSTestError):
    """配置错误（文件不存在、值无效、权限不足）"""
    pass


class DBCError(BMSTestError):
    """DBC文件错误（解析失败、信号未找到）"""
    pass


class TestExecutionError(BMSTestError):
    """测试执行错误（超时、中断、硬件故障）"""
    pass


class ValidationError(BMSTestError):
    """验证错误（期望值不匹配、验证失败）"""
    pass


class DatabaseError(BMSTestError):
    """数据库错误（连接失败、写入失败、查询错误）"""
    pass


class HardwareError(BMSTestError):
    """硬件错误（设备未连接、驱动问题）"""
    pass


class TimeoutError(BMSTestError):
    """超时错误（等待信号超时、响应超时）"""
    pass


class SignalNotFoundError(BMSTestError):
    """信号未找到错误（DBC中不存在该信号）"""
    pass
