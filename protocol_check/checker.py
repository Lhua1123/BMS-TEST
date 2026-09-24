"""协议核对引擎：ID / DLC / 信号可解码"""

from collections import Counter, defaultdict
from typing import Dict, List, Optional

from protocol_check.models import (
    CanFrame,
    CheckIssue,
    CheckResult,
    SignalTemplate,
    TemplateBook,
)

# 右侧实报列表最多保留的帧数（避免超大日志撑爆 UI）
UI_FRAME_LIMIT = 2000
# 每个异常类别最多展示的条目
ISSUE_SAMPLE_LIMIT = 50


def _is_motorola(sig: SignalTemplate) -> bool:
    order = (sig.byte_order or "Intel").strip().lower()
    return order.startswith("m") or order.startswith("大") or order in ("be", "big")


def _motorola_bit_positions(start_bit: int, length: int) -> List[int]:
    """Vector DBC Motorola（@0）位序：start 为 MSB，字节内向低位，跨字节进入下一字节 MSB。"""
    positions = []
    bit = start_bit
    for _ in range(length):
        positions.append(bit)
        if bit % 8 == 0:
            bit += 15
        else:
            bit -= 1
    return positions


def _signal_bit_fits(sig: SignalTemplate, frame_bits: int) -> bool:
    if sig.length <= 0 or sig.start_bit < 0 or sig.length > 64:
        return False
    if _is_motorola(sig):
        if sig.start_bit >= frame_bits:
            return False
        try:
            pos = _motorola_bit_positions(sig.start_bit, sig.length)
        except Exception:
            return False
        return all(0 <= p < frame_bits for p in pos)
    # Intel: LSB start, 向高位连续
    return sig.start_bit + sig.length <= frame_bits


def _extract_signal_raw(data: bytes, sig: SignalTemplate) -> Optional[int]:
    """按起始位/长度/字节序提取原始整型；失败返回 None。

    Intel (@1)：start 为 LSB，低位在前。
    Motorola (@0)：start 为 MSB，按 Vector DBC 锯齿位序取 length 位。
    """
    if sig.length <= 0 or sig.start_bit < 0 or sig.length > 64:
        return None
    frame_bits = len(data) * 8
    if not _signal_bit_fits(sig, frame_bits):
        return None

    if _is_motorola(sig):
        raw = 0
        for bit_index in _motorola_bit_positions(sig.start_bit, sig.length):
            byte_index = bit_index // 8
            bit_in_byte = bit_index % 8
            if byte_index >= len(data):
                return None
            bit_val = (data[byte_index] >> bit_in_byte) & 0x1
            raw = (raw << 1) | bit_val
        return raw

    raw = 0
    for i in range(sig.length):
        bit_index = sig.start_bit + i
        byte_index = bit_index // 8
        bit_in_byte = bit_index % 8
        if byte_index >= len(data):
            return None
        bit_val = (data[byte_index] >> bit_in_byte) & 0x1
        raw |= bit_val << i
    return raw


def _to_physical(raw: int, sig: SignalTemplate) -> float:
    if sig.signed:
        bits = sig.length
        if raw >= (1 << (bits - 1)):
            raw -= 1 << bits
    factor = sig.factor if sig.factor not in (None, "") else 1.0
    offset = sig.offset if sig.offset not in (None, "") else 0.0
    try:
        return float(raw) * float(factor) + float(offset)
    except Exception:
        return float(raw)


def _check_signal_on_frame(frame: CanFrame, sig: SignalTemplate) -> Optional[str]:
    """返回 None=可解码；否则返回原因。"""
    if sig.length <= 0:
        return f"信号 {sig.name} 长度无效({sig.length})"
    if sig.start_bit < 0:
        return f"信号 {sig.name} 起始位无效({sig.start_bit})"
    have_bits = frame.dlc * 8
    if not _signal_bit_fits(sig, have_bits):
        if _is_motorola(sig):
            return (
                f"信号 {sig.name} (Motorola start={sig.start_bit} len={sig.length}) "
                f"超出 DLC={frame.dlc} 可用 {have_bits} bit"
            )
        return (
            f"信号 {sig.name} 位段 [{sig.start_bit}..{sig.start_bit + sig.length - 1}] "
            f"超出 DLC={frame.dlc} 可用 {have_bits} bit"
        )
    raw = _extract_signal_raw(frame.data[: frame.dlc], sig)
    if raw is None:
        return f"信号 {sig.name} 无法从数据解码"
    return None


