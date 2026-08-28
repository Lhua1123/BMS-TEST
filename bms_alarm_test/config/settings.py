"""
全局配置管理
移植自 报警测试/src/config/settings.py
去除PySide6依赖，使用纯Python实现
"""

import json
import logging
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional

from .config_keys import ConfigKeys
from .constants import BMSAddressConstants, DatabaseConstants, FileConstants, LogConstants, UIConstants

logger = logging.getLogger(__name__)


class BaudRate(Enum):
    """CAN波特率枚举"""
    BAUD_10K = 10000
    BAUD_20K = 20000
    BAUD_50K = 50000
    BAUD_100K = 100000
    BAUD_125K = 125000
    BAUD_250K = 250000
    BAUD_500K = 500000
    BAUD_800K = 800000
    BAUD_1M = 1000000

    @classmethod
    def from_string(cls, baud_str: str) -> 'BaudRate':
        """从字符串创建波特率"""
        baud_map = {
            "10k": cls.BAUD_10K,
            "20k": cls.BAUD_20K,
            "50k": cls.BAUD_50K,
            "100k": cls.BAUD_100K,
            "125k": cls.BAUD_125K,
            "250k": cls.BAUD_250K,
            "500k": cls.BAUD_500K,
            "800k": cls.BAUD_800K,
            "1m": cls.BAUD_1M,
        }
        return baud_map.get(baud_str.lower(), cls.BAUD_500K)

    def __str__(self) -> str:
        """转换为字符串表示"""
        baud_str_map = {
            BaudRate.BAUD_10K: "10k",
            BaudRate.BAUD_20K: "20k",
            BaudRate.BAUD_50K: "50k",
            BaudRate.BAUD_100K: "100k",
            BaudRate.BAUD_125K: "125k",
            BaudRate.BAUD_250K: "250k",
            BaudRate.BAUD_500K: "500k",
            BaudRate.BAUD_800K: "800k",
            BaudRate.BAUD_1M: "1M",
        }
        return baud_str_map.get(self, "500k")


@dataclass
class CANConfig:
    """CAN通道配置"""
    channel: int           # 通道号：1或2
    enabled: bool          # 是否启用
    baud_rate: BaudRate    # 波特率
    description: str       # 描述

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "channel": self.channel,
            "enabled": self.enabled,
            "baud_rate": self.baud_rate.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CANConfig':
        """从字典创建"""
        return cls(
            channel=data["channel"],
            enabled=data["enabled"],
            baud_rate=BaudRate(data["baud_rate"]),
            description=data["description"],
        )


