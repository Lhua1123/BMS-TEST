"""
验证配置合并窗口
选项卡 1：CAN 信号回读协议（ID/位定义/DBC导入）
选项卡 2：故障期望值 / 额外回读
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from shared.style import COLORS
from bms_alarm_test.config.fault_mapping import FaultMapping
from bms_alarm_test.ui.can_readback_config_dialog import CanReadbackConfigDialog
from bms_alarm_test.ui.fault_verify_config_dialog import FaultVerifyConfigDialog

# 两个页签统一字号（避免全局 QTableWidget 样式把某一侧压小）
UNIFY_UI_PT = 13
UNIFY_TABLE_PT = 13
UNIFY_ROW_H = 36
CELL_PAD_X = 20  # 左右留白，避免“贴边吞字”

def unify_table_qss() -> str:
    """两个页签统一的表格/页签样式（网格线颜色随主题变化）"""
    return f"""
QTableWidget {{
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_TABLE_PT}pt;
    gridline-color: {COLORS['grid_line']};
}}
QTableWidget::item {{
    padding: 4px 6px;
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_TABLE_PT}pt;
}}
QHeaderView::section {{
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_TABLE_PT}pt;
    font-weight: bold;
    padding: 6px 4px;
}}
QPushButton {{
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_UI_PT}pt;
}}
QLabel {{
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_UI_PT}pt;
}}
QTabWidget::pane {{
    border: 1px solid {COLORS['grid_line']};
}}
QTabWidget::tab-bar {{
    alignment: left;
}}
QTabBar::tab {{
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_UI_PT}pt;
    padding: 8px 14px;
    min-width: 140px;
    max-width: 360px;
}}
QTabBar {{
    font-family: 'Microsoft YaHei';
    font-size: {UNIFY_UI_PT}pt;
}}
"""


def _text_width(fm: QFontMetrics, text: str) -> int:
    text = "" if text is None else str(text)
    try:
        if hasattr(fm, "horizontalAdvance"):
            return int(fm.horizontalAdvance(text))
        return int(fm.width(text))
    except Exception:
        return len(text) * 14


def _autofit_table_columns(table: QTableWidget) -> None:
    """按表头+单元格最长文字设列宽（13pt 字号下不吞字）"""
    if table is None:
        return
    table.setWordWrap(False)
    try:
        table.setTextElideMode(Qt.ElideNone)
    except Exception:
        pass
    table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

    h_fm = QFontMetrics(table.horizontalHeader().font())
    c_fm = QFontMetrics(table.font())
    col_count = table.columnCount()
    for col in range(col_count):
        width = _text_width(h_fm, table.horizontalHeaderItem(col).text() if table.horizontalHeaderItem(col) else "")
        for row in range(table.rowCount()):
            item = table.item(row, col)
            if item is None:
                continue
            width = max(width, _text_width(c_fm, item.text()))
        # 最小宽度，避免空列过窄导致视觉挤压
        width = max(width + CELL_PAD_X, 90)
        table.setColumnWidth(col, width)

    # 再与系统 contents 宽度取 max
    for col in range(col_count):
        try:
            table.resizeColumnToContents(col)
        except Exception:
            pass
    for col in range(col_count):
        cur = table.columnWidth(col)
        need = _text_width(h_fm, table.horizontalHeaderItem(col).text() if table.horizontalHeaderItem(col) else "")
        for row in range(table.rowCount()):
            item = table.item(row, col)
            if item is not None:
                need = max(need, _text_width(c_fm, item.text()))
        table.setColumnWidth(col, max(cur, need + CELL_PAD_X, 90))


def _unify_table(table: QTableWidget):
    if table is None:
        return
    font = QFont("Microsoft YaHei", UNIFY_TABLE_PT)
    table.setFont(font)
    header_font = QFont("Microsoft YaHei", UNIFY_TABLE_PT, QFont.Bold)
    table.horizontalHeader().setFont(header_font)
    table.verticalHeader().setDefaultSectionSize(UNIFY_ROW_H)
    old = table.styleSheet() or ""
    table.setStyleSheet(unify_table_qss() + old)
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            it = table.item(r, c)
            if it is not None:
                it.setFont(font)
    _autofit_table_columns(table)


class VerifyConfigDialog(QDialog):
    """一个窗口配置全部故障验证相关项"""

    def __init__(self, parent: Optional[QWidget] = None,
                 fault_mapping: Optional[FaultMapping] = None):
        super().__init__(parent)
        self.setWindowTitle("验证配置（回读协议 + 故障期望值）")
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self.resize(1280, 760)
        self.setFont(QFont("Microsoft YaHei", UNIFY_UI_PT))

        self.fault_mapping = fault_mapping

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.setStyleSheet(unify_table_qss())

        hint = QLabel(
            "左侧页签切换：① 信号怎么读（CAN ID/位/系数，可 DBC 导入）；"
            "② 每个故障码期望什么值、是否额外回读。改完在对应页点「保存」。"
        )
        hint.setWordWrap(True)
        hint.setFont(QFont("Microsoft YaHei", UNIFY_UI_PT))
        layout.addWidget(hint)

        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Microsoft YaHei", UNIFY_UI_PT))
        self.tabs.setDocumentMode(False)
        self.readback_panel = CanReadbackConfigDialog(self, embedded=True)
        self.fault_panel = FaultVerifyConfigDialog(self, fault_mapping=fault_mapping, embedded=True)
        self.tabs.addTab(self.readback_panel, "① 信号回读协议")
        self.tabs.addTab(self.fault_panel, "② 故障期望值")
        # 页签标题完整显示：不省略、可滚动，宽度按文字撑开
        try:
            self.tabs.tabBar().setExpanding(True)
            self.tabs.tabBar().setUsesScrollButtons(True)
            self.tabs.tabBar().setElideMode(Qt.ElideNone)
            self.tabs.tabBar().setDrawBase(True)
        except Exception:
            pass
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.btn_close = QPushButton("关闭窗口")
        self.btn_close.setMinimumHeight(38)
        self.btn_close.setFont(QFont("Microsoft YaHei", UNIFY_UI_PT))
        self.btn_close.clicked.connect(self.accept)
        bottom.addStretch()
        bottom.addWidget(self.btn_close)
        layout.addLayout(bottom)

        # 两个页签表格/按钮字号强制一致 + 列宽自适应
        self._apply_unified_fonts()
        self.tabs.currentChanged.connect(lambda _i: self._on_tab_changed())
        # 布局生效后再量一次列宽
        QTimer.singleShot(0, self._apply_unified_fonts)
        QTimer.singleShot(50, self._apply_unified_fonts)

    def _on_tab_changed(self):
        self._apply_unified_fonts()

    def _apply_unified_fonts(self):
        font = QFont("Microsoft YaHei", UNIFY_UI_PT)
        for panel in (self.readback_panel, self.fault_panel):
            if panel is None:
                continue
            panel.setFont(font)
            for child in panel.findChildren(QPushButton):
                child.setFont(font)
            for child in panel.findChildren(QLabel):
                child.setFont(font)
            table = getattr(panel, "table", None)
            _unify_table(table)
        self.tabs.setFont(font)
        try:
            bar = self.tabs.tabBar()
            for i in range(self.tabs.count()):
                bar.setTabToolTip(i, self.tabs.tabText(i))
            bar.setExpanding(True)
            bar.setElideMode(Qt.ElideNone)
            bar.updateGeometry()
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_unified_fonts)

