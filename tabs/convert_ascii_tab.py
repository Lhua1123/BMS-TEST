"""
进制转换Tab
二进制/八进制/十进制/十六进制/字符串 互转工具
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from shared.style import COLORS, FONTS


def bin_to_str(binary):
    binary = binary.replace(" ", "")
    if not binary:
        return ""
    result = ""
    for i in range(0, len(binary), 8):
        part = binary[i:i + 8]
        if part:
            result += chr(int(part, 2))
    return result


def str_to_bin(s):
    if not s:
        return ""
    return " ".join(format(ord(c), '08b') for c in s)


def oct_to_str(octal):
    octal_numbers = octal.split()
    result = ""
    for oct_number in octal_numbers:
        if oct_number:
            result += chr(int(oct_number, 8))
    return result


def str_to_oct(s):
    if not s:
        return ""
    return " ".join(format(ord(c), '03o') for c in s)


def dec_to_str(decimal):
    decimal_numbers = decimal.split()
    result = ""
    for number in decimal_numbers:
        if number:
            result += chr(int(number))
    return result


def str_to_dec(s):
    if not s:
        return ""
    return " ".join(str(ord(c)) for c in s)


def hex_to_str(hexadecimal):
    hexadecimal_numbers = hexadecimal.split()
    result = ""
    for hex_number in hexadecimal_numbers:
        if hex_number:
            result += chr(int(hex_number, 16))
    return result


def str_to_hex(s):
    if not s:
        return ""
    return " ".join(format(ord(c), '02x') for c in s)


class ConvertAsciiTab(QWidget):
    """进制转换Tab"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        tip = QLabel(
            "进制数据需要用空格隔开！\n"
            "例如：二进制输入 1010 1100，八进制输入 75 63，以此类推。\n"
            "输入对应进制的数据后，点击「一键转换」按钮获取转换结果。"
        )
        tip.setFont(QFont('Microsoft YaHei', 10))
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 10px; background-color: {COLORS['bg_panel']}; border-radius: 4px;")
        tip.setFixedHeight(120)
        layout.addWidget(tip)

        for label_text in ["二进制", "八进制", "十进制", "十六进制", "字符串"]:
            row = QHBoxLayout()
            label = QLabel(f"{label_text}：")
            label.setFont(QFont('Microsoft YaHei', 11))
            label.setFixedWidth(100)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(label)

            line_edit = QLineEdit()
            line_edit.setFont(QFont('Consolas', 12))
            line_edit.setMinimumHeight(40)
            line_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            line_edit.setTextMargins(8, 0, 0, 0)
            row.addWidget(line_edit)
            self.fields[label_text] = line_edit

            layout.addLayout(row)

        btn_layout = QHBoxLayout()
        convert_btn = QPushButton("一键转换")
        convert_btn.setMinimumHeight(44)
        convert_btn.clicked.connect(self.convert)
        btn_layout.addWidget(convert_btn)

        clear_btn = QPushButton("清空内容")
        clear_btn.setMinimumHeight(44)
        clear_btn.setStyleSheet(f"background-color: {COLORS['bg_panel']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']};")
        clear_btn.clicked.connect(self.clear_all)
        btn_layout.addWidget(clear_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def convert(self):
        bin_value = self.fields["二进制"].text()
        oct_value = self.fields["八进制"].text()
        dec_value = self.fields["十进制"].text()
        hex_value = self.fields["十六进制"].text()
        str_value = self.fields["字符串"].text()

        for field in self.fields.values():
            field.clear()

        try:
            if bin_value:
                result_str = bin_to_str(bin_value)
                self.fields["字符串"].setText(self.format_string_output(result_str))
                self.fields["八进制"].setText(str_to_oct(result_str))
                self.fields["十进制"].setText(str_to_dec(result_str))
                self.fields["十六进制"].setText(str_to_hex(result_str))
                self.fields["二进制"].setText(self.format_binary_output(bin_value))
            elif oct_value:
                result_str = oct_to_str(oct_value)
                self.fields["字符串"].setText(self.format_string_output(result_str))
                self.fields["二进制"].setText(self.format_binary_output(str_to_bin(result_str)))
                self.fields["十进制"].setText(str_to_dec(result_str))
                self.fields["十六进制"].setText(str_to_hex(result_str))
                self.fields["八进制"].setText(oct_value)
            elif dec_value:
                result_str = dec_to_str(dec_value)
                self.fields["字符串"].setText(self.format_string_output(result_str))
                self.fields["二进制"].setText(self.format_binary_output(str_to_bin(result_str)))
                self.fields["八进制"].setText(str_to_oct(result_str))
                self.fields["十六进制"].setText(str_to_hex(result_str))
                self.fields["十进制"].setText(dec_value)
            elif hex_value:
                result_str = hex_to_str(hex_value)
                self.fields["字符串"].setText(self.format_string_output(result_str))
                self.fields["二进制"].setText(self.format_binary_output(str_to_bin(result_str)))
                self.fields["八进制"].setText(str_to_oct(result_str))
                self.fields["十进制"].setText(str_to_dec(result_str))
                self.fields["十六进制"].setText(hex_value)
            elif str_value:
                self.fields["二进制"].setText(self.format_binary_output(str_to_bin(str_value)))
                self.fields["八进制"].setText(str_to_oct(str_value))
                self.fields["十进制"].setText(str_to_dec(str_value))
                self.fields["十六进制"].setText(str_to_hex(str_value))
                self.fields["字符串"].setText(str_value)
        except ValueError as e:
            self.fields["字符串"].setText(f"转换错误: {str(e)}")

    def format_binary_output(self, binary):
        binary = binary.replace(" ", "")
        return " ".join(binary[i:i+4] for i in range(0, len(binary), 4))

    def format_string_output(self, s):
        return "".join(char if not char.isspace() else f"空白字符(ASCII: {ord(char)})" for char in s)

    def clear_all(self):
        for field in self.fields.values():
            field.clear()
