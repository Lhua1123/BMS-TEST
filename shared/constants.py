"""
共享常量定义
集中管理项目中使用的魔法数字，避免硬编码
"""

# ============ Modbus 相关常量 ============
# Modbus 保持寄存器基址偏移（实际地址 = 寄存器地址 + 40000）
MODBUS_HOLDING_REGISTER_BASE = 40000

# 串口写操作后等待时间（秒），确保数据传输完成
SERIAL_WRITE_DELAY = 0.05

# 轮询间隔默认值（秒）
DEFAULT_POLL_INTERVAL = 1.0

# 最小轮询间隔（秒）
MIN_POLL_INTERVAL = 0.1

# 最大轮询间隔（秒）
MAX_POLL_INTERVAL = 10.0

# 默认从机地址
DEFAULT_SLAVE_ID = 1

# ============ 寄存器视图显示 ============
# 寄存器视图每行显示的寄存器数量
REGISTERS_PER_ROW = 9

# ============ 日志相关 ============
# 最大日志条数（超过后丢弃旧日志）
MAX_LOG_ENTRIES = 1000

# ============ 串口通信 ============
# 串口读取超时时间（秒）
SERIAL_READ_TIMEOUT = 1.0

# 串口读取最大字节数
SERIAL_READ_MAX_BYTES = 256

# 轮询线程停止等待超时（秒）
POLL_THREAD_STOP_TIMEOUT = 2.0

# ============ 窗口与界面 ============
# 窗口默认最小尺寸
WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 900

# 窗口默认初始尺寸
WINDOW_DEFAULT_WIDTH = 1400
WINDOW_DEFAULT_HEIGHT = 1200

# 左侧面板固定宽度（像素）
LEFT_PANEL_FIXED_WIDTH = 380

# 协议配置弹窗占屏幕比例
CONFIG_DIALOG_WIDTH_RATIO = 0.65
CONFIG_DIALOG_HEIGHT_RATIO = 0.65

# 刷新间隔（毫秒）
REFRESH_INTERVAL_MS = 500

# ============ 日志清理 ============
# 日志文件保留天数（超过该天数的 .log 文件将被删除）
LOG_RETENTION_DAYS = 7

# 单个日志文件大小上限（MB），超过后将被清空/归档
LOG_MAX_SIZE_MB = 100

# 定时清理间隔（小时）
CLEANUP_INTERVAL_HOURS = 24

# ============ Excel 解析 ============
# Excel 解析最大行数
EXCEL_MAX_ROWS = 300

# Excel 最小行数（用于判断有效sheet）
EXCEL_MIN_ROWS = 10

# Excel 最小列数（用于判断有效sheet）
EXCEL_MIN_COLS = 10

# ============ Modbus 地址范围 ============
# Modbus 从机地址范围（1-247）
SLAVE_ID_MIN = 1
SLAVE_ID_MAX = 247

# 寄存器地址起始（BMS监控从地址20开始）
BMS_REGISTER_START_ADDR = 20

# ============ BMS 特定常量 ============
# 控制指令默认地址（寄存器2）
CONTROL_REGISTER_ADDR = 2

# 控制指令地址2的位定义
CTRL_BIT_POWER = 0       # 上下电指令位
CTRL_BIT_RESET = 2       # 复位/关机/消音位
CTRL_BIT_ESTOP = 4       # 急停报警位
