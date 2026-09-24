"""协议核对数据模型"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CanFrame:
    timestamp: float
    arbitration_id: int
    data: bytes
    dlc: int = 0
    channel: Optional[int] = None
    is_extended: bool = True
    source: str = ""

    def __post_init__(self):
        if self.dlc <= 0:
            self.dlc = len(self.data)
        if self.data is None:
            self.data = b""

    @property
    def id_hex(self) -> str:
        return f"{self.arbitration_id:X}"

    @property
    def data_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data[: self.dlc])


@dataclass
class SignalTemplate:
    msg_id: int
    name: str
    start_bit: int = 0
    length: int = 8
    byte_order: str = "Intel"  # Intel / Motorola
    signed: bool = False
    factor: float = 1.0
    offset: float = 0.0
    unit: str = ""
    note: str = ""

    @property
    def msg_id_hex(self) -> str:
        return f"{self.msg_id:X}"


@dataclass
class MessageTemplate:
    msg_id: int
    name: str = ""
    expected_dlc: int = 8
    required: bool = True
    note: str = ""
    signals: List[SignalTemplate] = field(default_factory=list)

    @property
    def msg_id_hex(self) -> str:
        return f"{self.msg_id:X}"


@dataclass
class TemplateBook:
    messages: Dict[int, MessageTemplate] = field(default_factory=dict)
    source_path: str = ""

    def add_message(self, msg: MessageTemplate) -> None:
        self.messages[msg.msg_id] = msg

    def add_signal(self, sig: SignalTemplate) -> None:
        if sig.msg_id not in self.messages:
            self.messages[sig.msg_id] = MessageTemplate(
                msg_id=sig.msg_id, name="", expected_dlc=8, required=False
            )
        self.messages[sig.msg_id].signals.append(sig)

    @property
    def message_count(self) -> int:
        return len(self.messages)


@dataclass
class CheckIssue:
    level: str  # error / warn / info
    category: str  # unexpected_id / missing_id / dlc_mismatch / signal_decode
    msg_id_hex: str
    message: str
    detail: str = ""
    sample: str = ""


@dataclass
class CheckResult:
    frames_total: int = 0
    unique_ids: int = 0
    matched_frames: int = 0
    issues: List[CheckIssue] = field(default_factory=list)
    id_stats: Dict[int, dict] = field(default_factory=dict)
    frames: List[CanFrame] = field(default_factory=list)
    template: Optional[TemplateBook] = None

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warn")

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def summary_text(self) -> str:
        return (
            f"报文总数 {self.frames_total} | 唯一ID {self.unique_ids} | "
            f"匹配帧 {self.matched_frames} | 异常 {self.error_count} | "
            f"警告 {self.warn_count}"
        )
