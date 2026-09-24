"""
CAN 回读协议配置（故障验证用）
类似 485 协议配置：可在程序中编辑，也可从 DBC 导入，避免验证逻辑写死在代码里。
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CONFIG_DIR / "can_readback_config.json"


def _hex_to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    if isinstance(v, int):
        return v
    s = str(v).strip()
    try:
        return int(s, 0)
    except ValueError:
        return default


def default_config() -> Dict[str, Any]:
    """默认回读协议（与当前程序内既有约定一致，可再改）"""
    return {
        "version": 1,
        "inject": {
            "message_name": "DAPP_FaultSet",
            "can_id": "0x18D1FFDF",
            "is_extended": True,
            "addr_byte": 0,
            "code_byte": 1,
            "flag_byte": 7,
            "inject_flag": 3,
            "clear_flag": 2,
        },
        "monitored_ids": [
            "0x18B1FFA1",
            "0x18BBFFA1",
            "0x18A3FFA1",
            "0x18B8FFB1",
            "0x18A2FFB1",
            "0x18FFA0F4",
            "0x18D2FFDF",
            "0x18A3F100",
            "0x18A5F100",
            "0x18B2F100",
            "0x18B3F100",
            "0x18B4F100",
        ],
        # 角色 → signals 中的键；验证器按角色找配置
        "roles": {
            "inner_sys_fail_sta": "SysFailSta",
            "inner_err_tab": "ErrTab",
            "outer_sys_fail_sta": "OuterSysFailSta",
            "outer_warning": "OuterWarning",
        },
        # 信号定义：可增删改；name 支持 {idx} 占位（簇序号）
        "signals": {
            "SysFailSta": {
                "signal_name": "BMS_SysFailSta",
                "message_name": "",
                "can_id": "0x18B1FFA1",
                "is_extended": True,
                "byte_order": "big_endian",
                "start_bit": 7,
                "length": 8,
                "factor": 1.0,
                "offset": 0.0,
                "channel_role": "inner",
                "source": "default",
                "comment": "对内系统失败状态",
            },
            "ErrTab": {
                "signal_name": "BMS_ErrTab",
                "message_name": "",
                "can_id": "0x18B1FFA1",
                "is_extended": True,
                "byte_order": "big_endian",
                "start_bit": 23,
                "length": 8,
                "factor": 1.0,
                "offset": 0.0,
                "channel_role": "inner",
                "source": "default",
                "comment": "对内故障码表（期望=故障码）",
            },
            "OuterSysFailSta": {
                "signal_name": "BMS_SysFailSta",
                "message_name": "BMS_Msg01",
                "can_id": "0x18A3F100",
                "is_extended": True,
                "byte_order": "big_endian",
                "start_bit": 7,
                "length": 8,
                "factor": 1.0,
                "offset": 0.0,
                "channel_role": "outer",
                "source": "default",
                "comment": "对外组最大报警等级",
            },
            "OuterWarning": {
                "signal_name": "BMS_NBCMU{idx}_Warning",
                "message_name": "BMS_Msg15",
                "can_id": "0x18B2F100",
                "is_extended": True,
                "byte_order": "big_endian",
                "start_bit": 7,
                "length": 8,
                "factor": 1.0,
                "offset": 0.0,
                "channel_role": "outer",
                "source": "default",
                "comment": "对外Warning汇总，{idx}=簇序号",
            },
        },
        # Excel/故障表 specific 信号名 → 覆盖定义（可为空，空则仍走 DBC 名解码）
        "overrides": {},
    }


def extract_bits(
    data: bytes,
    start_bit: int,
    length: int,
    byte_order: str = "big_endian",
    signed: bool = False,
) -> int:
    """DBC 风格位提取（与 CAN 解析页一致：大端 start=MSB 锯齿位号）"""
    if length <= 0 or not data:
        return 0
    length = min(length, 64)
    bits: List[int] = []
    if byte_order == "little_endian":
        positions = []
        for i in range(length):
            pos = start_bit + i
            positions.append((pos // 8, pos % 8))
    else:
        seq_start = 8 * (start_bit // 8) + (7 - (start_bit % 8))
        positions = []
        for i in range(length):
            pos = seq_start + i
            positions.append((pos // 8, 7 - (pos % 8)))

    for byte_idx, bit_in_byte in positions:
        if byte_idx >= len(data):
            bits.append(0)
        else:
            bits.append((data[byte_idx] >> bit_in_byte) & 1)

    raw = 0
    if byte_order == "little_endian":
        for i, b in enumerate(bits):
            raw |= (b << i)
    else:
        for b in bits:
            raw = (raw << 1) | b
    if signed and (raw & (1 << (length - 1))):
        raw -= 1 << length
    return raw


class CanReadbackConfig:
    """故障回读协议配置管理器"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else CONFIG_PATH
        self.data: Dict[str, Any] = default_config()
        self.load()

    def load(self) -> bool:
        if not self.path.exists():
            self.data = default_config()
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            base = default_config()
            if isinstance(loaded, dict):
                base.update({k: loaded[k] for k in loaded if k in base})
                if isinstance(loaded.get("signals"), dict):
                    base["signals"].update(loaded["signals"])
                if isinstance(loaded.get("overrides"), dict):
                    base["overrides"].update(loaded["overrides"])
                if isinstance(loaded.get("roles"), dict):
                    base["roles"].update(loaded["roles"])
                if isinstance(loaded.get("inject"), dict):
                    base["inject"].update(loaded["inject"])
                if isinstance(loaded.get("monitored_ids"), list):
                    base["monitored_ids"] = loaded["monitored_ids"]
            self.data = base
            logger.info(f"已加载 CAN 回读配置: {self.path}")
            return True
        except Exception as e:
            logger.error(f"加载 CAN 回读配置失败: {e}")
            self.data = default_config()
            return False

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            logger.info(f"已保存 CAN 回读配置: {self.path}")
            return True
        except Exception as e:
            logger.error(f"保存 CAN 回读配置失败: {e}")
            return False

    def reset_default(self) -> None:
        self.data = default_config()

    # ---------- 查询 ----------

    @property
    def inject(self) -> Dict[str, Any]:
        return self.data.get("inject", {})

    @property
    def signals(self) -> Dict[str, Dict[str, Any]]:
        return self.data.get("signals", {})

    @property
    def overrides(self) -> Dict[str, Dict[str, Any]]:
        return self.data.get("overrides", {})

    @property
    def roles(self) -> Dict[str, str]:
        return self.data.get("roles", {})

    @property
    def monitored_ids(self) -> List[int]:
        return [_hex_to_int(x) for x in self.data.get("monitored_ids", [])]

    def get_role_signal(self, role: str, idx: Optional[Union[int, str]] = None) -> Optional[Dict[str, Any]]:
        key = self.roles.get(role)
        if not key:
            return None
        return self.get_signal(key, idx=idx)

    def get_signal(self, key: str, idx: Optional[Union[int, str]] = None) -> Optional[Dict[str, Any]]:
        # overrides 优先（Excel specific 名）
        if key in self.overrides:
            spec = deepcopy(self.overrides[key])
        elif key in self.signals:
            spec = deepcopy(self.signals[key])
        else:
            # 模糊：overrides 中带 {idx} 模板
            spec = None
            for ov_key, ov in self.overrides.items():
                if "{idx}" in ov_key and self._match_idx_key(ov_key, key):
                    spec = deepcopy(ov)
                    break
            if spec is None:
                return None
        if idx is not None:
            for field in ("signal_name", "can_id", "message_name"):
                if field in spec and isinstance(spec[field], str):
                    spec[field] = spec[field].replace("{idx}", str(idx))
        return spec

    @staticmethod
    def _match_idx_key(pattern: str, name: str) -> bool:
        rx = "^" + re.escape(pattern).replace(r"\{idx\}", r"(\d+)") + "$"
        return re.match(rx, name) is not None

    def channel_for_role(self, role: str, default: int = 1) -> int:
        """角色 → 逻辑通道号（inner/outer 由 settings 决定，这里只标角色）"""
        spec = self.get_role_signal(role)
        if not spec:
            return default
        return default

    def resolve_spec(
        self,
        signal_name: Optional[str] = None,
        role: Optional[str] = None,
        idx: Optional[Union[int, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if role:
            spec = self.get_role_signal(role, idx=idx)
            if spec:
                return spec
        if signal_name:
            return self.get_signal(signal_name, idx=idx)
        return None

    def physical_from_frame(self, spec: Dict[str, Any], data: bytes) -> Optional[float]:
        raw = extract_bits(
            data,
            int(spec.get("start_bit", 0)),
            int(spec.get("length", 8)),
            spec.get("byte_order", "big_endian"),
            bool(spec.get("is_signed", False)),
        )
        factor = float(spec.get("factor", 1.0) or 1.0)
        offset = float(spec.get("offset", 0.0) or 0.0)
        return raw * factor + offset

    def parse_can_id(self, spec: Dict[str, Any], idx: Optional[Union[int, str]] = None) -> int:
        cid = spec.get("can_id", 0)
        if isinstance(cid, str) and idx is not None:
            cid = cid.replace("{idx}", str(idx))
        return _hex_to_int(cid)

    # ---------- DBC 导入 ----------

    def import_from_dbc(
        self,
        dbc_path: str,
        selected: Optional[List[Tuple[str, str]]] = None,
        channel_role: str = "inner",
    ) -> int:
        """
        从 DBC 导入信号定义。
        selected: [(message_name, signal_name), ...]；为空则导入全部（可能很多）。
        返回导入条数。
        """
        import cantools

        path = Path(dbc_path)
        if not path.exists():
            raise FileNotFoundError(f"DBC 不存在: {dbc_path}")

        content = None
        for enc in ("utf-8", "gbk", "gb2312", "iso-8859-1"):
            try:
                content = path.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            raise ValueError("无法读取 DBC 编码")

        # 复用重名处理
        try:
            from convert_ascii.bms.bms_formatter import BMSFormatter
            content = BMSFormatter()._resolve_duplicate_signals(content)
        except Exception:
            pass

        db = cantools.database.load_string(content)
        # load_string 返回 can.Database | diagnostics.Database，用 getattr 兼容两者的类型差异
        messages = getattr(db, "messages", [])
        msg_by_name = {m.name: m for m in messages}

        count = 0
        pairs = selected
        if not pairs:
            pairs = [(m.name, s.name) for m in messages for s in m.signals]

        for msg_name, sig_name in pairs:
            msg = msg_by_name.get(msg_name)
            if not msg:
                continue
            try:
                sig = msg.get_signal_by_name(sig_name)
            except KeyError:
                continue
            key = sig_name
            # 同名不同报文时，用报文名_信号名
            if key in self.data["signals"] and self.data["signals"][key].get("message_name") not in ("", msg_name):
                key = f"{msg_name}_{sig_name}"
            self.data["signals"][key] = {
                "signal_name": sig_name,
                "message_name": msg_name,
                "can_id": f"0x{msg.frame_id:08X}",
                "is_extended": msg.is_extended_frame if hasattr(msg, "is_extended_frame") else True,
                "byte_order": sig.byte_order,
                "start_bit": sig.start,
                "length": sig.length,
                "factor": sig.scale if sig.scale is not None else 1.0,
                "offset": sig.offset if sig.offset is not None else 0.0,
                "is_signed": bool(sig.is_signed),
                "channel_role": channel_role,
                "source": "dbc",
                "comment": (sig.comment or "")[:80],
            }
            count += 1
        logger.info(f"从 DBC 导入 {count} 个信号: {path.name}")
        return count

    def list_signal_keys(self) -> List[str]:
        keys = set(self.signals.keys()) | set(self.overrides.keys())
        return sorted(keys)


_global_readback: Optional[CanReadbackConfig] = None


def get_readback_config() -> CanReadbackConfig:
    global _global_readback
    if _global_readback is None:
        _global_readback = CanReadbackConfig()
    return _global_readback


def set_readback_config(cfg: CanReadbackConfig) -> None:
    global _global_readback
    _global_readback = cfg
