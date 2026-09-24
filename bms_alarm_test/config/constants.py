"""
常量定义
集中管理项目中所有魔法数字和字符串常量
"""

# CAN相关常量
class CANConstants:
    """CAN总线常量"""

    # 通道号
    CHANNEL_1 = 1
    CHANNEL_2 = 2

    # 报文ID定义
    DAPP_FAULTSET_MSG_ID = 0x18D1FFDF  # 故障注入报文ID
    DAPP_THRESHOLDSET_MSG_ID = 0x18D2FFDF  # 阈值设置报文ID

    # 通道0关注的报文ID
    CH0_MONITORED_IDS = {
        0x18B1FFA1,  # NBCMU01_WarningInfo1
        0x18BBFFA1,  # NBCMU01_WarningInfo2
        0x18A3FFA1,  # NBCMU01_WarningInfo3
        0x18B8FFB1,  # SBCMU01_WarningInfo
        0x18A2FFB1,  # SBCMU01_DCChrgState
        0x18FFA0F4,  # DAPP_PIDReadResp（PID读取响应）
        0x18D2FFDF,  # DAPP_ThresholdSet（阈值设置）
        # 阈值测试环境实际值（默认簇1；其他簇由引擎动态扩展）
        0x18B2FFA1,  # NBCMU01_VoltExtremeInfo
        0x18B3FFA1,  # NBCMU01_TempExtremeInfo
        0x18B4FFA1,  # NBCMU01_SysSOX
        0x18B5FFA1,  # NBCMU01_SysHVoltage
        0x18C1FF01,  # NBICU01_VoltExtremeInfo
        0x18C2FF01,  # NBICU01_TempExtremeInfo
    }

    # 通道1关注的报文ID（基础模式）
    CH1_MONITORED_BASE_IDS = {
        0x18A3F100,  # BMS_Msg01基础
        0x18A5F100,  # BMS_Msg03基础
        0x18B2F100,  # BMS_Msg15基础
        0x18B3F100,  # BMS_Msg16基础
        0x18B4F100,  # BMS_Msg17基础
    }

    # 默认波特率
    DEFAULT_BAUD_RATE = 500000

    # CAN数据长度
    CAN_DATA_LENGTH = 8

    # 最近报文缓冲上限（供 CAN 监控面板使用）
    RECENT_MESSAGE_LIMIT = 1000


# 时序常量
class TimingConstants:
    """时序配置常量"""

    # 故障注入时序
    FAULT_INJECTION_FRAME_INTERVAL_MS = 50  # 帧间隔
    FAULT_INJECTION_REPEAT_INTERVAL_MS = 200  # 两遍间隔
    FAULT_INJECTION_REPEAT_COUNT = 2  # 每遍发送次数
    FAULT_INJECTION_TOTAL_ROUNDS = 2  # 总遍数

    # 故障清除时序
    FAULT_CLEAR_FRAME_INTERVAL_MS = 50  # 清除帧间隔
    FAULT_CLEAR_REPEAT_INTERVAL_MS = 200  # 清除两遍间隔
    FAULT_CLEAR_REPEAT_COUNT = 2  # 清除每遍发送次数

    # 等待时间
    DEFAULT_INJECTION_DELAY_SEC = 1.5  # 注入后等待
    DEFAULT_CLEAR_DELAY_SEC = 0.3  # 清除后等待
    DEFAULT_CLEAR_CONFIRM_TIMEOUT_SEC = 5.0  # 清除确认超时
    DEFAULT_VERIFICATION_TIMEOUT_SEC = 5.0  # 验证超时

    # 阈值测试时序
    BASELINE_READ_TIME_SEC = 2.0  # 基线读取时间
    ALARM_WAIT_TIME_SEC = 5.0  # 报警等待时间
    RESTORE_DELAY_SEC = 1.0  # 恢复延迟


# 验证常量
class VerificationConstants:
    """验证相关常量"""

    MAX_RETRIES = 3  # 最大重试次数
    RETRY_DELAY_SEC = 0.5  # 重试延迟


# 测试常量
class TestConstants:
    """测试相关常量"""

    DEFAULT_BMS_ADDRESS = 1
    DEFAULT_DOMAIN = "NBCMU"

    # 测试暂停
    TEST_PAUSE_INTERVAL_SEC = 0.1  # 连续测试间隔

    # 重连等待
    RECONNECT_WAIT_SEC = 1.0


# UI常量
class UIConstants:
    """UI相关常量"""

    # 窗口默认大小
    DEFAULT_WINDOW_WIDTH = 1280
    DEFAULT_WINDOW_HEIGHT = 860

    # 状态更新间隔
    STATUS_UPDATE_INTERVAL_MS = 1000  # 1秒

    # 日志限制
    MAX_LOG_LINES = 1000
    LOG_TRIM_RATIO = 0.5  # 裁剪时保留的比例

    # 字体大小
    DEFAULT_FONT_SIZE = 10


# 数据库常量
class DatabaseConstants:
    """数据库相关常量"""

    # 默认路径
    DEFAULT_DB_PATH = "data/test_results.db"

    # 保留天数
    DEFAULT_RETENTION_DAYS = 30

    # 最大记录数
    MAX_RECORDS = 10000

    # 导出默认限制
    EXPORT_LIMIT = 10000


# 日志常量
class LogConstants:
    """日志相关常量"""

    # 默认日志级别
    DEFAULT_LEVEL = "INFO"

    # 日志格式
    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # 日志文件
    DEFAULT_LOG_FILE = "logs/bms_test.log"


# 文件常量
class FileConstants:
    """文件相关常量"""

    # 配置文件
    DEFAULT_CONFIG_FILE = "config/settings.json"

    # 样式表
    STYLESHEET_FILE = "style.qss"

    # Excel导出时间戳格式
    EXCEL_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

    # 时间显示格式
    TIME_DISPLAY_FORMAT = "%H:%M:%S"
    DATETIME_DISPLAY_FORMAT = "%Y-%m-%d %H:%M:%S"


# BMS地址常量
class BMSAddressConstants:
    """BMS地址范围常量"""

    # NBCMU地址范围
    NBCMU_ADDRESS_MIN = 0xA1
    NBCMU_ADDRESS_MAX = 0xA5

    # SBCMU地址范围
    SBCMU_ADDRESS_MIN = 0xB1
    SBCMU_ADDRESS_MAX = 0xB5

    # 默认地址
    DEFAULT_NBCMU_ADDRESS = 0xA1
    DEFAULT_SBCMU_ADDRESS = 0xB1


# 故障相关常量
class FaultConstants:
    """故障相关常量"""

    # 故障码范围
    FAULT_CODE_MIN = 1
    FAULT_CODE_MAX = 96

    # 故障等级
    FAULT_LEVEL_MIN = 1
    FAULT_LEVEL_MAX = 3

    # SysFailSta有效值
    SYS_FAIL_STA_VALUES = {0, 1, 2, 3}

    # 预留故障码
    RESERVED_FAULT_CODES = {48, 53, 54, 58, 66, 67, 69, 70, 73, 77}

    # 共有故障码
    SHARED_FAULT_CODES = {57, 68, 71, 81}

    # 继电器故障码（期望值含义：1=开路，2=粘连）
    RELAY_FAULT_CODES = {59, 60, 62, 63}


# PID相关常量
class PIDConstants:
    """PID相关常量"""

    # PID格式
    PID_HEX_FORMAT = "0x{:04X}"

    # 阈值默认值
    NO_THRESHOLD = "无"
