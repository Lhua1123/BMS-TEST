"""
双重验证器
执行对内3项验证（SysFailSta + ErrTab + specific）和对外2项验证（specific + Warning汇总）
移植自 报警测试/src/engine/verifier.py
"""

import logging
import time
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from enum import Enum

from bms_alarm_test.config.fault_mapping import Fault, FaultMapping, FaultDomain
from bms_alarm_test.models.test_result import TestResult, Check, CheckType, CheckStatus
from bms_alarm_test.can.can_listener import CANListener, CANChannel
from bms_alarm_test.can.can_manager import CANManager
from bms_alarm_test.config.constants import (
    VerificationConstants,
    TimingConstants,
    TestConstants,
    CANConstants,
)
from bms_alarm_test.utils.exceptions import ValidationError, CANError

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """验证错误"""
    pass


@dataclass
class VerificationConfig:
    """验证配置"""
    timeout_sec: float = TimingConstants.DEFAULT_VERIFICATION_TIMEOUT_SEC
    max_retries: int = VerificationConstants.MAX_RETRIES
    retry_delay_sec: float = VerificationConstants.RETRY_DELAY_SEC

    def __post_init__(self):
        """验证配置参数"""
        if self.timeout_sec <= 0:
            raise ValueError(f"超时时间必须大于0: {self.timeout_sec}")
        if self.max_retries <= 0:
            raise ValueError(f"最大重试次数必须大于0: {self.max_retries}")
        if self.retry_delay_sec <= 0:
            raise ValueError(f"重试延迟必须大于0: {self.retry_delay_sec}")


