"""
故障码测试引擎
负责发送DAPP_FaultSet报文注入故障，并协调验证过程
移植自 报警测试/src/engine/fault_engine.py
去PySide6依赖（使用回调函数通信）
"""

import logging
import time
import threading
from typing import List, Optional, Dict, Any, Callable, Union
from dataclasses import dataclass
from enum import Enum

from bms_alarm_test.config.can_readback_config import get_readback_config
from bms_alarm_test.config.fault_mapping import Fault, FaultMapping, FaultDomain
from bms_alarm_test.models.test_result import (
    TestResult,
    CheckStatus,
    CheckType,
    READBACK_SCOPE_OUTER,
)
from bms_alarm_test.can.can_manager import CANManager
from bms_alarm_test.engine.verifier import BMSVerifier
from bms_alarm_test.can.can_listener import CANChannel
from bms_alarm_test.config.constants import (
    CANConstants,
    TimingConstants,
    TestConstants,
    FaultConstants,
)
from bms_alarm_test.utils.exceptions import TestExecutionError, CANError

logger = logging.getLogger(__name__)


class TestState(Enum):
    """测试状态"""
    IDLE = "idle"
    PREPARING = "preparing"
    INJECTING = "injecting"
    VERIFYING = "verifying"
    CLEARING = "clearing"
    COMPLETED = "completed"
    FAILED = "failed"
    # 独立的「清除所有故障中」状态：用于一键清除/测试前全清的进度展示
    CLEANING_PROGRESS = "cleaning_progress"


@dataclass
class TestProgress:
    """测试进度"""
    current_fault_index: int = 0
    total_faults: int = 0
    current_state: TestState = TestState.IDLE
    current_fault: Optional[Fault] = None
    start_time: float = 0.0
    elapsed_time: float = 0.0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    # 清除进度（清除所有故障时使用）：当前故障码 / 总故障码
    clear_current: int = 0
    clear_total: int = 0


