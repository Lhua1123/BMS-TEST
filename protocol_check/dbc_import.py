"""DBC 解析：生成可编辑的接收模板数据（默认做总线 ID 映射）"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from protocol_check.models import MessageTemplate, SignalTemplate, TemplateBook

logger = logging.getLogger(__name__)

_BO_RE = re.compile(r"^BO_\s+(\d+)\s+([^:]+):\s*(\d+)\s+(\S+)")
# SG_ Name [mux] : start|len@order sign (factor,offset) [min|max] "unit" receivers
_SG_RE = re.compile(
    r"SG_\s+(?P<name>\S+)\s*"
    r"(?P<mux>[mM]\d*\s+|m\s+|M\s+)?"
    r":\s*(?P<start>\d+)\s*\|\s*(?P<len>\d+)@(?P<order>\d)(?P<sign>[+-])\s*"
    r"\((?P<factor>[^,]+)\s*,\s*(?P<offset>[^)]*)\)\s*"
    r"\[(?P<min>[^|]*)\|(?P<max>[^\]]*)\]\s*"
    r"\"(?P<unit>[^\"]*)\""
)


def dbc_id_to_bus_id(dbc_id: int) -> int:
    """DBC 标准扩展帧文档 ID → 总线上常见 ID。

    常见情况：文档里带了 0x80 标志位（如 0x98xxxxxx），总线实际是 29-bit ID
    （如 0x18xxxxxx）。默认按 & 0x1FFFFFFF 映射，与实报对齐。
    """
    return dbc_id & 0x1FFFFFFF


def parse_dbc_file(path: str, map_id: bool = True) -> Tuple[TemplateBook, List[str]]:
    """解析 DBC，返回 (模板, 日志列表)。map_id=True 时 msg_id 使用总线 ID。"""
    notes: List[str] = []
    book = TemplateBook(source_path=path)
    try:
        text = open(path, "r", encoding="utf-8", errors="ignore").read()
    except Exception as e:
        raise RuntimeError(f"读取 DBC 失败: {e}") from e

    current: Optional[MessageTemplate] = None
    current_dbc_id: Optional[int] = None
    msg_count = 0
    sig_count = 0

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("BO_ "):
            m = _BO_RE.match(line)
            if not m:
                current = None
                continue
            dbc_id = int(m.group(1))
            name = m.group(2).strip()
            dlc = int(m.group(3))
            node = m.group(4).strip()
            bus_id = dbc_id_to_bus_id(dbc_id) if map_id else dbc_id
            note = f"DBC:{dbc_id:X}"
            if map_id and bus_id != dbc_id:
                note += f"→BUS:{bus_id:X}"
            if node:
                note += f" node={node}"
            current = MessageTemplate(
                msg_id=bus_id,
                name=name,
                expected_dlc=dlc if dlc > 0 else 8,
                required=False,
                note=note,
            )
            current_dbc_id = dbc_id
            # 同 bus_id 冲突时覆盖并提示
            if bus_id in book.messages:
                notes.append(f"ID 0x{bus_id:X} 重复，后者覆盖: {name}")
            book.add_message(current)
            msg_count += 1
        elif line.startswith("SG_") and current is not None:
            sm = _SG_RE.search(line)
            if not sm:
                continue
            try:
                start = int(sm.group("start"))
                length = int(sm.group("len"))
                order = int(sm.group("order"))
                sign = sm.group("sign")
                factor = float(sm.group("factor"))
                offset = float(sm.group("offset"))
            except Exception:
                continue
            # order: 1=Intel/little, 0=Motorola/big（Vector DBC 惯例）
            byte_order = "Motorola" if order == 0 else "Intel"
            unit = sm.group("unit") or ""
            sig = SignalTemplate(
                msg_id=current.msg_id,
                name=sm.group("name"),
                start_bit=start,
                length=length,
                byte_order=byte_order,
                signed=(sign == "-"),
                factor=factor,
                offset=offset,
                unit=unit,
                note="",
            )
            current.signals.append(sig)
            sig_count += 1

    notes.append(
        f"解析完成：报文 {msg_count}，信号 {sig_count}；"
        f"ID映射={'开(&0x1FFFFFFF)' if map_id else '关(原样)'}"
    )
    return book, notes


def merge_books(base: TemplateBook, other: TemplateBook, overwrite: bool = True) -> TemplateBook:
    """合并两个模板（以 msg_id 为键）。"""
    for msg in other.messages.values():
        if msg.msg_id in base.messages and not overwrite:
            continue
        base.messages[msg.msg_id] = msg
    return base