class BMSVerifier:
    """BMS双重验证器"""

    def __init__(self, can_manager: CANManager, fault_mapping: FaultMapping):
        self.can_manager = can_manager
        self.fault_mapping = fault_mapping
        self.config = VerificationConfig()

    def clear_signal_cache(self) -> None:
        """清除信号缓存"""
        try:
            self.can_manager.clear_signal_cache()
        except Exception as e:
            logger.warning(f"清除信号缓存失败: {e}")

    def verify_fault(self, fault: Fault, target_address: int, domain: str,
                     read_outer: bool = True) -> TestResult:
        """
        验证单个故障
        执行对内3项验证和对外2项验证
        read_outer=True 时读取对外通道报文做对外验证；
        read_outer=False 时跳过对外验证（对外无报文时不回读）
        """
        from datetime import datetime

        test_result = TestResult(
            test_id=f"fault_{fault.code}_{datetime.now().strftime('%H%M%S')}",
            test_type="fault",
            fault_name=fault.name,
            bms_address=target_address,
            domain_type=domain,
            metadata={"fault_code": str(fault.code)}
        )

        # 对内验证（配置的对内通道）
        inner_checks = self._verify_internal(fault, target_address, domain)
        test_result.checks.extend(inner_checks)

        # 对外验证（配置的对外通道）
        # 需读取对外报文时才执行；对外无报文时跳过，避免无谓等待超时
        if read_outer and not fault.is_skip_outer():
            outer_checks = self._verify_external(fault, target_address, domain)
            test_result.checks.extend(outer_checks)

        # 计算总体结果
        test_result.complete()
        return test_result

    def _verify_internal(self, fault: Fault, target_address: int, domain: str) -> List[Check]:
        """对内验证（配置的对内通道）"""
        checks = []

        # 1. SysFailSta验证
        sys_fail_sta_check = self._check_sys_fail_sta(fault, target_address, domain)
        checks.append(sys_fail_sta_check)

        # 2. ErrTab验证
        err_tab_check = self._check_err_tab(fault, target_address, domain)
        checks.append(err_tab_check)

        # 3. specific信号验证
        if fault.has_inner_specific():
            specific_check = self._check_inner_specific(fault, target_address, domain)
            checks.append(specific_check)

        # 4. 配置中的额外回读项（可在「故障期望值配置」里增删）
        checks.extend(self._check_extra_reads(fault, target_address, domain))

        return checks

    def _check_extra_reads(self, fault: Fault, target_address: int, domain: str) -> List[Check]:
        """执行故障上的 extra_checks（界面可编辑的额外回读信号+期望值）"""
        extra = getattr(fault, "extra_checks", None) or []
        if not extra:
            return []
        checks = []
        idx = self._get_dbc_index(target_address, domain)
        for i, item in enumerate(extra):
            name = item.get("name") or item.get("signal_name") or f"extra_{i+1}"
            expected = item.get("expected")
            signal_name = item.get("signal_name") or ""
            message_name = item.get("message_name") or ""
            role = item.get("channel_role") or "inner"
            readback_key = item.get("readback_key") or signal_name
            check = Check(
                name=f"额外回读: {name}",
                check_type=CheckType.INNER_SPECIFIC,
                expected_value=expected,
                description=item.get("comment") or f"自定义回读 {signal_name}"
            )
            check.start()
            try:
                channel = self._get_inner_channel() if role == "inner" else self._get_outer_channel()
                if signal_name and "{idx}" in signal_name:
                    signal_name = signal_name.replace("{idx}", str(idx))
                value = self._wait_for_signal(
                    channel,
                    message_name or None,
                    signal_name or readback_key,
                    expected,
                    self.config.timeout_sec,
                    readback_role=None,
                    readback_idx=idx,
                )
                # 也尝试按回读协议配置键解码
                if value is None and readback_key:
                    try:
                        value = self.can_manager.read_signal_via_readback(
                            channel, signal_name=readback_key, idx=idx
                        )
                    except Exception:
                        value = None
                if value is not None:
                    match_value = value.value if hasattr(value, "value") else value
                    if expected is None or self._match_signal_value(signal_name, match_value, expected):
                        check.pass_check(f"{name}={match_value}", actual_value=match_value)
                    else:
                        check.fail(f"期望值={expected}, 实际值={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={expected}, 实际值=None", actual_value=None)
            except Exception as e:
                check.error(f"额外回读异常: {e}")
            checks.append(check)
        return checks

    def _verify_external(self, fault: Fault, target_address: int, domain: str) -> List[Check]:
        """对外验证（从配置的对外通道读取，外DBC信号）"""
        checks = []

        # SBCMU 域：没有对外 SysFailSta 和对外 Warning 汇总，只查对外 specific
        if domain.upper() != "SBCMU":
            # 1. 对外SysFailSta：1组当前最大报警等级，读BMS_Msg01
            sys_fail_sta_check = self._check_outer_sys_fail_sta(fault, target_address, domain)
            checks.append(sys_fail_sta_check)

            # 2. 对外specific：信号在Msg15中（EMS_TimeOut/NBCMU_Warning等）
            if fault.outer_signal and fault.outer_expected is not None:
                specific_check = self._check_outer_specific(fault, target_address, domain)
                checks.append(specific_check)

            # 3. 对外Warning汇总：1簇1级报警，读BMS_Msg15
            if fault.outer_warning_expected is not None:
                warning_check = self._check_outer_warning(fault, target_address, domain)
                checks.append(warning_check)
        else:
            # SBCMU 域：只查对外 specific
            if fault.outer_signal and fault.outer_expected is not None:
                specific_check = self._check_outer_specific(fault, target_address, domain)
                checks.append(specific_check)

        return checks

    def _get_inner_channel(self) -> int:
        """对内通道（发送故障注入 / 读对内信号）"""
        try:
            settings = getattr(self.can_manager, 'settings', None)
            if settings:
                return settings.get_inner_channel()
        except Exception:
            pass
        return CANConstants.CHANNEL_1

    def _get_outer_channel(self) -> int:
        """对外通道（读 BMS 对外响应）"""
        try:
            settings = getattr(self.can_manager, 'settings', None)
            if settings:
                return settings.get_outer_channel()
        except Exception:
            pass
        return CANConstants.CHANNEL_2

    def _get_dbc_index(self, target_address: int, domain: str) -> str:
        """将目标地址转换为DBC报文名中的序号"""
        if domain.upper() == "NBCMU":
            idx = target_address - 0xA1 + 1
        else:
            idx = target_address - 0xB1 + 1
        return f"{idx:02d}"

    def _get_outer_message_id(self, base_name: str, target_address: int) -> int:
        """根据目标地址计算外DBC报文CAN ID（A1簇尾缀）"""
        base_ids = {
            "BMS_Msg01": 0x18A3F100,
            "BMS_Msg03": 0x18A5F100,
            "BMS_Msg15": 0x18B2F100,
            "BMS_Msg16": 0x18B3F100,
            "BMS_Msg17": 0x18B4F100,
        }
        base = base_ids.get(base_name)
        if base is None:
            return 0
        return base | (target_address & 0xFF)

    def _get_outer_message_name(self, can_id: int) -> Optional[str]:
        """从外DBC根据CAN ID获取报文名"""
        try:
            dbc_info = self.can_manager.dbc_loader.get_outer_dbc()
            if not dbc_info:
                return None
            for message in dbc_info.db.messages:
                if message.frame_id == can_id:
                    return message.name
        except Exception:
            pass
        return None

    def _get_signal_choices(self, signal_name: str, dbc_type: str = "inner") -> Optional[Dict]:
        """从DBC获取信号的枚举映射"""
        try:
            dbc_info = self.can_manager.dbc_loader.get_inner_dbc() if dbc_type == "inner" else self.can_manager.dbc_loader.get_outer_dbc()
            if not dbc_info:
                return None
            for msg in dbc_info.db.messages:
                for sig in msg.signals:
                    if sig.name == signal_name:
                        return sig.choices
        except Exception:
            pass
        return None

    def _find_inner_message_for_signal(self, signal_name: str) -> Optional[str]:
        """从内DBC查找信号所在的报文名"""
        try:
            dbc_info = self.can_manager.dbc_loader.get_inner_dbc()
            if not dbc_info:
                return None
            for msg in dbc_info.db.messages:
                for sig in msg.signals:
                    if sig.name == signal_name:
                        return msg.name
        except Exception:
            pass
        return None

    def _find_outer_message_for_signal(self, signal_name: str) -> Optional[str]:
        """从外DBC查找信号所在的报文名"""
        try:
            dbc_info = self.can_manager.dbc_loader.get_outer_dbc()
            if not dbc_info:
                return None
            for msg in dbc_info.db.messages:
                for sig in msg.signals:
                    if sig.name == signal_name:
                        return msg.name
        except Exception:
            pass
        return None

    def _match_signal_value(self, signal_name: str, actual_value: Any, expected: Any, dbc_type: str = "inner") -> bool:
        """匹配信号值（处理DBC枚举字符串与整数的比较）"""
        if actual_value is None:
            return False
        # cantools返回NamedSignalValue，提取其数值部分
        if hasattr(actual_value, 'value'):
            actual_value = actual_value.value
        if actual_value == expected:
            return True
        if isinstance(actual_value, str) and isinstance(expected, int):
            choices = self._get_signal_choices(signal_name, dbc_type)
            if choices:
                dbc_str = str(choices.get(expected, "")).strip()
                if dbc_str and dbc_str == actual_value.strip():
                    return True
        return False

    def _check_sys_fail_sta(self, fault: Fault, target_address: int, domain: str) -> Check:
        """检查SysFailSta信号"""
        check = Check(
            name=f"SysFailSta验证",
            check_type=CheckType.INNER_SYS_FAIL_STA,
            expected_value=fault.sys_fail_sta_expected,
            description=f"验证{fault.name}的SysFailSta信号"
        )
        check.start()

        try:
            idx = self._get_dbc_index(target_address, domain)
            if domain.upper() in ("NBCMU", "BOTH"):
                default_signal = f"NBCMU{idx}_SysFailSta"
                default_message = f"NBCMU{idx}_WarningInfo1"
            else:
                default_signal = f"SBCMU{idx}_SysFailSta"
                default_message = f"SBCMU{idx}_WarningInfo"

            # DBC 主读固定用默认具体信号名（NBCMU/SBCMU{idx}_SysFailSta）；
            # 回读配置里的通用 signal_name（如 BMS_SysFailSta）只作 _wait_for_signal 内的
            # CAN ID 兜底解码，不参与 DBC 名查询，否则缓存 key 对不上会永远读到 None
            value = self._wait_for_signal(
                self._get_inner_channel(), default_message, default_signal,
                fault.sys_fail_sta_expected, self.config.timeout_sec,
                readback_role="inner_sys_fail_sta", readback_idx=idx,
            )

            if value is not None:
                match_value = value.value if hasattr(value, 'value') else value
                if match_value == fault.sys_fail_sta_expected:
                    check.pass_check(f"SysFailSta={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={fault.sys_fail_sta_expected}, 实际值={match_value}", actual_value=match_value)
            else:
                check.fail(f"期望值={fault.sys_fail_sta_expected}, 实际值=None", actual_value=None)

        except Exception as e:
            check.error(f"验证异常: {e}")

        return check

    def _check_err_tab(self, fault: Fault, target_address: int, domain: str) -> Check:
        """检查ErrTab信号"""
        check = Check(
            name=f"ErrTab验证",
            check_type=CheckType.INNER_ERR_TAB,
            expected_value=fault.err_tab_expected,
            description=f"验证{fault.name}的ErrTab信号"
        )
        check.start()

        try:
            idx = self._get_dbc_index(target_address, domain)
            if domain.upper() in ("NBCMU", "BOTH"):
                signal_name = f"NBCMU{idx}_ErrTab"
                message_name = f"NBCMU{idx}_WarningInfo2"
            else:
                signal_name = f"SBCMU{idx}_ErrTab"
                message_name = f"SBCMU{idx}_WarningInfo"

            value = self._wait_for_signal(
                self._get_inner_channel(), message_name, signal_name,
                fault.err_tab_expected, self.config.timeout_sec
            )

            if value is not None:
                match_value = value.value if hasattr(value, 'value') else value
                if match_value == fault.err_tab_expected:
                    check.pass_check(f"ErrTab={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={fault.err_tab_expected}, 实际值={match_value}", actual_value=match_value)
            else:
                check.fail(f"期望值={fault.err_tab_expected}, 实际值=None", actual_value=None)

        except Exception as e:
            check.error(f"验证异常: {e}")

        return check

    def _check_inner_specific(self, fault: Fault, target_address: int, domain: str) -> Check:
        """检查内部specific信号"""
        check = Check(
            name=f"内部specific验证: {fault.inner_signal}",
            check_type=CheckType.INNER_SPECIFIC,
            expected_value=fault.inner_expected,
            description=f"验证{fault.name}的内部specific信号"
        )
        check.start()

        try:
            idx = self._get_dbc_index(target_address, domain)
            inner_signal = fault.inner_signal

            # SBCMU域：inner_signal 本来就是 SBCMU01_* 格式，直接查 DBC
            # DBC 中 SBCMU 信号在 SBCMU01_WarningInfo，不需要替换前缀

            # 优先按 DBC 查信号实际所在报文，不再按名字猜
            message_name = None
            if inner_signal:
                message_name = self._find_inner_message_for_signal(inner_signal)

            # DBC里找不到时，按旧规则兜底
            if not message_name:
                if inner_signal and ("SumVolt_HighWarning" in inner_signal or "SumVolt_LowWarning" in inner_signal):
                    message_name = f"NBCMU{idx}_WarningInfo3"
                elif inner_signal and ("SupplyVolt_HighWarning" in inner_signal or "SupplyVolt_LowWarning" in inner_signal):
                    message_name = f"NBCMU{idx}_WarningInfo2"
                elif inner_signal and "ChrgFault" in inner_signal:
                    message_name = f"NBCMU{idx}_WarningInfo3"
                elif inner_signal and ("Warning" in inner_signal or "Fault" in inner_signal):
                    message_name = f"NBCMU{idx}_WarningInfo1"
                else:
                    message_name = f"NBCMU{idx}_WarningInfo2"

            value = self._wait_for_signal(
                self._get_inner_channel(), message_name, inner_signal or "",
                fault.inner_expected, self.config.timeout_sec
            )

            if value is not None:
                match_value = value.value if hasattr(value, 'value') else value
                if match_value == fault.inner_expected:
                    check.pass_check(f"{fault.inner_signal}={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={fault.inner_expected}, 实际值={match_value}", actual_value=match_value)
            else:
                check.fail(f"期望值={fault.inner_expected}, 实际值=None", actual_value=None)

        except Exception as e:
            check.error(f"验证异常: {e}")

        return check

    def _check_outer_sys_fail_sta(self, fault: Fault, target_address: int, domain: str) -> Check:
        """检查对外SysFailSta（1组当前最大报警等级，读BMS_Msg01）"""
        check = Check(
            name=f"对外SysFailSta验证",
            check_type=CheckType.OUTER_SYS_FAIL_STA,
            expected_value=fault.sys_fail_sta_expected,
            description=f"验证{fault.name}的对外SysFailSta"
        )
        check.start()

        try:
            value = self._wait_for_signal(
                self._get_outer_channel(), "BMS_Msg01", "BMS_SysFailSta",
                fault.sys_fail_sta_expected, self.config.timeout_sec
            )

            if value is not None:
                match_value = value.value if hasattr(value, 'value') else value
                if match_value == fault.sys_fail_sta_expected:
                    check.pass_check(f"SysFailSta={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={fault.sys_fail_sta_expected}, 实际值={match_value}", actual_value=match_value)
            else:
                check.fail(f"期望值={fault.sys_fail_sta_expected}, 实际值=None", actual_value=None)

        except Exception as e:
            check.error(f"验证异常: {e}")

        return check

    def _check_outer_specific(self, fault: Fault, target_address: int, domain: str) -> Check:
        """检查外部specific信号（支持{idx}占位符动态匹配地址）"""
        check = Check(
            name=f"外部specific验证: {fault.outer_signal}",
            check_type=CheckType.OUTER_SPECIFIC,
            expected_value=fault.outer_expected,
            description=f"验证{fault.name}的外部specific信号"
        )
        check.start()

        try:
            signal_name = self._resolve_outer_signal_name(fault, target_address, domain)
            if not signal_name:
                check.fail(f"外DBC中未找到信号: {fault.outer_signal}")
                return check

            message_name = self._find_outer_message_for_signal(signal_name)
            if not message_name:
                check.fail(f"外DBC中未找到信号所在报文: {signal_name}")
                return check

            value = self._wait_for_signal(
                self._get_outer_channel(), message_name, signal_name,
                fault.outer_expected, self.config.timeout_sec
            )

            if value is not None:
                match_value = value.value if hasattr(value, 'value') else value
                if match_value == fault.outer_expected:
                    check.pass_check(f"{signal_name}={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={fault.outer_expected}, 实际值={match_value}", actual_value=match_value)
            else:
                check.fail(f"期望值={fault.outer_expected}, 实际值=None", actual_value=None)

        except Exception as e:
            check.error(f"验证异常: {e}")

        return check

    def _resolve_outer_signal_name(self, fault: Fault, target_address: int, domain: str) -> Optional[str]:
        """解析对外信号名，支持{idx}占位符替换为地址序号"""
        if not fault.outer_signal:
            return None
        if '{idx}' in fault.outer_signal:
            idx = self._get_dbc_index(target_address, domain)
            return fault.outer_signal.replace('{idx}', idx)
        return fault.outer_signal

    def _check_outer_warning(self, fault: Fault, target_address: int, domain: str) -> Check:
        """检查外部Warning汇总（1簇1级报警，读BMS_Msg15）"""
        check = Check(
            name=f"外部Warning汇总验证",
            check_type=CheckType.OUTER_WARNING,
            expected_value=fault.outer_warning_expected,
            description=f"验证{fault.name}的外部Warning汇总"
        )
        check.start()

        try:
            idx = self._get_dbc_index(target_address, domain)
            signal_name = f"BMS_NBCMU{idx}_Warning"

            value = self._wait_for_signal(
                self._get_outer_channel(), "BMS_Msg15", signal_name,
                None, self.config.timeout_sec
            )

            if value is not None:
                match_value = value.value if hasattr(value, 'value') else value
                if match_value == fault.outer_warning_expected:
                    check.pass_check(f"Warning={match_value}", actual_value=match_value)
                else:
                    check.fail(f"期望值={fault.outer_warning_expected}, 实际值={match_value}", actual_value=match_value)
            else:
                check.fail(f"期望值={fault.outer_warning_expected}, 实际值=None", actual_value=None)

        except Exception as e:
            check.error(f"验证异常: {e}")

        return check

    def _get_latest_frame_desc(self, channel: int) -> str:
        """取该通道最近一帧原始报文的描述（ID+数据），无则返回空串"""
        try:
            listener = getattr(self.can_manager, "_listener", None)
            if listener is None:
                return ""
            can_ch = CANChannel.CH1 if channel == 1 else CANChannel.CH2
            recent = listener.get_recent_messages(can_ch, 1)
            if not recent:
                return ""
            msg, _ts = recent[-1]
            data_hex = ' '.join(f'{b:02X}' for b in msg.data)
            return f"ID=0x{msg.arbitration_id:08X} 数据=[{data_hex}]"
        except Exception:
            return ""

    def _wait_for_signal(self, channel: int, message_name: Optional[str],
                         signal_name: str, expected_value: Any,
                         timeout: float,
                         readback_role: Optional[str] = None,
                         readback_idx: Optional[Union[int, str]] = None) -> Optional[Any]:
        """
        等待信号达到期望值。
        优先 DBC 名解码；失败时按「CAN 回读协议配置」用 CAN ID+位定义原始解码。
        """
        start_time = time.time()
        poll_count = 0
        while time.time() - start_time < timeout:
            if self.can_manager.is_stop_requested():
                logger.debug(f"[verifier] 停止请求，退出等待: {signal_name}")
                return None

            try:
                value = None
                if message_name:
                    value = self.can_manager.read_signal(channel, message_name, signal_name)
                if value is not None and hasattr(value, 'value'):
                    value = value.value
                if value is None:
                    try:
                        raw = self.can_manager.read_signal_via_readback(
                            channel,
                            signal_name=signal_name,
                            role=readback_role,
                            idx=readback_idx,
                        )
                        if raw is not None:
                            value = raw
                            if poll_count <= 1:
                                logger.info(
                                    f"[verifier] 回读配置解码: role={readback_role} "
                                    f"sig={signal_name} → {value}"
                                )
                    except Exception as rb_err:
                        logger.debug(f"回读配置解码失败: {rb_err}")
                poll_count += 1
                # DEBUG: 第1次轮询时 dump 整个 message 缓存
                if poll_count == 1 and message_name:
                    can_ch = CANChannel.CH1 if channel == 1 else CANChannel.CH2
                    listener = getattr(self.can_manager, "_listener", None)
                    all_vals = listener.get_message_values(can_ch, message_name) if listener else {}
                    logger.info(f"[verifier] 首次轮询缓存 dump: {message_name} 所有信号={all_vals}")
                # 回读到的报文：在第1次/每40次/匹配成功时记录原始帧（避免刷屏）
                if poll_count == 1 or poll_count % 40 == 0:
                    logger.info(f"[verifier] 轮询 {signal_name} (msg={message_name} ch={channel}): "
                                f"第{poll_count}次, 值={value}, 期望={expected_value}")
                    frame_desc = self._get_latest_frame_desc(channel)
                    if frame_desc:
                        logger.info(f"[回读报文] CH{channel} {message_name}.{signal_name}={value} {frame_desc}")
                if value is not None:
                    if expected_value is None or self._match_signal_value(signal_name, value, expected_value):
                        logger.info(f"[verifier] 信号匹配成功: {signal_name}={value} "
                                    f"(期望={expected_value}, 轮询{poll_count}次)")
                        frame_desc = self._get_latest_frame_desc(channel)
                        if frame_desc:
                            logger.info(f"[回读报文] CH{channel} {message_name}.{signal_name}={value} {frame_desc}")
                        return value
            except Exception as e:
                logger.debug(f"读取信号异常: {e}")

            time.sleep(0.05)

        logger.warning(f"[verifier] 超时: {signal_name} (msg={message_name} ch={channel}) "
                       f"期望={expected_value}, 轮询{poll_count}次")
        return None
