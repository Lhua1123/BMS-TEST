"""
进制转换Tab - 基于 Convert_ASCII_V1.1 BasicTab
支持二进制/八进制/十进制/十六进制/字符串互转
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QComboBox, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from convert_ascii.core.converter import ASCIIConverter
from convert_ascii.gui.styles import (
    FONT_SIZE, FONT_TEXTEDIT, STYLE_GROUP, STYLE_BTN_PRIMARY,
    STYLE_BTN_DANGER, STYLE_BTN_COPY, STYLE_OUTPUT_LABEL,
    CollapsibleOutput
)


class ConvertAsciiTab(QWidget):
    """进制转换标签页"""
    convert_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.converter = ASCIIConverter()
        self._output_widgets = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 输入区
        grp_in = QGroupBox("输入数据")
        grp_in.setStyleSheet(STYLE_GROUP)
        gi = QVBoxLayout(grp_in)

        row = QHBoxLayout()
        row.addWidget(QLabel("输入类型:"))
        self.cb_input_type = QComboBox()
        self.cb_input_type.setStyleSheet(f"font-size: {FONT_SIZE}px; min-height: 36px;")
        self.cb_input_type.addItems(["智能检测", "二进制", "八进制",
                                      "十进制", "十六进制", "字符串"])
        self.cb_input_type.setToolTip("选择'智能检测'可自动识别输入的进制类型")
        row.addWidget(self.cb_input_type)
        row.addStretch()
        gi.addLayout(row)

        self.txt_input = QTextEdit()
        self.txt_input.setMaximumHeight(160)
        self.txt_input.setStyleSheet(f"font-size: {FONT_TEXTEDIT}px; padding: 6px;")
        self.txt_input.setPlaceholderText(
            "输入需要转换的数据…\n"
            "支持格式：41 42 43, 0x41 0x42, 01000001, Hello, 65 66 67"
        )
        self.txt_input.setAcceptRichText(False)
        gi.addWidget(self.txt_input)
        layout.addWidget(grp_in)

        # 选项区
        grp_opt = QGroupBox("转换选项")
        grp_opt.setStyleSheet(STYLE_GROUP)
        go = QHBoxLayout(grp_opt)

        self.chk_auto = QCheckBox("实时转换")
        self.chk_auto.setStyleSheet(f"font-size: {FONT_SIZE}px;")
        self.chk_auto.setChecked(True)
        go.addWidget(self.chk_auto)

        self.chk_group4 = QCheckBox("二进制4位分组")
        self.chk_group4.setStyleSheet(f"font-size: {FONT_SIZE}px;")
        self.chk_group4.setChecked(True)
        go.addWidget(self.chk_group4)

        self.chk_uppercase = QCheckBox("十六进制大写")
        self.chk_uppercase.setStyleSheet(f"font-size: {FONT_SIZE}px;")
        self.chk_uppercase.setChecked(True)
        go.addWidget(self.chk_uppercase)

        go.addStretch()

        self.btn_convert = QPushButton("🔄 转换")
        self.btn_convert.setStyleSheet(STYLE_BTN_PRIMARY)
        self.btn_convert.setMinimumHeight(42)
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        go.addWidget(self.btn_convert)

        self.btn_clear_all = QPushButton("🗑 清空")
        self.btn_clear_all.setStyleSheet(STYLE_BTN_DANGER)
        self.btn_clear_all.setMinimumHeight(42)
        self.btn_clear_all.setCursor(Qt.PointingHandCursor)
        go.addWidget(self.btn_clear_all)

        layout.addWidget(grp_opt)

        # 输出区
        grp_out = QGroupBox("转换结果")
        grp_out.setStyleSheet(STYLE_GROUP)
        gout = QVBoxLayout(grp_out)

        outputs = [
            ("ascii_output", "ASCII字符串"),
            ("hex_output", "十六进制"),
            ("dec_output", "十进制"),
            ("oct_output", "八进制"),
            ("bin_output", "二进制"),
        ]
        for name, label in outputs:
            co = CollapsibleOutput(label + " :")
            gout.addWidget(co)
            self._output_widgets[name] = co

        layout.addWidget(grp_out, 1)

        # 信号连接
        self.btn_convert.clicked.connect(self.convert)
        self.btn_clear_all.clicked.connect(self.clear_all)
        self.txt_input.textChanged.connect(self._on_input_changed)

    def _on_input_changed(self):
        if self.chk_auto.isChecked():
            self.convert()

    def get_input_text(self):
        return self.txt_input.toPlainText().strip()

    def get_input_type(self):
        return self.cb_input_type.currentText()

    def is_auto_convert(self):
        return self.chk_auto.isChecked()

    def is_group4(self):
        return self.chk_group4.isChecked()

    def is_uppercase(self):
        return self.chk_uppercase.isChecked()

    def set_output(self, name, text):
        if name in self._output_widgets:
            self._output_widgets[name].set_value(text)

    def clear_outputs(self):
        for w in self._output_widgets.values():
            w.clear_value()

    def clear_input(self):
        self.txt_input.clear()

    def convert(self):
        text = self.txt_input.toPlainText().strip()
        if not text:
            self.clear_outputs()
            return

        raw_type = self.cb_input_type.currentText()
        if raw_type == "智能检测":
            detected = self.converter.detect_type(text)
            if not detected:
                return
            input_type = detected
        else:
            input_type = raw_type

        try:
            if input_type == "二进制":
                result_str, ascii_codes = self.converter.binary_to_str(text)
            elif input_type == "八进制":
                result_str, ascii_codes = self.converter.octal_to_str(text)
            elif input_type == "十进制":
                result_str, ascii_codes = self.converter.decimal_to_str(text)
            elif input_type == "十六进制":
                result_str, ascii_codes = self.converter.hex_to_str(text)
            else:
                result_str = text
                ascii_codes = [ord(c) for c in text]

            all_fmts = self.converter.str_to_all(result_str)

            bin_val = all_fmts['binary']
            if self.chk_group4.isChecked():
                bin_val = self.converter.format_output(bin_val, 'binary')

            hex_val = all_fmts['hex']
            if self.chk_uppercase.isChecked():
                hex_val = hex_val.upper()

            self.set_output('ascii_output', result_str)
            self.set_output('hex_output', hex_val)
            self.set_output('dec_output', all_fmts['decimal'])
            self.set_output('oct_output', all_fmts['octal'])
            self.set_output('bin_output', bin_val)

        except ValueError as e:
            self.set_output('ascii_output', f"转换错误: {str(e)}")
        except Exception as e:
            self.set_output('ascii_output', f"转换出错: {str(e)}")

    def clear_all(self):
        self.clear_input()
        self.clear_outputs()

    def clear_input(self):
        self.txt_input.clear()

    def clear_outputs(self):
        for w in self._output_widgets.values():
            w.clear_value()
