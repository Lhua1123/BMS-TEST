"""
阈值测试引擎
触发路径与故障码测试不同（DAPP_ThresholdSet 越限），回读验证与故障码测试共用 BMSVerifier。
"""

import logging
import time
import threading
from typing import List, Optional, Dict, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from bms_alarm_test.config.pid_table import PIDTable, PIDConfig, ThresholdType
from bms_alarm_test.models.test_result import TestResult, Check, CheckType, CheckStatus
from bms_alarm_test.can.can_manager import CANManager
from bms_alarm_test.can.can_listener import CANChannel
from bms_alarm_test.config.constants import (
    TestConstants,
    TimingConstants,
    CANConstants,
)
from bms_alarm_test.config.fault_mapping import FaultMapping, FaultDomain
from bms_alarm_test.engine.verifier import BMSVerifier
from bms_alarm_test.utils.exceptions import TestExecutionError, CANError

logger = logging.getLogger(__name__)

# HEX17 字段：每级 触发2字节 + 解除2字节 + 充放等级1字节
# [0]=使能 [1]=成熟 [2:7]=三级 [7:12]=二级 [12:17]=一级
_FIELD_TRIG = {3: 2, 2: 7, 1: 12}
_FIELD_REL = {3: 4, 2: 9, 1: 14}
_FIELD_LEVEL = {3: 6, 2: 11, 1: 16}

# 默认测试偏移系数（相对环境实际值的物理量）
DEFAULT_OFFSET = 1.0

# 环境值信号映射关键字 → (报文模板, 信号名, 通道)
# 报文中 {idx} 为 DBC 簇序号


