"""CAN 协议核对模块：Excel 接收模板 + 报文日志解析 + ID/DLC/信号校验"""

from protocol_check.models import (
    CanFrame,
    CheckIssue,
    CheckResult,
    MessageTemplate,
    SignalTemplate,
    TemplateBook,
)
from protocol_check.checker import verify_frames
from protocol_check.excel_template import load_template_excel, save_template_excel, build_sample_template
from protocol_check.log_parser import load_log_file, parse_hex_text

__all__ = [
    "CanFrame",
    "CheckIssue",
    "CheckResult",
    "MessageTemplate",
    "SignalTemplate",
    "TemplateBook",
    "verify_frames",
    "load_template_excel",
    "save_template_excel",
    "build_sample_template",
    "load_log_file",
    "parse_hex_text",
]
