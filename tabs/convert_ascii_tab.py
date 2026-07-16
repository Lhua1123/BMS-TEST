"""
进制转换Tab - 统一项目风格
支持二进制/八进制/十进制/十六进制/字符串互转
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QComboBox, QCheckBox, QLineEdit, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from convert_ascii.core.converter import ASCIIConverter
from shared.style import COLORS, FONTS


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
        gi = QVBoxLayout(grp_in)

        row = QHBoxLayout()
        row.addWidget(QLabel("输入类型:"))
        self.cb_input_type = QComboBox()
        self.cb_input_type.addItems(["智能检测", "二进制", "八进制",
                                      "十进制", "十六进制", "字符串"])
        self.cb_input_type.setToolTip("选择'智能检测'可自动识别输入的进制类型")
        row.addWidget(self.cb_input_type)
        row.addStretch()
        gi.addLayout(row)

        self.txt_input = QTextEdit()
        self.txt_input.setMaximumHeight(160)
        self.txt_input.setPlaceholderText(
            "输入需要转换的数据…\n"
            "支持格式：41 42 43, 0x41 0x42, 01000001, Hello, 65 66 67"
        )
        self.txt_input.setAcceptRichText(False)
        self.txt_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                padding: 8px;
                font-family: {FONTS['mono'][0]};
                font-size: {FONTS['mono'][1]}pt;
            }}
        """)
        gi.addWidget(self.txt_input)
        layout.addWidget(grp_in)

        # 选项区
        grp_opt = QGroupBox("转换选项")
        go = QHBoxLayout(grp_opt)

        self.chk_auto = QCheckBox("实时转换")
        self.chk_auto.setChecked(True)
        go.addWidget(self.chk_auto)

        self.chk_group4 = QCheckBox("二进制4位分组")
        self.chk_group4.setChecked(True)
        go.addWidget(self.chk_group4)

        self.chk_uppercase = QCheckBox("十六进制大写")
        self.chk_uppercase.setChecked(True)
        go.addWidget(self.chk_uppercase)

        go.addStretch()

        self.btn_convert = QPushButton("🔄 转换")
        self.btn_convert.setMinimumHeight(42)
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        go.addWidget(self.btn_convert)

        self.btn_clear_all = QPushButton("🗑 清空")
        self.btn_clear_all.setMinimumHeight(42)
        self.btn_clear_all.setCursor(Qt.PointingHandCursor)
        go.addWidget(self.btn_clear_all)

        layout.addWidget(grp_opt)

        # 输出区
        grp_out = QGroupBox("转换结果")
        gout = QVBoxLayout(grp_out)

        outputs = [
            ("ascii_output", "ASCII字符串"),
            ("hex_output", "十六进制"),
            ("dec_output", "十进制"),
            ("oct_output", "八进制"),
            ("bin_output", "二进制"),
        ]
        for name, label in outputs:
            row_out = QHBoxLayout()
            lbl = QLabel(label + " :")
            lbl.setFixedWidth(100)
            lbl.setFont(QFont(FONTS['heading'][0], FONTS['heading'][1], QFont.Bold))
            row_out.addWidget(lbl)

            value = QLineEdit()
            value.setReadOnly(True)
            value.setFont(QFont(FONTS['mono'][0], FONTS['mono'][1]))
            value.setStyleSheet(f"background-color: {COLORS['bg_input']}; border: 1px solid {COLORS['border']}; padding: 6px;")
            row_out.addWidget(value, 1)

            copy_btn = QPushButton("复制")
            copy_btn.setMaximumWidth(80)
            copy_btn.setMinimumHeight(36)
            copy_btn.setCursor(Qt.PointingHandCursor)
            row_out.addWidget(copy_btn)

            gout.addLayout(row_out)
            self._output_widgets[name] = (value, copy_btn)

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
            value, _ = self._output_widgets[name]
            value.setText(text)

    def clear_outputs(self):
        for value, _ in self._output_widgets.values():
            value.clear()

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
