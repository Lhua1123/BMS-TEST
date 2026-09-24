"""CAN 报文日志解析：Vector ASC/BLF，以及宽松 HEX/TXT"""

import logging
import os
import re
from typing import List, Optional

from protocol_check.models import CanFrame

logger = logging.getLogger(__name__)

# Vector ASC 数据行示例:
#   0.006058 2  18A2FFB1x       Rx   d 8 00 01 00 00 00 00 42 00  Length = ...
_ASC_DATA_RE = re.compile(
    r"^\s*(?P<ts>[\d.]+)\s+"
    r"(?P<ch>\d+|---)\s+"
    r"(?P<id>[0-9A-Fa-f]+)x?\s+"
    r"(?:Rx|Tx|RxRq|TxRq)\s+"
    r"(?:d|D|r|R)\s+"
    r"(?P<dlc>\d+)\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s*){0,8})",
    re.IGNORECASE,
)

# 宽松 HEX：  0x18A2F2F2 00 64 64 ... 或 18A2F2F2 00 64 ...
_HEX_LINE_RE = re.compile(
    r"(?:0x)?(?P<id>[0-9A-Fa-f]{3,8})\s*[:=,]?\s+(?P<data>(?:[0-9A-Fa-f]{2}[\s,]+){1,8}[0-9A-Fa-f]{2})",
    re.IGNORECASE,
)


def _parse_id(token: str) -> int:
    token = token.strip().lower()
    if token.endswith("x"):
        token = token[:-1]
    return int(token, 16)


def _parse_data(data_str: str, dlc: Optional[int] = None) -> bytes:
    parts = [p for p in re.split(r"[\s,]+", data_str.strip()) if p]
    raw = bytes(int(p, 16) & 0xFF for p in parts)
    if dlc is not None and 0 <= dlc <= 8:
        if len(raw) > dlc:
            raw = raw[:dlc]
        elif len(raw) < dlc:
            raw = raw + b"\x00" * (dlc - len(raw))
    return raw[:8]


def parse_asc_text(text: str, source: str = "") -> List[CanFrame]:
    frames: List[CanFrame] = []
    for line in text.splitlines():
        if "Status:" in line or line.strip().startswith("//") or line.strip().startswith("date "):
            continue
        m = _ASC_DATA_RE.match(line)
        if not m:
            continue
        try:
            ts = float(m.group("ts"))
            ch_raw = m.group("ch")
            channel = None if ch_raw == "---" else int(ch_raw)
            arb_id = _parse_id(m.group("id"))
            dlc = int(m.group("dlc"))
            data = _parse_data(m.group("data"), dlc)
            frames.append(
                CanFrame(
                    timestamp=ts,
                    arbitration_id=arb_id,
                    data=data,
                    dlc=dlc,
                    channel=channel,
                    source=source or "asc",
                )
            )
        except Exception as e:
            logger.debug(f"ASC 行解析失败: {line[:80]} ... {e}")
    return frames


def parse_hex_text(text: str, source: str = "txt") -> List[CanFrame]:
    frames: List[CanFrame] = []
    for idx, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        m = _HEX_LINE_RE.search(line)
        if not m:
            continue
        try:
            arb_id = _parse_id(m.group("id"))
            data = _parse_data(m.group("data"))
            frames.append(
                CanFrame(
                    timestamp=float(idx),
                    arbitration_id=arb_id,
                    data=data,
                    dlc=len(data),
                    source=source,
                )
            )
        except Exception as e:
            logger.debug(f"HEX 行解析失败: {line[:80]} ... {e}")
    return frames


def _load_with_python_can(path: str, fmt: str) -> List[CanFrame]:
    import can

    frames: List[CanFrame] = []
    if fmt == "blf":
        reader = can.BLFReader(path)
        iterable = reader
        closer = reader
    else:
        handle = open(path, "r", encoding="utf-8", errors="ignore")
        from can.io import ASCReader

        iterable = ASCReader(handle)
        closer = handle

    try:
        for msg in iterable:
            data = bytes(msg.data) if msg.data is not None else b""
            frames.append(
                CanFrame(
                    timestamp=float(getattr(msg, "timestamp", 0.0) or 0.0),
                    arbitration_id=int(msg.arbitration_id),
                    data=data,
                    dlc=int(getattr(msg, "dlc", len(data)) or len(data)),
                    is_extended=bool(getattr(msg, "is_extended_id", True)),
                    source=fmt,
                )
            )
    finally:
        try:
            closer.close()
        except Exception:
            pass
    return frames


def load_log_file(path: str, max_frames: Optional[int] = None) -> List[CanFrame]:
    """按扩展名加载 asc / blf / txt / hex 日志。"""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"日志文件不存在: {path}")

    ext = os.path.splitext(path)[1].lower()
    frames: List[CanFrame] = []

    # ASC 优先内置解析（Vector 格式稳定、大文件更快）；BLF 依赖 python-can
    if ext == ".asc":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        frames = parse_asc_text(text, source=os.path.basename(path))
        if not frames:
            try:
                frames = _load_with_python_can(path, "asc")
            except Exception as e:
                logger.warning(f"python-can 解析 ASC 失败: {e}")
    elif ext == ".blf":
        try:
            frames = _load_with_python_can(path, "blf")
        except Exception as e:
            logger.warning(f"python-can 解析 BLF 失败: {e}")
            raise RuntimeError(f"BLF 解析失败: {e}") from e
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        head = text[:2000]
        if "base hex" in head.lower() or _ASC_DATA_RE.search(head):
            frames = parse_asc_text(text, source=os.path.basename(path))
        else:
            frames = parse_hex_text(text, source=os.path.basename(path))

    if max_frames is not None and len(frames) > max_frames:
        frames = frames[:max_frames]
    return frames