class FaultTestEngine:
    """故障码测试引擎"""

    def __init__(self, can_manager: CANManager, fault_mapping: FaultMapping):
        self.can_manager = can_manager
        self.fault_mapping = fault_mapping
        self.verifier = BMSVerifier(can_manager, fault_mapping)

        # 测试配置
        self.target_addresses: Dict[FaultDomain, int] = {
            FaultDomain.NBCMU: TestConstants.DEFAULT_BMS_ADDRESS,
            FaultDomain.SBCMU: 0xB1,
        }
        self.injection_delay_sec = TimingConstants.DEFAULT_INJECTION_DELAY_SEC
        self.verification_timeout_sec = TimingConstants.DEFAULT_VERIFICATION_TIMEOUT_SEC
        self.clear_delay_sec = TimingConstants.DEFAULT_CLEAR_DELAY_SEC
        self.clear_confirm_timeout_sec = TimingConstants.DEFAULT_CLEAR_CONFIRM_TIMEOUT_SEC

        # 是否读取对外报文做对外验证（对外无报文时可关闭，跳过回读）
        self.read_outer_messages = True

        # 可配置的暂停间隔
        self.test_pause_interval_sec = TestConstants.TEST_PAUSE_INTERVAL_SEC

        # 测试状态
        self.progress = TestProgress()
        self.is_running = False
        self.stop_requested = False
        self.fail_on_first_error = False
        self._clear_aborted = False
        # 「本次运行一个故障码都没测」的中止说明（非空即代表未测任何故障码），供界面原样展示：
        #   abort_reason = 失败原因（CAN 发送异常等）
        #   stop_reason  = 用户主动停止（非失败）
        # 没有这两个字段时，界面只能拿到空结果列表，会把「0 通过 0 失败」画成测试成功。
        self.abort_reason: str = ""
        self.stop_reason: str = ""
        # clear_all_faults 内部记录中止原因，供 _run_test_sequence 取出（每次调用前复位）
        self._clear_abort_reason: str = ""
        self.current_thread: Optional[threading.Thread] = None

        # 回调函数
        self.on_progress_update: Optional[Callable[[TestProgress], None]] = None
        self.on_test_result: Optional[Callable[[TestResult], None]] = None
        self.on_test_complete: Optional[Callable[[List[TestResult]], None]] = None

    def start_test(self, fault_codes: Optional[List[str]] = None,
                   target_addresses: Union[Dict[FaultDomain, int], int, None] = None,
                   fail_on_first_error: bool = False) -> bool:
        """
        开始故障测试
        target_addresses: dict 以 FaultDomain 为 key 的地址映射，或单个 int（向后兼容，作为 NBCMU 地址）
        """
        if self.is_running:
            logger.warning("测试引擎已在运行中")
            return False

        # 获取要测试的故障列表
        if fault_codes:
            faults = self.fault_mapping.get_faults_by_codes(fault_codes)
        else:
            faults = self.fault_mapping.get_all_faults()

        if not faults:
            logger.error("没有找到要测试的故障")
            return False

        # 处理 target_addresses：支持向后兼容
        if isinstance(target_addresses, dict):
            self.target_addresses = {
                FaultDomain.NBCMU: target_addresses.get(FaultDomain.NBCMU, TestConstants.DEFAULT_BMS_ADDRESS),
                FaultDomain.SBCMU: target_addresses.get(FaultDomain.SBCMU, 0xB1),
            }
        elif isinstance(target_addresses, int):
            # 旧调用方式：单个 int 作为 NBCMU 地址
            self.target_addresses = {
                FaultDomain.NBCMU: target_addresses,
                FaultDomain.SBCMU: 0xB1,
            }
        else:
            # 使用默认值
            self.target_addresses = {
                FaultDomain.NBCMU: TestConstants.DEFAULT_BMS_ADDRESS,
                FaultDomain.SBCMU: 0xB1,
            }

        # 重置状态
        self.progress = TestProgress(
            current_fault_index=0,
            total_faults=len(faults),
            current_state=TestState.IDLE,
            start_time=time.time()
        )

        self.is_running = True
        self.stop_requested = False
        self.abort_reason = ""
        self.stop_reason = ""
        self.fail_on_first_error = fail_on_first_error

        # 清除之前的停止请求
        try:
            self.can_manager.clear_stop()
        except CANError:
            pass

        # 启动测试线程
        self.current_thread = threading.Thread(
            target=self._run_test_sequence,
            args=(faults,),
            name="FaultTestEngine"
        )
        self.current_thread.daemon = True
        self.current_thread.start()

        logger.info(f"开始测试 {len(faults)} 个故障，地址配置={self.target_addresses}")
        return True

    def step_test_single(self, fault_code: int, target_addresses: Dict[FaultDomain, int],
                         domain: Optional[FaultDomain] = None,
                         clear_previous: bool = True, auto_clear_after: bool = False) -> Optional[TestResult]:
        """
        单步测试：同步执行，返回 TestResult
        - clear_previous=True: 先清除上一个测试的故障
        - auto_clear_after=False: 验证后不清除，留在 ECU 上
        """
        if self.is_running:
            logger.warning("测试引擎已在运行中")
            return None

        # 复位上次「停止」遗留的标志（只有 start_test 会复位），
        # 否则下方验证会因 is_stop_requested 直接返回 None，全部检查项秒失败
        self.clear_stop_request()

        # 同 start_test：清掉上轮的中止说明，避免旧原因影响本轮界面显示
        self.abort_reason = ""
        self.stop_reason = ""

        # 更新目标地址
        self.target_addresses = {
            FaultDomain.NBCMU: target_addresses.get(FaultDomain.NBCMU, TestConstants.DEFAULT_BMS_ADDRESS),
            FaultDomain.SBCMU: target_addresses.get(FaultDomain.SBCMU, 0xB1),
        }

        # 获取故障（支持同码多版本：57-NBCMU / 57-SBCMU）
        fault = self.fault_mapping.get_fault(fault_code, domain)
        if not fault:
            logger.error(f"故障码 {fault_code} 域 {domain} 不存在")
            return None

        # 如果需要，先清除上一个故障
        if clear_previous and hasattr(self, '_last_step_fault') and self._last_step_fault:
            logger.info(f"[step] 清除上一个故障: {self._last_step_fault.code}")
            self._clear_fault(self._last_step_fault)
            time.sleep(self.clear_delay_sec)

        # 记录当前故障
        self._last_step_fault = fault

        # 执行单步测试
        result = self._test_single_fault(fault, auto_clear=auto_clear_after)
        return result

    def step_clear_all(self) -> bool:
        """单步模式结束：清除所有故障"""
        if hasattr(self, '_last_step_fault') and self._last_step_fault:
            logger.info(f"[step] 结束单步模式，清除故障: {self._last_step_fault.code}")
            success = self._clear_fault(self._last_step_fault)
            self._last_step_fault = None
            return success
        # 没有上次的故障，全清
        self.verifier.clear_signal_cache()
        for domain in self.target_addresses:
            self.clear_all_faults(domain)
        return True

    def stop_test(self) -> None:
        """停止测试"""
        if not self.is_running:
            return

        self.stop_requested = True
        try:
            self.can_manager.request_stop()
        except CANError:
            pass
        logger.info("测试停止请求已发送")

    def clear_stop_request(self) -> None:
        """
        清除上次「停止」遗留的停止标志
        start_test() 会复位这些标志，但单步测试、一键清除等同步路径不经过它。
        标志残留时：全清被立即中断，验证 _wait_for_signal 直接返回 None（所有检查项秒失败），
        而注入发送不受影响，表现为「故障能触发但结果显示失败」。
        """
        stale = self.stop_requested
        try:
            stale = stale or self.can_manager.is_stop_requested()
            self.can_manager.clear_stop()
        except Exception:
            pass
        self.stop_requested = False
        if stale:
            logger.info("[stop] 已清除上次遗留的停止请求（单步/清除路径不经过 start_test 复位）")

    def wait_for_completion(self, timeout_sec: float = 300.0) -> bool:
        """
        等待测试完成
        """
        if not self.current_thread:
            return True

        self.current_thread.join(timeout=timeout_sec)
        return not self.current_thread.is_alive()

    def get_progress(self) -> TestProgress:
        """获取当前进度"""
        self.progress.elapsed_time = time.time() - self.progress.start_time
        return self.progress

    def _run_test_sequence(self, faults: List[Fault]) -> None:
        """运行测试序列"""
        all_results: List[TestResult] = []

        # 全局清除：对每个域用对应地址清空故障
        logger.info("测试前准备：清除所有故障中...")
        self._update_progress(TestState.PREPARING)
        self.verifier.clear_signal_cache()
        for domain in self.target_addresses:
            if self.stop_requested:
                break
            ok = self.clear_all_faults(domain)
            # 发送层连续失败说明总线/通道异常，继续清码只会空转
            if not ok and self._clear_aborted:
                if self.stop_requested:
                    # 用户在准备阶段点了停止：属于中断，不是失败
                    self.stop_reason = (
                        "用户在准备阶段点击了「停止故障测试」，本次测试已中断，"
                        "未测试任何故障码。"
                    )
                    logger.info("准备阶段收到停止请求，中断测试")
                    self.progress.current_state = TestState.COMPLETED
                else:
                    self.abort_reason = self._clear_abort_reason or (
                        "准备阶段清除故障失败（CAN 发送异常），测试已中断，未测试任何故障码。"
                    )
                    logger.error("准备阶段清除故障失败（CAN 发送异常），中断测试")
                    self.progress.current_state = TestState.FAILED
                self.is_running = False
                self._update_progress(self.progress.current_state)
                if self.on_test_complete:
                    try:
                        self.on_test_complete([])
                    except Exception:
                        pass
                return

        if self.stop_requested:
            self.stop_reason = (
                "用户在测试开始前点击了「停止故障测试」，本次测试已中断，未测试任何故障码。"
            )
            self.is_running = False
            self.progress.current_state = TestState.COMPLETED
            self._update_progress(TestState.COMPLETED)
            if self.on_test_complete:
                try:
                    self.on_test_complete([])
                except Exception:
                    pass
            return

        # 根据 target_addresses 动态扩展 CH0 监控报文范围
        self._update_monitored_ids()

        try:
            for i, fault in enumerate(faults):
                if self.stop_requested:
                    logger.info("测试被用户停止")
                    self.stop_reason = (
                        f"用户在第 {i + 1}/{len(faults)} 个故障处点击了「停止故障测试」，"
                        f"本次测试已中断（已测部分的结果见统计）。"
                    )
                    break

                # 更新进度
                self.progress.current_fault_index = i + 1
                self.progress.current_fault = fault
                self._update_progress(TestState.PREPARING)

                # 测试单个故障
                result = self._test_single_fault(fault)
                all_results.append(result)

                # 更新统计
                if result.overall_status == CheckStatus.PASS:
                    self.progress.passed_count += 1
                elif result.overall_status == CheckStatus.FAIL:
                    self.progress.failed_count += 1
                else:
                    self.progress.skipped_count += 1

                # 通知结果
                if self.on_test_result:
                    self.on_test_result(result)

                # 失败处理：遇到失败是否中断
                if self.fail_on_first_error and result.overall_status == CheckStatus.FAIL:
                    logger.info(f"故障{fault.code}失败，按配置中断测试")
                    break

                # 短暂暂停
                if i < len(faults) - 1 and not self.stop_requested:
                    time.sleep(0.1)

        except TestExecutionError as e:
            logger.error(f"测试序列执行异常: {e}")
            self.progress.current_state = TestState.FAILED
        except Exception as e:
            logger.error(f"测试序列执行异常（未知错误）: {e}", exc_info=True)
            self.progress.current_state = TestState.FAILED
        finally:
            self.is_running = False
            self.progress.current_state = TestState.COMPLETED
            try:
                self._update_progress(TestState.COMPLETED)
            except Exception:
                pass

            # 通知完成
            if self.on_test_complete:
                try:
                    self.on_test_complete(all_results)
                except Exception:
                    pass

            logger.info(f"测试完成: 通过={self.progress.passed_count}, "
                       f"失败={self.progress.failed_count}, "
                       f"跳过={self.progress.skipped_count}")

    def _resolve_address(self, domain: FaultDomain) -> int:
        """将域解析为目标地址，BOTH 统一映射到 NBCMU 地址"""
        if domain == FaultDomain.BOTH:
            return self.target_addresses.get(FaultDomain.NBCMU, TestConstants.DEFAULT_BMS_ADDRESS)
        return self.target_addresses.get(domain, TestConstants.DEFAULT_BMS_ADDRESS)

    def _is_stop_requested(self) -> bool:
        """
        是否已收到停止请求
        引擎标志与 CAN 管理层标志任一为真即算已停止：
        _wait_for_signal 只看 can_manager.is_stop_requested()，直接调用
        can_manager.request_stop() 的路径不会置位 stop_requested。
        """
        if self.stop_requested:
            return True
        try:
            return bool(self.can_manager.is_stop_requested())
        except Exception:
            return False

    def _test_single_fault(self, fault: Fault, auto_clear: bool = True) -> TestResult:
        """
        测试单个故障
        流程：清除缓存 → 注入故障 → 等待生效 → 双重验证 → [回读超时则重注入复验一次]
              → [清除故障] → 返回结果
        auto_clear=False 时跳过清除步骤，用于单步调试模式
        """
        logger.info(f"开始测试故障: {fault.code} - {fault.name}")

        # 1. 清除信号缓存
        self._update_progress(TestState.PREPARING)
        self.verifier.clear_signal_cache()

        # 2. 发送故障注入报文
        self._update_progress(TestState.INJECTING)
        injection_success = self._inject_fault(fault)

        if not injection_success:
            logger.error(f"故障{fault.code}注入失败")
            return self._create_failed_result(fault, "故障注入失败")

        # 3. 等待故障生效
        logger.debug(f"等待故障生效: {self.injection_delay_sec}秒")
        time.sleep(self.injection_delay_sec)

        # 4. 执行双重验证
        self._update_progress(TestState.VERIFYING)
        addr = self._resolve_address(fault.domain)
        result = self.verifier.verify_fault(fault, addr, fault.domain.value,
                                            read_outer=self.read_outer_messages)

        # 4.1 第1轮结果「对内信号不可信」→ 重新注入并复验（第2轮，共两轮验证）
        # 触发条件有两种「对内不可信」，都要重发一次故障帧才有机会翻盘：
        #   a) 对内回读超时：信号始终没读到（timed_out=True，timed_out_scope=inner）；
        #   b) 对内读到了稳定但与期望不符的值：BMS 又快又稳地回 SysFailSta=0/ErrTab=0
        #      （"No Error"）——正是「注入的故障根本没生效」的表现，
        #      _wait_for_signal 回传该错误值后 timed_out 不再置位，历史上因此完全不会重试。
        #      重发故障帧是这种情况唯一合理的补救手段。
        # 只认对内通道：对外通道的失败/超时是接线条件（对外线未接 / 台架上 CH1 一帧不发），
        # 重发对内故障报文改变不了它，用它触发会让每个故障都白跑第2轮、测试时间翻倍。
        # 停止请求时 _wait_for_signal 同样返回 None，必须排除，否则会误触发重注入。
        # 第2轮前不清信号缓存：若故障本就在第1轮末尾才置位，可快速确认，省掉一个超时窗口。
        retry_reasons = self._collect_reinject_reasons(result, fault)
        if retry_reasons and not self._is_stop_requested():
            logger.warning(f"[重试] 故障{fault.code} {'/'.join(retry_reasons)}，"
                           f"重新注入并复验（第2轮）")
            self._update_progress(TestState.INJECTING)
            reinject_success = self._inject_fault(fault)
            if not reinject_success:
                logger.error(f"[重试] 故障{fault.code} 重新注入失败，保留第1轮结果")
            else:
                time.sleep(self.injection_delay_sec)
                self._update_progress(TestState.VERIFYING)
                result = self.verifier.verify_fault(fault, addr, fault.domain.value,
                                                    read_outer=self.read_outer_messages)
                logger.info(f"[重试] 故障{fault.code} 复验结果: {result.overall_status.value}")

        # 5. 清除故障（auto_clear=True 时才清除）
        if auto_clear:
            self._update_progress(TestState.CLEARING)
            clear_success = self._clear_fault(fault)
            if not clear_success:
                logger.warning(f"故障{fault.code}清除失败")

            # 6. 等待故障清除
            time.sleep(self.clear_delay_sec)

        # 7. 返回结果
        logger.info(f"故障{fault.code}测试完成: {result.overall_status.value}")
        return result

    # 对内通道的检查项类型：只有这些「对内回读」的检查项不可信时才可能是故障帧没送达。
    # 对外检查项（OUTER_*）的失败属于接线/台架条件，重发对内故障报文无济于事。
    _INNER_CHECK_TYPES = (
        CheckType.INNER_SYS_FAIL_STA,
        CheckType.INNER_ERR_TAB,
        CheckType.INNER_SPECIFIC,
    )

    def _collect_reinject_reasons(self, result: TestResult, fault: Optional[Fault] = None) -> List[str]:
        """收集「值得重新注入复验一次」的原因；为空表示不重试

        两种原因都只认对内通道：
        - "对内回读超时"：信号始终没读到值（Check.timed_out=True 且角色为 inner）
        - "对内值不匹配"：读到了值但与期望不符（典型为 BMS 稳定回 SysFailSta=0/ErrTab=0
          的「无故障」，即注入的故障没生效）——这种之前从不重试，恰恰是重发故障帧
          唯一能救回来的场景。
        """
        reasons: List[str] = []
        if result.has_inner_readback_timeout():
            reasons.append("对内回读超时")
        if self._has_inner_stable_mismatch(result, fault):
            reasons.append("对内值不匹配")
        return reasons

    def _has_inner_stable_mismatch(self, result: TestResult,
                                   fault: Optional[Fault] = None) -> bool:
        """本轮验证是否存在「对内通道读到了错误值」的检查项

        判据全部取自 Check 已有字段（用 getattr 兜底，兼容旧结果对象）：
        - 状态为 FAILED（不是 ERROR/TIMEOUT，也不是通过）
        - actual_value 不为 None：说明确实读到了值（读不到值的情形由 timed_out 分支处理）
        - timed_out_scope 明确为 outer 的一律排除
        - check_type 属于对内检查项；extra_checks 无论内外都标成 INNER_SPECIFIC，
          这里再用 fault.extra_checks 里配置的角色把「对外额外回读」剔除
        """
        for c in getattr(result, "checks", None) or []:
            if getattr(c, "status", None) != CheckStatus.FAILED:
                continue
            if getattr(c, "actual_value", None) is None:
                continue  # 没读到值，不是「读到了错误的值」
            if getattr(c, "timed_out_scope", None) == READBACK_SCOPE_OUTER:
                continue
            if getattr(c, "check_type", None) not in self._INNER_CHECK_TYPES:
                continue
            if self._is_outer_extra_check(c, fault):
                continue
            return True
        return False

    @staticmethod
    def _is_outer_extra_check(check, fault: Optional[Fault] = None) -> bool:
        """判断检查项是否为配置成对外通道的 extra_checks 额外回读

        verifier 里 extra_checks 一律用 CheckType.INNER_SPECIFIC 作类型（不看 role），
        只能从 fault 的配置里按名称把 role=outer 的那些剔除。
        """
        name = str(getattr(check, "name", "") or "")
        for item in (getattr(fault, "extra_checks", None) or []):
            if not isinstance(item, dict):
                continue
            if (item.get("channel_role") or "inner") != "outer":
                continue
            extra_name = item.get("name") or item.get("signal_name") or ""
            if extra_name and name.startswith(f"额外回读: {extra_name}"):
                return True
        return False

    def _get_inner_channel(self) -> int:
        """获取当前配置的对内通道号（发送故障注入的通道）"""
        try:
            settings = self.can_manager.settings
            if settings:
                return settings.get_inner_channel()
        except Exception:
            pass
        return CANConstants.CHANNEL_1

    @staticmethod
    def _inject_can_id() -> int:
        """注入/清除报文 CAN ID：优先读可编辑回读协议配置"""
        try:
            inj = get_readback_config().inject or {}
            cid = inj.get("can_id", None)
            if cid is not None:
                return int(str(cid), 0) if not isinstance(cid, int) else cid
        except Exception:
            pass
        return CANConstants.DAPP_FAULTSET_MSG_ID

    @staticmethod
    def _inject_extended() -> bool:
        try:
            return bool((get_readback_config().inject or {}).get("is_extended", True))
        except Exception:
            return True

    def _inject_fault(self, fault: Fault) -> bool:
        """
        注入故障 - 发送故障设置报文
        策略：连续发N次，帧间隔M毫秒，两遍间隔K毫秒
        CAN ID/扩展帧来自「CAN 回读协议配置」
        """
        try:
            message_id = self._inject_can_id()
            is_ext = self._inject_extended()
            data = self._build_fault_injection_data(fault)
            if data is None:
                return False
            inner_ch = self._get_inner_channel()
            data_hex = ' '.join(f'{b:02X}' for b in data)
            logger.info(f"[注入] 故障{fault.code} 目标={self._resolve_address(fault.domain)} "
                        f"通道=CH{inner_ch} 报文ID=0x{message_id:X} 数据=[{data_hex}]")

            # 第一遍
            for i in range(TimingConstants.FAULT_INJECTION_REPEAT_COUNT):
                success = self.can_manager.send_message(
                    channel=inner_ch,
                    message_id=message_id,
                    data=data,
                    is_extended_id=is_ext
                )
                if not success:
                    logger.error(f"故障注入报文发送失败(第{i+1}次): {fault.code}")
                    return False
                logger.debug(f"故障注入报文已发送(第{i+1}次): {fault.code} 等级={fault.fault_level}")
                if i < TimingConstants.FAULT_INJECTION_REPEAT_COUNT - 1:
                    time.sleep(TimingConstants.FAULT_INJECTION_FRAME_INTERVAL_MS / 1000.0)

            # 两遍间隔
            time.sleep(TimingConstants.FAULT_INJECTION_REPEAT_INTERVAL_MS / 1000.0)

            # 第二遍
            for i in range(TimingConstants.FAULT_INJECTION_REPEAT_COUNT):
                success = self.can_manager.send_message(
                    channel=inner_ch,
                    message_id=message_id,
                    data=data,
                    is_extended_id=is_ext
                )
                if not success:
                    logger.error(f"故障注入报文发送失败(第{i+3}次): {fault.code}")
                    return False
                logger.debug(f"故障注入报文已发送(第{i+3}次): {fault.code} 等级={fault.fault_level}")
                if i < TimingConstants.FAULT_INJECTION_REPEAT_COUNT - 1:
                    time.sleep(TimingConstants.FAULT_INJECTION_FRAME_INTERVAL_MS / 1000.0)

            logger.info(f"故障注入完成(共{TimingConstants.FAULT_INJECTION_REPEAT_COUNT * 2}次): "
                       f"{fault.code} 等级={fault.fault_level}")
            return True

        except CANError as e:
            logger.error(f"故障注入异常: {e}")
            return False
        except Exception as e:
            logger.error(f"故障注入异常（未知错误）: {e}", exc_info=True)
            return False

    def _clear_fault(self, fault: Fault) -> bool:
        """
        清除故障 - 发送DAPP_FaultSet报文，手动强制模式
        策略：与注入一致，连续发2遍（帧间隔50ms，两遍间隔200ms）
        """
        try:
            message_id = CANConstants.DAPP_FAULTSET_MSG_ID
            data = self._build_fault_clear_data(fault)
            if data is None:
                return False
            inner_ch = self._get_inner_channel()
            data_hex = ' '.join(f'{b:02X}' for b in data)
            logger.info(f"[清除] 故障{fault.code} 目标={self._resolve_address(fault.domain)} "
                        f"通道=CH{inner_ch} 报文ID=0x{message_id:X} 数据=[{data_hex}]")

            # 第一遍
            for i in range(TimingConstants.FAULT_CLEAR_REPEAT_COUNT):
                success = self.can_manager.send_message(
                    channel=inner_ch,
                    message_id=message_id,
                    data=data,
                    is_extended_id=True
                )
                if not success:
                    logger.warning(f"故障清除报文发送失败(第{i+1}次): {fault.code}")
                    return False
                if i < TimingConstants.FAULT_CLEAR_REPEAT_COUNT - 1:
                    time.sleep(TimingConstants.FAULT_CLEAR_FRAME_INTERVAL_MS / 1000.0)

            # 两遍间隔
            time.sleep(TimingConstants.FAULT_CLEAR_REPEAT_INTERVAL_MS / 1000.0)

            # 第二遍
            for i in range(TimingConstants.FAULT_CLEAR_REPEAT_COUNT):
                success = self.can_manager.send_message(
                    channel=inner_ch,
                    message_id=message_id,
                    data=data,
                    is_extended_id=True
                )
                if not success:
                    logger.warning(f"故障清除报文发送失败(第{i+3}次): {fault.code}")
                    return False
                if i < TimingConstants.FAULT_CLEAR_REPEAT_COUNT - 1:
                    time.sleep(TimingConstants.FAULT_CLEAR_FRAME_INTERVAL_MS / 1000.0)

            logger.info(f"故障清除报文已发送(共{TimingConstants.FAULT_CLEAR_REPEAT_COUNT * 2}次): {fault.code}")
            return True

        except CANError as e:
            logger.warning(f"故障清除异常: {e}")
            return False
        except Exception as e:
            logger.warning(f"故障清除异常（未知错误）: {e}", exc_info=True)
            return False

    def _build_fault_injection_data(self, fault: Fault) -> Optional[bytes]:
        """构建故障注入数据（通过 DBC encoder 编码 DAPP_FaultSet）"""
        target = self._resolve_address(fault.domain)
        encoded = self.can_manager.dbc_loader.encode_message(
            dbc_type='inner',
            message_name='DAPP_FaultSet',
            signals={
                'DAPP_Fault_Addr_Target': target,
                'DAPP_ErrCode': fault.code & 0xFF,
                'DAPP_Set_Fault': 1,
                'DAPP_FaultDetect_Mode': 1,
            }
        )
        if encoded is None:
            logger.error(f"故障{fault.code}报文编码失败（DBC 中缺少 DAPP_FaultSet）")
            return None
        can_id, data = encoded
        data_hex = ' '.join(f'{b:02X}' for b in data)
        logger.debug(f"[编码] 注入故障{fault.code} 目标={target} CAN_ID=0x{can_id:X} 数据=[{data_hex}]")
        return data

    def _build_fault_clear_data(self, fault: Fault) -> Optional[bytes]:
        """构建故障清除数据（通过 DBC encoder 编码 DAPP_FaultSet）"""
        target = self._resolve_address(fault.domain)
        encoded = self.can_manager.dbc_loader.encode_message(
            dbc_type='inner',
            message_name='DAPP_FaultSet',
            signals={
                'DAPP_Fault_Addr_Target': target,
                'DAPP_ErrCode': fault.code & 0xFF,
                'DAPP_Set_Fault': 0,
                'DAPP_FaultDetect_Mode': 1,
            }
        )
        if encoded is None:
            logger.error(f"故障{fault.code}报文编码失败（DBC 中缺少 DAPP_FaultSet）")
            return None
        can_id, data = encoded
        data_hex = ' '.join(f'{b:02X}' for b in data)
        logger.debug(f"[编码] 清除故障{fault.code} 目标={target} CAN_ID=0x{can_id:X} 数据=[{data_hex}]")
        return data

    def _create_failed_result(self, fault: Fault, error_message: str) -> TestResult:
        """创建失败结果"""
        from datetime import datetime
        return TestResult(
            test_id=f"fault_{fault.code}_{datetime.now().strftime('%H%M%S')}",
            test_type="fault",
            fault_name=fault.name,
            overall_status=CheckStatus.FAIL,
            error_message=error_message,
            metadata={"fault_code": str(fault.code)}
        )

    def _update_progress(self, state: TestState) -> None:
        """更新进度状态"""
        self.progress.current_state = state
        self.progress.elapsed_time = time.time() - self.progress.start_time

        if self.on_progress_update:
            self.on_progress_update(self.progress)

        logger.debug(f"测试状态更新: {state.value}")

    def _report_clear_progress(self, current_code: int, total: int) -> None:
        """报告清除所有故障的发送进度（在后台线程中调用，UI 侧经信号调度）"""
        self.progress.current_state = TestState.CLEANING_PROGRESS
        self.progress.clear_current = current_code
        self.progress.clear_total = total
        self.progress.elapsed_time = time.time() - self.progress.start_time

        if self.on_progress_update:
            self.on_progress_update(self.progress)

    def set_callbacks(self,
                     on_progress_update: Optional[Callable[[TestProgress], None]] = None,
                     on_test_result: Optional[Callable[[TestResult], None]] = None,
                     on_test_complete: Optional[Callable[[List[TestResult]], None]] = None) -> None:
        """设置回调函数"""
        self.on_progress_update = on_progress_update
        self.on_test_result = on_test_result
        self.on_test_complete = on_test_complete

    def get_test_summary(self) -> Dict[str, Any]:
        """获取测试摘要"""
        return {
            "total_faults": self.progress.total_faults,
            "passed": self.progress.passed_count,
            "failed": self.progress.failed_count,
            "skipped": self.progress.skipped_count,
            "elapsed_time": self.progress.elapsed_time,
            "current_state": self.progress.current_state.value,
            "is_running": self.is_running
        }

    def reset(self) -> None:
        """重置引擎状态"""
        self.stop_test()

        if self.current_thread and self.current_thread.is_alive():
            self.current_thread.join(timeout=2.0)

        self.is_running = False
        self.stop_requested = False
        self.abort_reason = ""
        self.stop_reason = ""
        self.progress = TestProgress()
        logger.info("测试引擎已重置")

    def _update_monitored_ids(self):
        """根据 target_addresses 动态扩展对内通道监控报文ID"""
        if not self.can_manager._listener:
            return

        listener = self.can_manager._listener
        inner_ch = self._get_inner_channel()
        can_ch = CANChannel.CH1 if inner_ch == 1 else CANChannel.CH2
        monitored = listener._monitored_message_ids[can_ch]

        for domain, addr in self.target_addresses.items():
            last_byte = addr & 0xFF
            if domain == FaultDomain.NBCMU:
                ids = {
                    0x18B1FF00 | last_byte,  # NBCMU{idx}_WarningInfo1
                    0x18BBFF00 | last_byte,  # NBCMU{idx}_WarningInfo2
                    0x18A3FF00 | last_byte,  # NBCMU{idx}_WarningInfo3
                }
            else:  # SBCMU
                ids = {
                    0x18B8FF00 | last_byte,  # SBCMU{idx}_WarningInfo
                    0x18A2FF00 | last_byte,  # SBCMU{idx}_DCChrgState
                }

            for msg_id in ids:
                if msg_id not in monitored:
                    monitored.add(msg_id)
                    logger.info(f"[monitor] 添加监控报文: 0x{msg_id:08X}")

        # 合并「CAN 回读协议配置」中的 monitored_ids
        try:
            for mid in get_readback_config().monitored_ids:
                if mid and mid not in monitored:
                    monitored.add(mid)
                    logger.info(f"[monitor] 按回读配置添加监控报文: 0x{mid:08X}")
        except Exception as e:
            logger.debug(f"合并回读配置监控ID失败: {e}")

    def clear_all_faults(self, domain: Union[FaultDomain, int, None] = None) -> bool:
        """
        一键清除所有故障（故障码 1-96）
        domain: FaultDomain 枚举值，或直接传入 int 地址（向后兼容）
        连续发送失败过多或收到停止请求时提前中止，避免界面假死。
        """
        # 归一化 domain：枚举 → 字符串值，避免后续 domain.upper() 崩溃
        if isinstance(domain, FaultDomain):
            domain_str = domain.value
            addr = self.target_addresses.get(domain, TestConstants.DEFAULT_BMS_ADDRESS)
        elif isinstance(domain, int):
            domain_str = "NBCMU"  # 传入 int 地址时按 NBCMU 域处理
            addr = domain
        else:
            domain_str = "NBCMU"
            addr = self.target_addresses.get(FaultDomain.NBCMU, TestConstants.DEFAULT_BMS_ADDRESS)
        logger.info("[clear_all_faults] 开始一键清除")
        if not self.can_manager.is_connected():
            logger.error("[clear_all_faults] CAN未连接")
            return False

        # 连续发送失败阈值：约 3 个故障码全失败（每码 2 轮 × 2 次 = 4 帧）
        max_consecutive_fail = 12
        self._clear_aborted = False
        self._clear_abort_reason = ""

        try:
            message_id = self._inject_can_id()
            inner_ch = self._get_inner_channel()
            success_count = 0
            fail_count = 0
            consecutive_fail = 0
            is_ext = self._inject_extended()

            # 按域决定清码范围
            if domain_str == "SBCMU":
                clear_codes = [81] + list(range(91, 95))  # 81, 91-94
            else:
                clear_codes = range(1, 97)

            total_codes = len(clear_codes)
            for idx, code in enumerate(clear_codes, start=1):
                if self.stop_requested:
                    logger.info("[clear_all_faults] 收到停止请求，中断清除")
                    self._clear_aborted = True
                    return False

                # 清除进度回调：UI 侧展示「清除所有故障中」状态与进度条
                try:
                    self._report_clear_progress(idx, total_codes)
                except Exception:
                    pass

                data = bytearray(8)
                data[0] = addr
                data[1] = code
                data[7] = 0x02

                # 两遍发送，与注入策略一致
                for round_idx in range(2):
                    for i in range(TimingConstants.FAULT_CLEAR_REPEAT_COUNT):
                        ok = self.can_manager.send_message(
                            channel=inner_ch,
                            message_id=message_id,
                            data=bytes(data),
                            is_extended_id=is_ext
                        )
                        if ok:
                            success_count += 1
                            consecutive_fail = 0
                        else:
                            fail_count += 1
                            consecutive_fail += 1
                            logger.warning(f"[clear_all_faults] 发送失败: 故障码={code}")
                        if i < TimingConstants.FAULT_CLEAR_REPEAT_COUNT - 1:
                            time.sleep(TimingConstants.FAULT_CLEAR_FRAME_INTERVAL_MS / 1000.0)

                    if round_idx == 0:
                        time.sleep(TimingConstants.FAULT_CLEAR_REPEAT_INTERVAL_MS / 1000.0)

                # 每个故障码之间间隔
                time.sleep(TimingConstants.FAULT_CLEAR_CODE_INTERVAL_MS / 1000.0)

                if code % 10 == 0 or domain_str == "SBCMU":
                    logger.info(f"[clear_all_faults] 进度: {code}/{total_codes} (成功={success_count}, 失败={fail_count})")

                if consecutive_fail >= max_consecutive_fail:
                    self._clear_aborted = True
                    hint = ""
                    try:
                        hint = "\n" + self.can_manager.tx_fail_hint(inner_ch, message_id)
                    except Exception:
                        pass
                    # 同一段说明同时用于日志与界面（界面据此提示用户，本次测试没有跑起来）
                    self._clear_abort_reason = (
                        f"CAN 通道无法发送报文：连续 {consecutive_fail} 次发送失败"
                        f"（清码进行到故障码 {code}），对内 CAN 通道发不出帧，"
                        f"本次测试无法开始，未测试任何故障码。{hint}"
                    )
                    logger.error(
                        f"[clear_all_faults] 连续 {consecutive_fail} 次发送失败，"
                        f"判定 CAN 发送异常，提前中止（已完成到故障码 {code}）"
                        f"。常见原因：对内CAN线未接在配置的对内通道上。{hint}"
                    )
                    return False

            logger.info(f"[clear_all_faults] 完成: 成功={success_count}, 失败={fail_count}")
            return fail_count == 0

        except Exception as e:
            logger.error(f"[clear_all_faults] 异常: {e}")
            self._clear_aborted = True
            return False