class ThresholdTestState(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    READING_ENV = "reading_env"
    SETTING = "setting"
    VERIFYING = "verifying"
    RELEASING = "releasing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ThresholdTestProgress:
    current_index: int = 0
    total: int = 0
    current_state: ThresholdTestState = ThresholdTestState.IDLE
    current_pid: Optional[str] = None
    current_level: Optional[int] = None
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    start_time: float = 0.0
    elapsed_time: float = 0.0


@dataclass
class PIDLevelEntry:
    """单个 PID 等级条目"""
    pid: PIDConfig
    level: int
    target_address: int = TestConstants.DEFAULT_BMS_ADDRESS
    domain: str = TestConstants.DEFAULT_DOMAIN

    @property
    def pid_code(self) -> str:
        return f"0x{self.pid.pid:04X}"

    @property
    def code(self) -> str:
        return f"{self.pid_code}:{self.level}"


class ThresholdTestEngine:
    """阈值测试引擎：阈值越限触发 + 与故障码测试相同的回读验证"""

    def __init__(self, can_manager: CANManager, pid_table: PIDTable, fault_mapping: FaultMapping):
        self.can_manager = can_manager
        self.pid_table = pid_table
        self.fault_mapping = fault_mapping
        self.verifier = BMSVerifier(can_manager, fault_mapping)

        self.is_running = False
        self.stop_requested = False
        self._current_thread: Optional[threading.Thread] = None
        self.progress = ThresholdTestProgress()

        self.on_progress_update: Optional[Callable[[ThresholdTestProgress], None]] = None
        self.on_test_result: Optional[Callable[[TestResult], None]] = None
        self.on_test_complete: Optional[Callable[[List[TestResult]], None]] = None

        self._test_type = "both"
        self._offset_value = DEFAULT_OFFSET
        self._alarm_wait_time_sec = 5.0
        self._target_address = TestConstants.DEFAULT_BMS_ADDRESS
        self._domain = TestConstants.DEFAULT_DOMAIN
        self._results: List[TestResult] = []

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def set_callbacks(self, on_progress_update=None, on_test_result=None, on_test_complete=None):
        self.on_progress_update = on_progress_update
        self.on_test_result = on_test_result
        self.on_test_complete = on_test_complete

    def start_test(self, pid_codes: Optional[List[str]] = None,
                   target_address: int = TestConstants.DEFAULT_BMS_ADDRESS,
                   domain: str = TestConstants.DEFAULT_DOMAIN,
                   test_type: str = "both",
                   offset_value: float = DEFAULT_OFFSET,
                   alarm_wait_time_sec: float = 5.0) -> bool:
        if self.is_running:
            logger.warning("阈值测试引擎已在运行中")
            return False
        if not self.can_manager or not self.can_manager.is_connected():
            logger.error("CAN 未连接，无法开始阈值测试")
            return False
        if not self.pid_table or not self.pid_table.is_loaded():
            logger.error("PID 表未加载")
            return False

        entries = self._resolve_level_entries(pid_codes, target_address, domain)
        if not entries:
            logger.error("没有找到要测试的PID等级")
            return False

        self._test_type = test_type or "both"
        self._offset_value = offset_value if offset_value and offset_value > 0 else DEFAULT_OFFSET
        self._alarm_wait_time_sec = alarm_wait_time_sec or 5.0
        self._target_address = target_address
        self._domain = domain
        entries = self._filter_by_test_type(entries)
        if not entries:
            logger.error("按测试类型过滤后没有可测 PID")
            return False

        self.stop_requested = False
        self.is_running = True
        self._results = []
        self.progress = ThresholdTestProgress(
            total=len(entries),
            current_state=ThresholdTestState.PREPARING,
            start_time=time.time(),
        )
        self._pending_level_total = len(entries)
        self._current_thread = threading.Thread(
            target=self._run_test_sequence,
            args=(entries,),
            name="ThresholdTestEngine",
            daemon=True,
        )
        self._current_thread.start()
        return True

    def run_single_pid(self, pid_code: str,
                       target_address: int = TestConstants.DEFAULT_BMS_ADDRESS,
                       domain: str = TestConstants.DEFAULT_DOMAIN,
                       test_type: str = "both",
                       offset_value: float = DEFAULT_OFFSET,
                       alarm_wait_time_sec: float = 5.0) -> Optional[TestResult]:
        if not self.can_manager or not self.can_manager.is_connected():
            logger.error("CAN 未连接，无法单步测试")
            return None
        entries = self._resolve_level_entries([pid_code], target_address, domain)
        if not entries:
            logger.error(f"PID 解析失败: {pid_code}")
            return None

        old = (self._test_type, self._offset_value, self._alarm_wait_time_sec)
        self._test_type = test_type or "both"
        self._offset_value = offset_value if offset_value and offset_value > 0 else DEFAULT_OFFSET
        self._alarm_wait_time_sec = alarm_wait_time_sec or 5.0
        entries = self._filter_by_test_type(entries)
        try:
            return self._test_pid_levels(entries[0].pid, entries, target_address, domain)
        finally:
            self._test_type, self._offset_value, self._alarm_wait_time_sec = old

    def stop_test(self):
        self.stop_requested = True
        logger.info("阈值测试停止请求已发送")

    def wait_for_completion(self, timeout_sec: float = 600.0) -> bool:
        t = self._current_thread
        if not t:
            return True
        t.join(timeout=timeout_sec)
        return not t.is_alive()

    def get_progress(self) -> ThresholdTestProgress:
        self.progress.elapsed_time = time.time() - self.progress.start_time if self.progress.start_time else 0
        return self.progress

    def get_test_summary(self) -> Dict[str, Any]:
        p = self.progress
        return {
            "total": p.total,
            "passed": p.passed_count,
            "failed": p.failed_count,
            "skipped": p.skipped_count,
        }

    def reset(self):
        self.stop_requested = True
        self.is_running = False
        self.progress = ThresholdTestProgress()
        self._results = []

    # ------------------------------------------------------------------
    # PID 解析 / 过滤
    # ------------------------------------------------------------------
    def _resolve_level_entries(self, pid_codes: Optional[List[str]],
                               target_address: int, domain: str) -> List[PIDLevelEntry]:
        entries: List[PIDLevelEntry] = []
        if not pid_codes:
            for pid in self.pid_table.get_all_pids():
                for lv in pid.get_supported_levels():
                    entries.append(PIDLevelEntry(pid, lv, target_address, domain))
            return entries

        for code in pid_codes:
            code = (code or "").strip()
            if not code:
                continue
            if ":" in code:
                pair = self.pid_table.get_pid_by_level_code(code)
                if pair:
                    pid, lv = pair
                    entries.append(PIDLevelEntry(pid, lv, target_address, domain))
                else:
                    logger.warning(f"PID 等级代码解析失败: {code}")
            else:
                pid = self.pid_table.get_pid_by_code(code)
                if not pid:
                    logger.warning(f"PID 解析失败: {code}")
                    continue
                for lv in pid.get_supported_levels():
                    entries.append(PIDLevelEntry(pid, lv, target_address, domain))
        return entries

    @staticmethod
    def _infer_pid_direction(pid: PIDConfig) -> str:
        """过高类返回 upper（阈值设低于实际）；过低类返回 lower"""
        name = (pid.alarm_category or "").lower()
        lower_keywords = ("过低", "偏低", "不足", "过小", "欠压", "soc过低", "soh过低")
        upper_keywords = ("过高", "过大", "偏高", "超限", "过温", "超温")
        for kw in lower_keywords:
            if kw in name:
                return "lower"
        for kw in upper_keywords:
            if kw in name:
                return "upper"
        # 阈值单调性兜底：阈值递增→过高类；递减→过低类
        t1 = pid.level1_threshold
        t3 = pid.level3_threshold
        if t1 is not None and t3 is not None:
            return "upper" if t1 <= t3 else "lower"
        return "upper"

    def _filter_by_test_type(self, entries: List[PIDLevelEntry]) -> List[PIDLevelEntry]:
        t = (self._test_type or "both").lower()
        if t in ("both", "上下限", "上下限测试"):
            return entries
        result = []
        for e in entries:
            d = self._infer_pid_direction(e.pid)
            if t in ("upper", "上限", "上限测试") and d == "upper":
                result.append(e)
            elif t in ("lower", "下限", "下限测试") and d == "lower":
                result.append(e)
        return result

    def _get_dbc_idx(self, target_address: int, domain: str) -> str:
        if (domain or "NBCMU").upper() == "NBCMU":
            idx = int(target_address) - 0xA1 + 1
        else:
            idx = int(target_address) - 0xB1 + 1
        return f"{max(1, idx):02d}"

    # ------------------------------------------------------------------
    # 环境实际值
    # ------------------------------------------------------------------
    def _env_signal_spec(self, pid: PIDConfig, domain: str, target_address: int) -> Optional[Tuple[str, str, int, str]]:
        """返回 (message_name, signal_name, channel, dbc_type)"""
        name = pid.alarm_category or ""
        idx = self._get_dbc_idx(target_address, domain)
        outer_ch = 2
        inner_ch = 1
        try:
            if self.can_manager and self.can_manager.settings:
                inner_ch = self.can_manager.settings.get_inner_channel()
                outer_ch = self.can_manager.settings.get_outer_channel()
        except Exception:
            pass

        def inn(msg, sig):
            return (msg, sig, inner_ch, "inner")

        def out(msg, sig):
            return (msg, sig, outer_ch, "outer")

        if "充电插座" in name:
            sig = "SBCMU01_TempMax_ChargeSocket_Nega" if ("负" in name or "Nega" in name) else "SBCMU01_TempMax_ChargeSocket_Posi"
            sbc_idx = idx if (domain or "").upper() == "SBCMU" else "01"
            return inn(f"SBCMU{sbc_idx}_DCChrgState", sig)
        if "温差" in name:
            return out("BMS_Msg03", "BMS_TempDiff")
        if "压差" in name:
            return out("BMS_Msg05", "BMS_CellVoltDiff")
        if "模块总压" in name:
            return inn(f"NBICU{idx}_VoltExtremeInfo", f"NBICU{idx}_CellSumVolt")
        if "簇总压" in name:
            return inn(f"NBCMU{idx}_SysHVoltage", f"NBCMU{idx}_SysHVoltage")
        if "SOC" in name.upper():
            return inn(f"NBCMU{idx}_SysSOX", f"NBCMU{idx}_SysSOC_Dis")
        if "SOH" in name.upper():
            return inn(f"NBCMU{idx}_SysSOX", f"NBCMU{idx}_SysSOH_Cal")
        if "供电" in name:
            return inn(f"NBICU{idx}_TempExtremeInfo", f"NBICU{idx}_SupplyVolt")
        if "环境温度" in name:
            return inn(f"NBCMU{idx}_TempExtremeInfo", f"NBCMU{idx}_AmbientTemp")
        if "S板" in name and "环境" in name:
            return inn(f"NBCMU{idx}_TempExtremeInfo", f"NBCMU{idx}_AmbientTemp")
        if "温度" in name or "过温" in name or "过高温" in name or "S板" in name:
            direction = self._infer_pid_direction(pid)
            sig = f"NBICU{idx}_CellTempMax" if direction == "upper" else f"NBICU{idx}_CellTempMin"
            return inn(f"NBICU{idx}_TempExtremeInfo", sig)
        if "电压" in name:
            direction = self._infer_pid_direction(pid)
            sig = f"NBCMU{idx}_SysCellVoltMax" if direction == "upper" else f"NBCMU{idx}_SysCellVoltMin"
            return inn(f"NBCMU{idx}_VoltExtremeInfo", sig)
        return None

    def _ensure_env_messages_monitored(self, specs: List[Tuple[str, str, int, str]]):
        """把环境值报文 ID 动态加入监听白名单，否则帧会被丢弃"""
        try:
            listener = getattr(self.can_manager, "_listener", None)
            if not listener:
                return
            from bms_alarm_test.can.can_listener import CANChannel
            for msg, _sig, ch, dbc_type in specs:
                can_id = None
                try:
                    dbc_msg = self.can_manager.dbc_loader.get_message(dbc_type, msg)
                    if dbc_msg is not None:
                        can_id = dbc_msg.frame_id
                except Exception:
                    can_id = None
                if can_id is None:
                    continue
                try:
                    can_channel = CANChannel.CH1 if int(ch) == 1 else CANChannel.CH2
                    listener.add_monitored_message(can_channel, can_id)
                    logger.debug(f"[监控扩展] {msg} ID=0x{can_id:X} -> CH{ch}")
                except Exception as e:
                    logger.warning(f"添加监控报文失败 {msg}: {e}")
        except Exception as e:
            logger.warning(f"扩展环境报文监控失败: {e}")

    def _read_environment_value(self, pid: PIDConfig, domain: str, target_address: int) -> Optional[float]:
        spec = self._env_signal_spec(pid, domain, target_address)
        if not spec:
            logger.warning(f"PID 0x{pid.pid:04X} {pid.alarm_category} 无环境实际值信号，暂不支持动态阈值测试")
            return None
        msg, sig, ch, dbc_type = spec
        self._ensure_env_messages_monitored([spec])
        try:
            self.can_manager.clear_signal_cache()
        except Exception:
            pass

        def _read_signal(message_name: str, signal_name: str, channel: int) -> Optional[float]:
            for _ in range(6):
                if self.stop_requested:
                    return None
                value = self.can_manager.read_signal(channel, message_name, signal_name)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        return None
                time.sleep(0.25)
            return None

        value = _read_signal(msg, sig, ch)
        if value is None:
            other = 2 if int(ch) == 1 else 1
            value = _read_signal(msg, sig, other)
        if value is None:
            logger.warning(
                f"[环境值] PID 0x{pid.pid:04X} {pid.alarm_category}: "
                f"读取 {msg}.{sig} (CH{ch}/{dbc_type}) 失败"
            )
            return None
        logger.info(f"[环境值] {pid.alarm_category}: {msg}.{sig}={value}")
        return value

    # ------------------------------------------------------------------
    # 阈值计算 / 编码
    # ------------------------------------------------------------------
    def _calc_level_value(self, pid: PIDConfig, env_value: float, level: int) -> float:
        direction = self._infer_pid_direction(pid)
        factor = {1: 3.0, 2: 2.0, 3: 1.0}.get(level, 1.0)
        off = self._offset_value * factor
        if direction == "upper":
            return env_value - off
        return env_value + off

    def _calc_release_value(self, pid: PIDConfig, env_value: float) -> float:
        direction = self._infer_pid_direction(pid)
        off = self._offset_value * 3.0
        if direction == "upper":
            return env_value + off
        return env_value - off

    def _encode_raw_value(self, pid: PIDConfig, phys_value: float) -> int:
        """物理值 → 报文原始值，与 PIDConfig.get_raw_threshold 同规则"""
        t = pid.threshold_type
        if t == ThresholdType.CURRENT:
            return int(phys_value * 10 + 30000)
        if t == ThresholdType.TEMPERATURE:
            return int(phys_value + 40)
        if t == ThresholdType.PERCENTAGE:
            return int(phys_value * 100)
        if t == ThresholdType.VOLTAGE:
            # 参数表电压类多为 0.1V 精度时 Excel 已是原始物理量（mV 或 V*10）
            if pid.unit and "mV" in pid.unit:
                return int(phys_value)
            return int(round(phys_value / (pid.precision or 0.1)))
        if pid.precision and pid.precision != 1:
            return int(round(phys_value / pid.precision))
        return int(phys_value)

    def _get_threshold_hex17(self, pid: PIDConfig) -> Optional[List[int]]:
        hx = getattr(pid, "threshold_hex", None)
        if not hx or len(hx) < 17:
            return None
        return list(hx[:17])

    @staticmethod
    def _encode_threshold_pair(buf: bytearray, idx: int, raw_value: int):
        raw_value = max(0, min(0xFFFF, int(raw_value)))
        buf[idx] = (raw_value >> 8) & 0xFF
        buf[idx + 1] = raw_value & 0xFF

    def _build_threshold_set_data(self, pid: PIDConfig, number: int, data4: bytes,
                                  target_address: int, mode: int = 0) -> Optional[bytes]:
        if len(data4) < 4:
            data4 = bytes(list(data4) + [0] * (4 - len(data4)))
        signals = {
            "DAPP_Threshold_Addr_Target": int(target_address) & 0xFF,
            "DAPP_Threshold_PID": int(pid.pid) & 0xFFFF,
            "DAPP_Threshold_Number": int(number) & 0x0F,
            "DAPP_Threshold_Mode": 1 if mode else 0,
            "DAPP_Threshold_Data1": data4[0],
            "DAPP_Threshold_Data2": data4[1],
            "DAPP_Threshold_Data3": data4[2],
            "DAPP_Threshold_Data4": data4[3],
        }
        try:
            encoded = self.can_manager.dbc_loader.encode_message("inner", "DAPP_ThresholdSet", signals)
            if not encoded:
                logger.error(f"DAPP_ThresholdSet 编码失败: PID={pid.pid:#06x} number={number}")
                return None
            return encoded[1]
        except Exception as e:
            logger.error(f"构建阈值设置报文异常: {e}")
            return None

    def _get_inner_channel(self) -> int:
        try:
            if self.can_manager and self.can_manager.settings:
                return self.can_manager.settings.get_inner_channel()
        except Exception:
            pass
        return CANConstants.CHANNEL_1

    def _send_hex_as_5frames(self, pid: PIDConfig, hex17: List[int],
                             target_address: int, mode: int = 0) -> Tuple[bool, Check]:
        check = Check(
            name=f"阈值设置 {pid.pid_code if False else hex(pid.pid)}",
            check_type=CheckType.THRESHOLD_SET,
            description="下发 DAPP_ThresholdSet 5帧",
            expected_value=f"PID=0x{pid.pid:04X} mode={mode}",
        )
        check.start()
        frames: List[bytes] = []
        raw = list(hex17[:17]) + [0] * 3
        for n in range(5):
            chunk = bytes(raw[n * 4:(n + 1) * 4])
            data = self._build_threshold_set_data(pid, n + 1, chunk, target_address, mode=mode)
            if data is None:
                check.fail("阈值设置报文编码失败")
                return False, check
            frames.append(data)

        ch = self._get_inner_channel()
        msg_id = CANConstants.DAPP_THRESHOLDSET_MSG_ID

        def _send_round(tag: str) -> bool:
            for i, data in enumerate(frames):
                if self.stop_requested:
                    return False
                ok = self.can_manager.send_message(
                    channel=ch,
                    can_id=msg_id,
                    data=data,
                    is_extended_id=True,
                )
                hex_str = " ".join(f"{b:02X}" for b in data)
                if ok:
                    logger.info(f"[阈值设置] PID=0x{pid.pid:04X} Number={i+1} [{tag}] ID=0x{msg_id:X} 数据=[{hex_str}]")
                else:
                    logger.error(f"阈值设置报文发送失败({tag}第{i+1}帧): PID=0x{pid.pid:04X}")
                    return False
                time.sleep(TimingConstants.FAULT_INJECTION_FRAME_INTERVAL_MS / 1000.0)
            return True

        try:
            if not _send_round("第1遍"):
                check.fail("第1遍阈值帧发送失败")
                return False, check
            time.sleep(TimingConstants.FAULT_INJECTION_REPEAT_INTERVAL_MS / 1000.0)
            if not _send_round("第2遍"):
                check.fail("第2遍阈值帧发送失败")
                return False, check
        except CANError as e:
            check.error(f"CAN错误: {e}")
            return False, check
        except Exception as e:
            check.error(f"设置阈值异常: {e}")
            return False, check

        check.pass_check("阈值5帧发送完成")
        return True, check

    def _set_thresholds_for_level(self, pid: PIDConfig, level: int, env_value: float,
                                  target_address: int) -> Tuple[bool, Check]:
        hex17 = self._get_threshold_hex17(pid)
        if not hex17:
            check = Check(
                name=f"阈值设置 L{level}",
                check_type=CheckType.THRESHOLD_SET,
                description="缺少 HEX17",
                expected_value="参数表 HEX 列 17 字节",
            )
            check.start()
            check.fail(f"PID 0x{pid.pid:04X} 缺少HEX17阈值数据，无法设置")
            return False, check

        buf = bytearray(hex17)
        test_val = self._calc_level_value(pid, env_value, level)
        rel_val = self._calc_release_value(pid, env_value)
        try:
            raw_trig = self._encode_raw_value(pid, test_val)
            raw_rel = self._encode_raw_value(pid, rel_val)
        except Exception as e:
            check = Check(
                name=f"阈值设置 L{level}",
                check_type=CheckType.THRESHOLD_SET,
                description="编码原始值失败",
            )
            check.start()
            check.error(str(e))
            return False, check

        self._encode_threshold_pair(buf, _FIELD_TRIG[level], raw_trig)
        self._encode_threshold_pair(buf, _FIELD_REL[level], raw_rel)

        check_meta = (
            f"level={level} env={env_value} test={test_val} release={rel_val} "
            f"raw_trig={raw_trig:#06x} raw_rel={raw_rel:#06x}"
        )
        ok, check = self._send_hex_as_5frames(pid, list(buf), target_address, mode=0)
        check.check_type = CheckType.THRESHOLD_SET
        check.name = f"阈值设置 L{level}"
        check.description = check_meta
        check.expected_value = check_meta
        return ok, check

    def _release_all_thresholds(self, pid: PIDConfig, env_value: Optional[float],
                                target_address: int) -> Tuple[bool, Check]:
        check = Check(
            name="阈值恢复",
            check_type=CheckType.THRESHOLD_RESTORE,
            description="恢复/解除阈值",
        )
        check.start()
        hex17 = self._get_threshold_hex17(pid)
        if not hex17:
            check.fail("缺少 HEX17，无法恢复")
            return False, check
        if env_value is None:
            # 退回参数表原始值
            ok, send_check = self._send_hex_as_5frames(pid, hex17, target_address, mode=0)
            check.actual_value = send_check.message
            if ok:
                check.pass_check("已按参数表原值恢复")
            else:
                check.fail(send_check.message or "按原值恢复失败")
            return ok, check

        buf = bytearray(hex17)
        rel = self._calc_release_value(pid, env_value)
        try:
            raw_rel = self._encode_raw_value(pid, rel)
        except Exception as e:
            check.error(str(e))
            return False, check
        for lv in pid.get_supported_levels():
            self._encode_threshold_pair(buf, _FIELD_REL[lv], raw_rel)
            # 解除测试：把触发值也设为不触发方向
            direction = self._infer_pid_direction(pid)
            safe = env_value + self._offset_value * 3 if direction == "upper" else env_value - self._offset_value * 3
            self._encode_threshold_pair(buf, _FIELD_TRIG[lv], self._encode_raw_value(pid, safe))
        ok, send_check = self._send_hex_as_5frames(pid, list(buf), target_address, mode=0)
        if ok:
            check.pass_check(f"解除值={rel}")
        else:
            check.fail(send_check.message or "解除发送失败")
        return ok, check

    # ------------------------------------------------------------------
    # 故障码映射 + 与故障码测试相同的验证
    # ------------------------------------------------------------------
    @staticmethod
    def _get_fault_code_for_level(pid: PIDConfig, level: int) -> Optional[int]:
        codes = pid.fault_codes or []
        if not codes:
            return None
        # 与 1/2/3 级对齐的列表（0/None 表示该级无码）
        if 1 <= level <= len(codes):
            val = codes[level - 1]
            if val not in (None, 0, ""):
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
            # 对齐列表中该级为空
            if len(codes) >= 3 or level <= pid.alarm_enable:
                # 仍尝试：仅当该 PID 只有一个非零码时共用
                pass
        positive = []
        for item in codes:
            try:
                c = int(item)
            except (TypeError, ValueError):
                continue
            if c > 0:
                positive.append(c)
        if not positive:
            return None
        if len(positive) == 1:
            return positive[0]
        if 1 <= level <= len(positive):
            return positive[level - 1]
        return None

    def _get_fault_for_level(self, pid: PIDConfig, level: int):
        code = self._get_fault_code_for_level(pid, level)
        if code is None:
            return None
        faults = self.fault_mapping.get_faults_by_codes([str(code)]) if hasattr(self.fault_mapping, "get_faults_by_codes") else []
        if not faults:
            try:
                faults = self.fault_mapping.get_faults_by_codes([code])
            except Exception:
                faults = []
        return faults[0] if faults else None

    def _verify_level(self, pid: PIDConfig, level: int, target_address: int, domain: str) -> TestResult:
        """与故障码测试一致：调用 BMSVerifier.verify_fault"""
        fault = self._get_fault_for_level(pid, level)
        fault_code = self._get_fault_code_for_level(pid, level)
        pid_label = f"0x{pid.pid:04X}:{level}"
        if fault is None:
            result = TestResult(
                test_id=f"threshold_{pid_label}_{datetime.now().strftime('%H%M%S')}",
                test_type="threshold",
                fault_name=f"{pid.alarm_category} L{level}",
                pid_name=pid_label,
                bms_address=target_address,
                domain_type=domain,
                metadata={"pid": hex(pid.pid), "level": str(level), "fault_code": str(fault_code)},
            )
            result.start()
            check = Check(
                name="阈值验证",
                check_type=CheckType.THRESHOLD_VERIFICATION,
                description="PID 等级未映射到故障码，无法回读",
                expected_value=str(fault_code),
            )
            check.start()
            check.fail(f"无故障码映射: PID=0x{pid.pid:04X} L{level}")
            result.add_check(check)
            result.fail("无故障码映射")
            return result

        verify_result = self.verifier.verify_fault(
            fault, target_address, domain,
            read_outer=getattr(self, "read_outer_messages", True),
        )
        verify_result.test_type = "threshold"
        verify_result.pid_name = pid_label
        verify_result.fault_name = f"{pid.alarm_category} L{level}"
        verify_result.metadata = {
            **(verify_result.metadata or {}),
            "pid": hex(pid.pid),
            "level": str(level),
            "fault_code": str(fault.code),
        }
        return verify_result

    # ------------------------------------------------------------------
    # 手动设置/清除（列表操作列）
    # ------------------------------------------------------------------
    def set_fault_by_threshold(self, pid_code: str, level: Optional[int],
                               target_address: int, domain: str,
                               offset_value: float = DEFAULT_OFFSET) -> Optional[TestResult]:
        entries = self._resolve_level_entries(
            [pid_code if level is None else f"{pid_code}:{level}"],
            target_address, domain,
        )
        if not entries:
            logger.error(f"[手动设置故障] PID 解析失败: {pid_code}")
            return None
        old_off = self._offset_value
        self._offset_value = offset_value or DEFAULT_OFFSET
        try:
            e = entries[0]
            return self._test_single_level(e.pid, e.level, target_address, domain, release=True)
        finally:
            self._offset_value = old_off

    def clear_fault_by_threshold(self, pid_code: str, target_address: int,
                                 domain: str, offset_value: float = DEFAULT_OFFSET) -> bool:
        pid = self.pid_table.get_pid_by_code(pid_code)
        if not pid:
            return False
        env = self._read_environment_value(pid, domain, target_address)
        ok, _ = self._release_all_thresholds(pid, env, target_address)
        return ok

    # ------------------------------------------------------------------
    # 测试序列
    # ------------------------------------------------------------------
    def _run_test_sequence(self, entries: List[PIDLevelEntry]) -> None:
        all_results: List[TestResult] = []
        try:
            # 按 PID 聚合等级，同一 PID 连续测完各级
            by_pid: Dict[int, List[PIDLevelEntry]] = {}
            order: List[int] = []
            for e in entries:
                if e.pid.pid not in by_pid:
                    by_pid[e.pid.pid] = []
                    order.append(e.pid.pid)
                by_pid[e.pid.pid].append(e)

            index = 0
            level_done = 0
            level_total = max(1, sum(len(v) for v in by_pid.values()))
            self.progress.total = level_total
            for pid_val in order:
                if self.stop_requested:
                    logger.info("阈值测试被用户停止")
                    break
                group = by_pid[pid_val]
                pid = group[0].pid
                addr = group[0].target_address
                domain = group[0].domain
                index += 1
                self.progress.current_index = level_done
                self.progress.current_pid = f"0x{pid.pid:04X}"
                self.progress.current_state = ThresholdTestState.PREPARING
                self._update_progress()

                result = self._test_pid_levels(pid, group, addr, domain)
                all_results.append(result)
                level_done += len(group)
                self.progress.current_index = level_done
                if result.overall_status == CheckStatus.PASSED:
                    self.progress.passed_count += 1
                elif result.overall_status in (CheckStatus.FAILED, CheckStatus.ERROR, CheckStatus.TIMEOUT):
                    self.progress.failed_count += 1
                else:
                    self.progress.skipped_count += 1
                if self.on_test_result:
                    try:
                        self.on_test_result(result)
                    except Exception:
                        pass
                if index < len(order):
                    time.sleep(TestConstants.TEST_PAUSE_INTERVAL_SEC)
        except Exception as e:
            logger.error(f"阈值测试序列异常: {e}", exc_info=True)
            self.progress.current_state = ThresholdTestState.FAILED
        finally:
            self.is_running = False
            self.progress.current_state = ThresholdTestState.COMPLETED
            self._results = all_results
            self._update_progress()
            if self.on_test_complete:
                try:
                    self.on_test_complete(all_results)
                except Exception:
                    pass
            logger.info(
                f"阈值测试完成: 通过={self.progress.passed_count} "
                f"失败={self.progress.failed_count} 跳过={self.progress.skipped_count}"
            )

    def _test_pid_levels(self, pid: PIDConfig, group: List[PIDLevelEntry],
                         target_address: int, domain: str) -> TestResult:
        """同一 PID 的使能等级依次触发并回读，最后统一解除"""
        levels = [e.level for e in group]
        pid_label = f"0x{pid.pid:04X}"
        result = TestResult(
            test_id=f"threshold_{pid_label}_{datetime.now().strftime('%H%M%S')}",
            test_type="threshold",
            fault_name=pid.alarm_category,
            pid_name=pid_label,
            bms_address=target_address,
            domain_type=domain,
            metadata={
                "pid": hex(pid.pid),
                "levels": ",".join(str(x) for x in levels),
                "test_type": self._test_type,
            },
        )
        result.start()

        try:
            self.can_manager.clear_signal_cache()
        except Exception:
            pass

        self.progress.current_state = ThresholdTestState.READING_ENV
        self._update_progress()
        env = self._read_environment_value(pid, domain, target_address)
        env_check = Check(
            name="环境实际值",
            check_type=CheckType.THRESHOLD_SET,
            description="读取动态阈值基准",
            expected_value="可读",
            actual_value=env,
        )
        env_check.start()
        if env is None:
            env_check.fail("环境实际值读取失败")
            result.add_check(env_check)
            result.fail("环境实际值读取失败")
            return result
        env_check.pass_check(f"env={env}")

        trigger_failed = False
        first_level = True
        for level in levels:
            if self.stop_requested:
                break
            self.progress.current_level = level
            self.progress.current_state = ThresholdTestState.SETTING
            self._update_progress()

            ok_set, set_check = self._set_thresholds_for_level(pid, level, env, target_address)
            if first_level:
                result.add_check(env_check)
                first_level = False
            result.add_check(set_check)
            if not ok_set:
                trigger_failed = True
                continue

            wait_t = self._alarm_wait_time_sec or 5.0
            if pid.mature_time and pid.mature_time > 0:
                wait_t = max(wait_t, float(pid.mature_time))
            logger.debug(f"等待报警成熟: {wait_t}s")
            time.sleep(wait_t)

            self.progress.current_state = ThresholdTestState.VERIFYING
            self._update_progress()
            verify_result = self._verify_level(pid, level, target_address, domain)
            # 合并 verifier 检查项
            for c in verify_result.checks:
                result.add_check(c)
            if verify_result.overall_status != CheckStatus.PASSED:
                trigger_failed = True

        self.progress.current_state = ThresholdTestState.RELEASING
        self._update_progress()
        if not self.stop_requested:
            ok_rel, rel_check = self._release_all_thresholds(pid, env, target_address)
            result.add_check(rel_check)

        result.complete()
        if trigger_failed and result.overall_status == CheckStatus.PASSED:
            result.overall_status = CheckStatus.FAILED
        logger.info(f"PID {pid_label} {pid.alarm_category} 测试完成: {result.overall_status.value}")
        return result

    def _test_single_level(self, pid: PIDConfig, level: int,
                           target_address: int, domain: str,
                           release: bool = True) -> Optional[TestResult]:
        return self._test_pid_levels(
            pid,
            [PIDLevelEntry(pid, level, target_address, domain)],
            target_address,
            domain,
        )

    def _update_progress(self):
        self.progress.elapsed_time = time.time() - self.progress.start_time if self.progress.start_time else 0
        if self.on_progress_update:
            try:
                self.on_progress_update(self.progress)
            except Exception:
                pass
