"""
配置键常量
集中管理settings.py中所有配置键名，避免硬编码字符串
"""

from typing import Optional


class ConfigKeys:
    """配置键常量类"""

    # ========== 路径配置 ==========
    INTERNAL_DBC_PATH = "internal_dbc_path"
    EXTERNAL_DBC_PATH = "external_dbc_path"
    FAULT_EXCEL_PATH = "fault_excel_path"
    PID_EXCEL_PATH = "pid_excel_path"
    LOG_DIRECTORY = "log_directory"

    # ========== CAN配置 ==========
    CHANNEL1_PARAMS = "channel1_params"
    CHANNEL2_PARAMS = "channel2_params"

    # ========== BMS地址配置 ==========
    NBCMU_ADDRESS = "nbcmu_address"
    SBCMU_ADDRESS = "sbcmu_address"

    # ========== 时序配置 ==========
    WAIT_AFTER_SEND_SEC = "wait_after_send_sec"
    CLEAR_CONFIRM_SEC = "clear_confirm_sec"
    DOMAIN_SWITCH_SEC = "domain_switch_sec"
    FRAME_INTERVAL_MS = "frame_interval_ms"
    REPEAT_INTERVAL_MS = "repeat_interval_ms"

    # ========== 其他设置 ==========
    AUTO_TEST_ENABLED = "auto_test_enabled"
    AUTO_CLEAR_FAULTS = "auto_clear_faults"
    MAX_CLEAR_RETRIES = "max_clear_retries"
    TEST_TIMEOUT_SEC = "test_timeout_sec"

    # ========== 反向映射（值→键）==========
    @classmethod
    def get_key_name(cls, value: str) -> Optional[str]:
        """根据值获取键名"""
        for attr_name in dir(cls):
            if not attr_name.startswith("_") and attr_name not in ("get_key_name",):
                attr_value = getattr(cls, attr_name)
                if attr_value == value:
                    return attr_name
        return None
