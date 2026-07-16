from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

import pyperclip


# ============================================================
# 字体大小
# ============================================================

FONT_SIZE = 20
FONT_MONO = 18
FONT_SMALL = 16
FONT_TITLE = 18
FONT_INPUT = 18
FONT_TEXTEDIT = 17
FONT_OUTPUT = 22
FONT_BTN = 18
FONT_BTN_SMALL = 16
FONT_TAB = 18

# ============================================================
# 按钮样式
# ============================================================

STYLE_BTN_PRIMARY = (
    "QPushButton { background-color: #3498db; color: white; border: none; "
    "border-radius: 8px; padding: 12px 30px; font-size: 18px; font-weight: bold; }"
    "QPushButton:hover { background-color: #2980b9; }"
    "QPushButton:pressed { background-color: #1c6ea4; }"
)
STYLE_BTN_SUCCESS = (
    "QPushButton { background-color: #27ae60; color: white; border: none; "
    "border-radius: 8px; padding: 12px 30px; font-size: 18px; font-weight: bold; }"
    "QPushButton:hover { background-color: #219a52; }"
)
STYLE_BTN_DANGER = (
    "QPushButton { background-color: #e74c3c; color: white; border: none; "
    "border-radius: 8px; padding: 12px 30px; font-size: 18px; font-weight: bold; }"
    "QPushButton:hover { background-color: #c0392b; }"
)
STYLE_BTN_COPY = (
    "QPushButton { background-color: #95a5a6; color: white; border: none; "
    "border-radius: 6px; padding: 8px 18px; font-size: 16px; }"
    "QPushButton:hover { background-color: #7f8c8d; }"
)

# ============================================================
# 输出标签样式
# ============================================================

STYLE_OUTPUT_LABEL = (
    "QLabel { background-color: #f4f6f8; border: 2px solid #d0d4d8; "
    "border-radius: 6px; padding: 12px 16px; font-family: Consolas, monospace; "
    "font-size: 22px; min-height: 36px; }"
)

# ============================================================
# 分组框样式
# ============================================================

STYLE_GROUP = (
    "QGroupBox { font-weight: bold; font-size: 17px; border: 2px solid #d0d4d8; "
    "border-radius: 10px; margin-top: 16px; padding-top: 22px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 14px; "
    "padding: 0 12px; }"
)

# ============================================================
# 提示框样式
# ============================================================

STYLE_HINT_BMS = (
    "background-color: #fff8e1; border: 1px solid #ffe082; "
    "border-radius: 8px; padding: 12px; color: #6d4c00;"
)
STYLE_HINT_BATCH = (
    "background-color: #e3f2fd; border: 1px solid #90caf9; "
    "border-radius: 8px; padding: 12px; color: #0d47a1;"
)


# ============================================================
# 辅助函数
# ============================================================

def make_copy_button(text="复制", style=STYLE_BTN_COPY):
    btn = QPushButton(text)
    btn.setStyleSheet(style)
    btn.setMaximumWidth(100)
    btn.setMinimumHeight(40)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


# ============================================================
# 可折叠的输出区域组件
# ============================================================

class CollapsibleOutput(QWidget):
    """带复制按钮的大字体输出条目"""
    def __init__(self, label_text, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)

        self.label = QLabel(label_text)
        self.label.setMinimumWidth(140)
        self.label.setStyleSheet(f"font-weight: bold; color: #444; font-size: {FONT_SIZE}px;")
        self._layout.addWidget(self.label)

        self.value = QLabel()
        self.value.setWordWrap(True)
        self.value.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.value.setStyleSheet(STYLE_OUTPUT_LABEL)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.value.setMinimumHeight(44)
        self.value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout.addWidget(self.value, 1)

        self.copy_btn = make_copy_button()
        self.copy_btn.clicked.connect(self._on_copy)
        self._layout.addWidget(self.copy_btn)

    def _on_copy(self):
        text = self.value.text()
        if text:
            pyperclip.copy(text)
            self._flash_copy_feedback()

    def _flash_copy_feedback(self):
        self.copy_btn.setText("✓")
        self.copy_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; "
            "border: none; border-radius: 6px; padding: 6px 16px; font-size: 14px; }"
        )
        QTimer.singleShot(800, self._reset_copy_btn)

    def _reset_copy_btn(self):
        self.copy_btn.setText("复制")
        self.copy_btn.setStyleSheet(STYLE_BTN_COPY)

    def set_value(self, text):
        self.value.setText(text)

    def clear_value(self):
        self.value.clear()