@dataclass
class BMSAddressConfig:
    """BMS地址配置"""
    nbcmu_address: int     # NBCMU地址，默认0xA1 (161)
    sbcmu_address: int     # SBCMU地址，默认0xB1 (177)

    def __post_init__(self):
        """数据验证"""
        if not BMSAddressConstants.NBCMU_ADDRESS_MIN <= self.nbcmu_address <= BMSAddressConstants.NBCMU_ADDRESS_MAX:
            raise ValueError(f"NBCMU地址必须在0xA1-0xA5范围内: 0x{self.nbcmu_address:02X}")
        if not BMSAddressConstants.SBCMU_ADDRESS_MIN <= self.sbcmu_address <= BMSAddressConstants.SBCMU_ADDRESS_MAX:
            raise ValueError(f"SBCMU地址必须在0xB1-0xB5范围内: 0x{self.sbcmu_address:02X}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "nbcmu_address": self.nbcmu_address,
            "sbcmu_address": self.sbcmu_address,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BMSAddressConfig':
        """从字典创建"""
        return cls(
            nbcmu_address=data["nbcmu_address"],
            sbcmu_address=data["sbcmu_address"],
        )


@dataclass
class TimingConfig:
    """时序配置"""
    wait_after_send_sec: float      # 发送后等待时间，默认15秒
    clear_confirm_sec: float        # 清除确认时间，默认2秒
    domain_switch_sec: float        # 域切换等待时间，默认10秒
    frame_interval_ms: float        # 帧间隔，默认50ms
    repeat_interval_ms: float       # 重复发送间隔，默认200ms

    def __post_init__(self):
        """数据验证"""
        if self.wait_after_send_sec < 1:
            raise ValueError(f"发送后等待时间必须>=1秒: {self.wait_after_send_sec}")
        if self.clear_confirm_sec < 0.5:
            raise ValueError(f"清除确认时间必须>=0.5秒: {self.clear_confirm_sec}")
        if self.domain_switch_sec < 1:
            raise ValueError(f"域切换等待时间必须>=1秒: {self.domain_switch_sec}")
        if self.frame_interval_ms < 10:
            raise ValueError(f"帧间隔必须>=10ms: {self.frame_interval_ms}")
        if self.repeat_interval_ms < 50:
            raise ValueError(f"重复发送间隔必须>=50ms: {self.repeat_interval_ms}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "wait_after_send_sec": self.wait_after_send_sec,
            "clear_confirm_sec": self.clear_confirm_sec,
            "domain_switch_sec": self.domain_switch_sec,
            "frame_interval_ms": self.frame_interval_ms,
            "repeat_interval_ms": self.repeat_interval_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TimingConfig':
        """从字典创建"""
        return cls(
            wait_after_send_sec=data["wait_after_send_sec"],
            clear_confirm_sec=data["clear_confirm_sec"],
            domain_switch_sec=data["domain_switch_sec"],
            frame_interval_ms=data["frame_interval_ms"],
            repeat_interval_ms=data["repeat_interval_ms"],
        )


@dataclass
class PathConfig:
    """路径配置"""
    inner_dbc_path: str      # 内部DBC文件路径
    outer_dbc_path: str      # 外部DBC文件路径
    fault_excel_path: str    # 故障列表Excel路径
    pid_excel_path: str      # PID阈值表Excel路径
    log_directory: str       # 日志目录

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "inner_dbc_path": self.inner_dbc_path,
            "outer_dbc_path": self.outer_dbc_path,
            "fault_excel_path": self.fault_excel_path,
            "pid_excel_path": self.pid_excel_path,
            "log_directory": self.log_directory,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PathConfig':
        """从字典创建"""
        return cls(
            inner_dbc_path=data["inner_dbc_path"],
            outer_dbc_path=data["outer_dbc_path"],
            fault_excel_path=data["fault_excel_path"],
            pid_excel_path=data["pid_excel_path"],
            log_directory=data["log_directory"],
        )


class Settings:
    """全局设置管理器（纯Python版，无QObject依赖）"""

    def __init__(self, config_file: Optional[str] = None):
        project_root = Path(__file__).parent.parent
        self.config_file = config_file or str(project_root / "config" / "settings.json")
        self.config_path = Path(self.config_file)

        # 默认配置
        self._can_configs = {
            1: CANConfig(
                channel=1,
                enabled=True,
                baud_rate=BaudRate.BAUD_500K,
                description="通道0（CAN盒物理通道0）"
            ),
            2: CANConfig(
                channel=2,
                enabled=True,
                baud_rate=BaudRate.BAUD_250K,
                description="通道1（CAN盒物理通道1）"
            ),
        }

        self._bms_address = BMSAddressConfig(
            nbcmu_address=BMSAddressConstants.DEFAULT_NBCMU_ADDRESS,
            sbcmu_address=BMSAddressConstants.DEFAULT_SBCMU_ADDRESS,
        )

        self._timing = TimingConfig(
            wait_after_send_sec=15.0,
            clear_confirm_sec=2.0,
            domain_switch_sec=10.0,
            frame_interval_ms=50.0,
            repeat_interval_ms=200.0,
        )

        # 默认路径（相对于项目根目录）
        self._paths = PathConfig(
            inner_dbc_path=str(project_root / "resources" / "Ship_Two_5Cu12Pack_Matrix_Full_V1.91_20251207.dbc"),
            outer_dbc_path=str(project_root / "resources" / "对外通讯信号清单_二级架构5簇_CAN_V1.71(0806).dbc"),
            fault_excel_path=str(project_root / "resources" / "YTD-BMS-001 故障列表(CN-2)V1.0.xlsx"),
            pid_excel_path=str(project_root / "resources" / "DIC.BMS参数-原始.xlsx"),
            log_directory=str(project_root / "logs"),
        )

        # 其他设置
        self._auto_test_enabled = False
        self._auto_clear_faults = True
        self._max_clear_retries = 3
        self._test_timeout_sec = 30.0

        # 变更回调列表（UI层注册）
        self._change_callbacks = []

        # 加载保存的配置
        self.load()

    def on_config_changed(self, callback):
        """注册配置变更回调"""
        self._change_callbacks.append(callback)

    def _notify_changed(self):
        """通知所有回调"""
        for cb in self._change_callbacks:
            try:
                cb()
            except Exception:
                pass

    def _resolve_paths(self):
        """将路径配置中的相对路径解析为基于项目根目录的绝对路径"""
        project_root = Path(__file__).parent.parent
        path_fields = ['inner_dbc_path', 'outer_dbc_path', 'fault_excel_path',
                       'pid_excel_path', 'log_directory']
        for field in path_fields:
            val = getattr(self._paths, field)
            p = Path(val)
            if not p.is_absolute():
                setattr(self._paths, field, str(project_root / p))

    def load(self) -> bool:
        """从文件加载配置"""
        if not self.config_path.exists():
            logger.info(f"配置文件不存在，使用默认配置: {self.config_path}")
            return False

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 加载CAN配置
            if ConfigKeys.CHANNEL1_PARAMS in data or ConfigKeys.CHANNEL2_PARAMS in data:
                for chan_key in [ConfigKeys.CHANNEL1_PARAMS, ConfigKeys.CHANNEL2_PARAMS]:
                    if chan_key in data:
                        chan_data = data[chan_key]
                        chan = chan_data["channel"]
                        self._can_configs[chan] = CANConfig.from_dict(chan_data)

            # 加载BMS地址配置
            if ConfigKeys.NBCMU_ADDRESS in data or ConfigKeys.SBCMU_ADDRESS in data:
                self._bms_address = BMSAddressConfig.from_dict(data.get("bms_address", {}))

            # 加载时序配置
            if ConfigKeys.WAIT_AFTER_SEND_SEC in data:
                self._timing = TimingConfig.from_dict(data.get("timing", {}))

            # 加载路径配置
            if ConfigKeys.INTERNAL_DBC_PATH in data:
                self._paths = PathConfig.from_dict(data.get("paths", {}))
                # 将相对路径解析为基于项目根目录的绝对路径
                self._resolve_paths()

            # 加载其他设置
            if ConfigKeys.AUTO_TEST_ENABLED in data:
                self._auto_test_enabled = data[ConfigKeys.AUTO_TEST_ENABLED]
            if ConfigKeys.AUTO_CLEAR_FAULTS in data:
                self._auto_clear_faults = data[ConfigKeys.AUTO_CLEAR_FAULTS]
            if ConfigKeys.MAX_CLEAR_RETRIES in data:
                self._max_clear_retries = data[ConfigKeys.MAX_CLEAR_RETRIES]
            if ConfigKeys.TEST_TIMEOUT_SEC in data:
                self._test_timeout_sec = data[ConfigKeys.TEST_TIMEOUT_SEC]

            logger.info(f"从 {self.config_path} 加载配置成功")
            self._notify_changed()
            return True

        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return False

    def save(self) -> bool:
        """保存配置到文件"""
        try:
            # 确保配置目录存在
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "can_configs": [cfg.to_dict() for cfg in self._can_configs.values()],
                "bms_address": self._bms_address.to_dict(),
                "timing": self._timing.to_dict(),
                "paths": self._paths.to_dict(),
                ConfigKeys.AUTO_TEST_ENABLED: self._auto_test_enabled,
                ConfigKeys.AUTO_CLEAR_FAULTS: self._auto_clear_faults,
                ConfigKeys.MAX_CLEAR_RETRIES: self._max_clear_retries,
                ConfigKeys.TEST_TIMEOUT_SEC: self._test_timeout_sec,
            }

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"配置保存到 {self.config_path}")
            return True

        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False

    # CAN配置相关方法
    def get_can_config(self, channel: int) -> Optional[CANConfig]:
        """获取指定通道的CAN配置"""
        return self._can_configs.get(channel)

    def set_can_config(self, channel: int, config: CANConfig) -> bool:
        """设置CAN配置"""
        if channel not in (1, 2):
            logger.error(f"无效的CAN通道: {channel}")
            return False

        self._can_configs[channel] = config
        self._notify_changed()
        return True

    def set_can_baud_rate(self, channel: int, baud_rate: BaudRate) -> bool:
        """设置CAN波特率"""
        config = self.get_can_config(channel)
        if not config:
            return False

        config.baud_rate = baud_rate
        self._notify_changed()
        return True

    def set_can_enabled(self, channel: int, enabled: bool) -> bool:
        """设置CAN通道启用状态"""
        config = self.get_can_config(channel)
        if not config:
            return False

        config.enabled = enabled
        self._notify_changed()
        return True

    def get_all_can_configs(self) -> Dict[int, CANConfig]:
        """获取所有CAN配置"""
        return self._can_configs.copy()

    # BMS地址相关方法
    def get_bms_address_config(self) -> BMSAddressConfig:
        """获取BMS地址配置"""
        return self._bms_address

    def set_bms_address_config(self, config: BMSAddressConfig) -> None:
        """设置BMS地址配置"""
        self._bms_address = config
        self._notify_changed()

    def get_nbcmu_address(self) -> int:
        """获取NBCMU地址"""
        return self._bms_address.nbcmu_address

    def get_sbcmu_address(self) -> int:
        """获取SBCMU地址"""
        return self._bms_address.sbcmu_address

    def set_nbcmu_address(self, address: int) -> bool:
        """设置NBCMU地址"""
        if not BMSAddressConstants.NBCMU_ADDRESS_MIN <= address <= BMSAddressConstants.NBCMU_ADDRESS_MAX:
            logger.error(f"无效的NBCMU地址: 0x{address:02X}")
            return False

        self._bms_address.nbcmu_address = address
        self._notify_changed()
        return True

    def set_sbcmu_address(self, address: int) -> bool:
        """设置SBCMU地址"""
        if not BMSAddressConstants.SBCMU_ADDRESS_MIN <= address <= BMSAddressConstants.SBCMU_ADDRESS_MAX:
            logger.error(f"无效的SBCMU地址: 0x{address:02X}")
            return False

        self._bms_address.sbcmu_address = address
        self._notify_changed()
        return True

    # 时序配置相关方法
    def get_timing_config(self) -> TimingConfig:
        """获取时序配置"""
        return self._timing

    def set_timing_config(self, config: TimingConfig) -> None:
        """设置时序配置"""
        self._timing = config
        self._notify_changed()

    def get_wait_after_send_sec(self) -> float:
        """获取发送后等待时间"""
        return self._timing.wait_after_send_sec

    def get_clear_confirm_sec(self) -> float:
        """获取清除确认时间"""
        return self._timing.clear_confirm_sec

    def get_domain_switch_sec(self) -> float:
        """获取域切换等待时间"""
        return self._timing.domain_switch_sec

    def get_frame_interval_ms(self) -> float:
        """获取帧间隔"""
        return self._timing.frame_interval_ms

    def get_repeat_interval_ms(self) -> float:
        """获取重复发送间隔"""
        return self._timing.repeat_interval_ms

    # 路径配置相关方法
    def get_path_config(self) -> PathConfig:
        """获取路径配置"""
        return self._paths

    def set_path_config(self, config: PathConfig) -> None:
        """设置路径配置"""
        self._paths = config
        self._notify_changed()

    def get_inner_dbc_path(self) -> str:
        """获取内部DBC路径"""
        return self._paths.inner_dbc_path

    def get_outer_dbc_path(self) -> str:
        """获取外部DBC路径"""
        return self._paths.outer_dbc_path

    def get_fault_excel_path(self) -> str:
        """获取故障列表Excel路径"""
        return self._paths.fault_excel_path

    def get_pid_excel_path(self) -> str:
        """获取PID阈值表Excel路径"""
        return self._paths.pid_excel_path

    def get_log_directory(self) -> str:
        """获取日志目录"""
        return self._paths.log_directory

    # 其他设置相关方法
    def is_auto_test_enabled(self) -> bool:
        """是否启用自动测试"""
        return self._auto_test_enabled

    def set_auto_test_enabled(self, enabled: bool) -> None:
        """设置自动测试启用状态"""
        self._auto_test_enabled = enabled
        self._notify_changed()

    def is_auto_clear_faults(self) -> bool:
        """是否自动清除故障"""
        return self._auto_clear_faults

    def set_auto_clear_faults(self, enabled: bool) -> None:
        """设置自动清除故障"""
        self._auto_clear_faults = enabled
        self._notify_changed()

    def get_max_clear_retries(self) -> int:
        """获取最大清除重试次数"""
        return self._max_clear_retries

    def set_max_clear_retries(self, retries: int) -> None:
        """设置最大清除重试次数"""
        self._max_clear_retries = retries
        self._notify_changed()

    def get_test_timeout_sec(self) -> float:
        """获取测试超时时间"""
        return self._test_timeout_sec

    def set_test_timeout_sec(self, timeout: float) -> None:
        """设置测试超时时间"""
        self._test_timeout_sec = timeout
        self._notify_changed()

    # 工具方法
    def validate_paths(self) -> Dict[str, bool]:
        """验证所有路径是否存在"""
        results = {}

        paths_to_check = [
            ("inner_dbc", self._paths.inner_dbc_path),
            ("outer_dbc", self._paths.outer_dbc_path),
            ("fault_excel", self._paths.fault_excel_path),
            ("pid_excel", self._paths.pid_excel_path),
            ("log_directory", self._paths.log_directory),
        ]

        for name, path_str in paths_to_check:
            path = Path(path_str)
            if name == "log_directory":
                # 日志目录不存在时创建
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    results[name] = True
                except Exception:
                    results[name] = False
            else:
                results[name] = path.exists()

        return results

    def get(self, key: str, default: Any = None) -> Any:
        """
        兼容dict-style访问接口
        """
        key_map = {
            ConfigKeys.INTERNAL_DBC_PATH: lambda: self._paths.inner_dbc_path,
            ConfigKeys.EXTERNAL_DBC_PATH: lambda: self._paths.outer_dbc_path,
            ConfigKeys.FAULT_EXCEL_PATH: lambda: self._paths.fault_excel_path,
            ConfigKeys.PID_EXCEL_PATH: lambda: self._paths.pid_excel_path,
            ConfigKeys.LOG_DIRECTORY: lambda: self._paths.log_directory,
            ConfigKeys.CHANNEL1_PARAMS: lambda: self._can_configs[1].to_dict() if 1 in self._can_configs else {},
            ConfigKeys.CHANNEL2_PARAMS: lambda: self._can_configs[2].to_dict() if 2 in self._can_configs else {},
            ConfigKeys.NBCMU_ADDRESS: lambda: self._bms_address.nbcmu_address,
            ConfigKeys.SBCMU_ADDRESS: lambda: self._bms_address.sbcmu_address,
            ConfigKeys.WAIT_AFTER_SEND_SEC: lambda: self._timing.wait_after_send_sec,
            ConfigKeys.CLEAR_CONFIRM_SEC: lambda: self._timing.clear_confirm_sec,
            ConfigKeys.DOMAIN_SWITCH_SEC: lambda: self._timing.domain_switch_sec,
            ConfigKeys.FRAME_INTERVAL_MS: lambda: self._timing.frame_interval_ms,
            ConfigKeys.REPEAT_INTERVAL_MS: lambda: self._timing.repeat_interval_ms,
            ConfigKeys.AUTO_TEST_ENABLED: lambda: self._auto_test_enabled,
            ConfigKeys.AUTO_CLEAR_FAULTS: lambda: self._auto_clear_faults,
            ConfigKeys.MAX_CLEAR_RETRIES: lambda: self._max_clear_retries,
            ConfigKeys.TEST_TIMEOUT_SEC: lambda: self._test_timeout_sec,
        }

        if key in key_map:
            try:
                return key_map[key]()
            except Exception:
                return default

        return default

    def get_summary(self) -> Dict[str, Any]:
        """获取配置摘要"""
        return {
            "can_configs": {chan: cfg.to_dict() for chan, cfg in self._can_configs.items()},
            "bms_address": self._bms_address.to_dict(),
            "timing": self._timing.to_dict(),
            "paths": self._paths.to_dict(),
            "auto_test_enabled": self._auto_test_enabled,
            "auto_clear_faults": self._auto_clear_faults,
            "max_clear_retries": self._max_clear_retries,
            "test_timeout_sec": self._test_timeout_sec,
        }


# 全局设置实例
_global_settings: Optional[Settings] = None


def get_global_settings() -> Settings:
    """获取全局设置实例"""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings()
    return _global_settings


def set_global_settings(settings: Settings) -> None:
    """设置全局设置实例"""
    global _global_settings
    _global_settings = settings