def verify_frames(
    frames: List[CanFrame],
    template: TemplateBook,
    keep_frames: bool = True,
) -> CheckResult:
    result = CheckResult(template=template)
    if not template or not template.messages:
        result.issues.append(
            CheckIssue(
                level="error",
                category="template",
                msg_id_hex="-",
                message="未加载接收协议模板",
                detail="请先导入 Excel 接收模板",
            )
        )
        return result

    id_count: Counter = Counter()
    id_dlc: Dict[int, Counter] = defaultdict(Counter)
    id_first_frame: Dict[int, CanFrame] = {}
    id_signal_fail: Dict[int, set] = defaultdict(set)
    id_signal_fail_msg: Dict[int, List[str]] = defaultdict(list)
    id_decoded_sample: Dict[int, str] = {}

    for fr in frames:
        result.frames_total += 1
        aid = fr.arbitration_id
        id_count[aid] += 1
        id_dlc[aid][fr.dlc] += 1
        if aid not in id_first_frame:
            id_first_frame[aid] = fr
        if keep_frames and len(result.frames) < UI_FRAME_LIMIT:
            result.frames.append(fr)

        msg_tpl = template.messages.get(aid)
        if msg_tpl is None:
            continue

        result.matched_frames += 1
        dlc_issues: List[str] = []
        if msg_tpl.expected_dlc is not None and fr.dlc != msg_tpl.expected_dlc:
            # 仅对首帧统计 DLC 问题，避免刷屏；统计里仍累计
            pass

        if msg_tpl.signals:
            parts = []
            any_fail = False
            for sig in msg_tpl.signals:
                reason = _check_signal_on_frame(fr, sig)
                if reason:
                    any_fail = True
                    key = f"{sig.name}:{sig.start_bit}+{sig.length}"
                    if key not in id_signal_fail[aid]:
                        id_signal_fail[aid].add(key)
                        id_signal_fail_msg[aid].append(reason)
                else:
                    raw = _extract_signal_raw(fr.data[: fr.dlc], sig)
                    phys = _to_physical(raw, sig) if raw is not None else None
                    if raw is not None:
                        unit = sig.unit or ""
                        parts.append(f"{sig.name}={phys:g}{unit}")
            if parts and aid not in id_decoded_sample:
                id_decoded_sample[aid] = ", ".join(parts[:8])

    result.unique_ids = len(id_count)
    result.id_stats = {}
    for aid, cnt in id_count.items():
        dlc_counter = id_dlc[aid]
        main_dlc = dlc_counter.most_common(1)[0][0] if dlc_counter else 0
        fr0 = id_first_frame[aid]
        tpl = template.messages.get(aid)
        result.id_stats[aid] = {
            "count": cnt,
            "dlc": main_dlc,
            "dlc_set": sorted(dlc_counter.keys()),
            "first_data": fr0.data_hex,
            "in_template": tpl is not None,
            "name": tpl.name if tpl else "",
            "expected_dlc": tpl.expected_dlc if tpl else None,
            "required": tpl.required if tpl else False,
            "decoded_sample": id_decoded_sample.get(aid, ""),
            "signal_fail": list(id_signal_fail.get(aid, [])),
        }

    # ── 异常汇总 ──
    issue_budget = {"unexpected_id": 0, "missing_id": 0, "dlc_mismatch": 0, "signal_decode": 0}

    for aid in sorted(id_count.keys()):
        cnt = id_count[aid]
        fr0 = id_first_frame[aid]
        tpl = template.messages.get(aid)
        id_hex = f"{aid:X}"

        if tpl is None:
            issue_budget["unexpected_id"] += 1
            detail = "模板中未定义该报文 ID"
            if issue_budget["unexpected_id"] > ISSUE_SAMPLE_LIMIT:
                detail = "(异常列表截断，统计仍计入)"
            result.issues.append(
                CheckIssue(
                    level="error",
                    category="unexpected_id",
                    msg_id_hex=id_hex,
                    message=f"协议外 ID 0x{id_hex}（出现 {cnt} 次）",
                    detail=detail,
                    sample=fr0.data_hex,
                )
            )
            continue

        # DLC
        if tpl.expected_dlc is not None:
            main_dlc = id_dlc[aid].most_common(1)[0][0] if id_dlc[aid] else -1
            if main_dlc != tpl.expected_dlc:
                result.issues.append(
                    CheckIssue(
                        level="error",
                        category="dlc_mismatch",
                        msg_id_hex=id_hex,
                        message=(
                            f"0x{id_hex} {tpl.name} DLC不符: 实报={main_dlc} 协议={tpl.expected_dlc}"
                        ),
                        detail=f"DLC分布={dict(id_dlc[aid])}",
                        sample=fr0.data_hex,
                    )
                )
            elif len(id_dlc[aid]) > 1:
                result.issues.append(
                    CheckIssue(
                        level="warn",
                        category="dlc_mismatch",
                        msg_id_hex=id_hex,
                        message=f"0x{id_hex} {tpl.name} DLC不唯一: {dict(id_dlc[aid])}",
                        detail="多数帧正确，但存在混合长度",
                        sample=fr0.data_hex,
                    )
                )

        # 信号
        for reason in id_signal_fail_msg.get(aid, []):
            result.issues.append(
                CheckIssue(
                    level="error",
                    category="signal_decode",
                    msg_id_hex=id_hex,
                    message=f"0x{id_hex} {tpl.name}: {reason}",
                    detail="信号位段与实报 DLC/布局不匹配",
                    sample=id_decoded_sample.get(aid, fr0.data_hex),
                )
            )

    for aid, tpl in template.messages.items():
        if not tpl.required:
            continue
        if aid not in id_count:
            id_hex = f"{aid:X}"
            result.issues.append(
                CheckIssue(
                    level="error",
                    category="missing_id",
                    msg_id_hex=id_hex,
                    message=f"缺失报文 0x{id_hex} {tpl.name}",
                    detail="模板标记为必须出现，但日志/采集未见",
                )
            )

    # 稳定排序：error 在前，同级按类别
    level_rank = {"error": 0, "warn": 1, "info": 2}
    cat_rank = {"missing_id": 0, "unexpected_id": 1, "dlc_mismatch": 2, "signal_decode": 3, "template": 4}
    result.issues.sort(key=lambda x: (level_rank.get(x.level, 9), cat_rank.get(x.category, 9), x.msg_id_hex))
    return result
