"""协议核对共用 UI 常量与无状态控件工厂

协议核对 Tab 与「编辑模板」弹窗共用这套字号、表格排版和主题 QSS，
单独成模块避免两者互相 import。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)

from bms_alarm_test.ui.panel_style import LeftAlignDelegate, btn_neutral
from shared.style import COLORS, themed_qss

# ── 全 Tab 统一字体标尺（与 main.py 一致：Microsoft YaHei 10pt）──
# 正文/按钮/表体/表头 同为 10pt，仅用加粗区分层级；提示用 9pt。
PT_BODY = 10
PT_SMALL = 9
FONT_FAMILY = "Microsoft YaHei"
FONT_MONO_FAMILY = "Consolas"

FONT_BODY = QFont(FONT_FAMILY, PT_BODY)
FONT_BODY_BOLD = QFont(FONT_FAMILY, PT_BODY, QFont.Bold)
FONT_MONO = QFont(FONT_MONO_FAMILY, PT_BODY)
FONT_MONO_BOLD = QFont(FONT_MONO_FAMILY, PT_BODY, QFont.Bold)
FONT_SMALL = QFont(FONT_FAMILY, PT_SMALL)

# 核对结果行的等级（error / warn / ok）存在单元格的这个角色里，切换主题时用来重新上色
LEVEL_ROLE = Qt.UserRole + 37


# 字号只写 pt，避免 px/pt 混用导致忽大忽小
def common_qss() -> str:
    return f"""
QGroupBox {{
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    font-weight: bold;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    margin-top: 16px;
    padding: 6px;
    background: {COLORS['bg_panel']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {COLORS['accent']};
    background: {COLORS['bg_dark']};
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    font-weight: bold;
}}
QLabel {{
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    background: transparent;
    padding: 0;
}}
QLabel#hint, QLabel#status {{
    color: {COLORS['text_dim']};
    font-family: '{FONT_FAMILY}';
    font-size: {PT_SMALL}pt;
    font-weight: normal;
    padding: 1px 0;
}}
QLabel#path {{
    color: {COLORS['text']};
    font-family: '{FONT_FAMILY}';
    font-size: {PT_SMALL}pt;
    font-weight: normal;
    background: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 3px 6px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    min-height: 26px;
    max-height: 28px;
    padding: 2px 6px;
    background: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QCheckBox {{
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    spacing: 6px;
}}
QTableWidget {{
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background: {COLORS['bg_panel']};
    alternate-background-color: {COLORS['row_even']};
    selection-background-color: {COLORS['selection']};
    selection-color: {COLORS['text']};
}}
QTableWidget::item {{
    padding: 6px 10px;
}}
QHeaderView::section {{
    background: {COLORS['header_bg']};
    color: {COLORS['text']};
    padding: 6px 10px;
    border: none;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['accent']};
    font-family: '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    font-weight: bold;
    text-align: center;
}}
QTextEdit {{
    font-family: '{FONT_MONO_FAMILY}', '{FONT_FAMILY}';
    font-size: {PT_BODY}pt;
    background: {COLORS['bg_panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 4px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
"""


def btn(text: str, style=btn_neutral, height: int = 30) -> QPushButton:
    """style 是返回样式串的函数（如 btn_primary），切换主题时会重新生成"""
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(FONT_BODY)
    themed_qss(b, lambda: style() + f"font-family: '{FONT_FAMILY}'; font-size: {PT_BODY}pt;")
    b.setFixedHeight(height)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return b


def make_item(text: str, align=Qt.AlignCenter, mono: bool = False, bold: bool = False):
    """统一表格单元格：10pt 字体 + 对齐 + 截断提示。"""
    item = QTableWidgetItem("" if text is None else str(text))
    if mono:
        item.setFont(FONT_MONO_BOLD if bold else FONT_MONO)
    else:
        item.setFont(FONT_BODY_BOLD if bold else FONT_BODY)
    item.setTextAlignment(int(align))
    full = item.text()
    if full:
        item.setToolTip(full)
    return item


def section_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setFont(FONT_BODY_BOLD)
    themed_qss(lab, lambda: (
        f"color: {COLORS['accent']}; background: transparent; padding: 2px 0;"
        f"font-family: '{FONT_FAMILY}'; font-size: {PT_BODY}pt; font-weight: bold;"
    ))
    return lab


def apply_table_font(table: QTableWidget):
    """表体与表头同字号 10pt，仅表头加粗。"""
    table.setFont(FONT_BODY)
    hh = table.horizontalHeader()
    hh.setFont(FONT_BODY_BOLD)
    hh.setDefaultAlignment(Qt.AlignCenter)
    table.verticalHeader().setDefaultSectionSize(28)
    hh.setMinimumHeight(30)


def style_table(table: QTableWidget, min_h: int = 120):
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setMinimumHeight(min_h)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(False)
    apply_table_font(table)


def hex_col_width(texts, font: QFont, minimum: int = 96) -> int:
    fm = QFontMetrics(font)
    w = minimum
    for t in texts:
        if not t:
            continue
        w = max(w, fm.horizontalAdvance(str(t)) + 22)
    return w


class _LeftAlignWithBg(LeftAlignDelegate.get()):
    """共享 LeftAlignDelegate + 补画单元格底色。

    共享委托只画文字不画背景，会吃掉 item.setBackground()——核对结果要按
    error/warn 整行着色，所以这里补上。没有底色时行为与共享委托完全一致。
    """

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        super().paint(painter, option, index)


def align_table(table: QTableWidget, left_cols=()):
    """文本列左对齐——与 report_panel / fault_test_panel 同一套做法。

    三件事缺一不可（见 report_panel.create_report_table 的注释）：
      1. 表头走 TextAlignmentRole，否则表头居中、内容靠左，对不齐；
      2. 表体用委托强制绘制，不依赖 setTextAlignment（部分环境 QSS/主题会冲掉）；
      3. 表头/表体内缩统一 10px，与委托的 adjusted(10,0,-8,0) 贴齐。

    left_cols 之外的列保持居中（ID/DLC/次数这类短值）。
    """
    left = set(left_cols)
    header = table.horizontalHeader()
    for c in range(table.columnCount()):
        align = int(Qt.AlignLeft | Qt.AlignVCenter) if c in left else int(Qt.AlignCenter)
        try:
            header.model().setHeaderData(c, Qt.Horizontal, align, Qt.TextAlignmentRole)
        except Exception:
            pass
        it = table.horizontalHeaderItem(c)
        if it is not None:
            it.setTextAlignment(align)
    for col in sorted(left):
        table.setItemDelegateForColumn(col, _LeftAlignWithBg(table))


def layout_msg_table(table: QTableWidget):
    """报文表：ID 列固定宽度防截断，名称/备注可拖，短列居中。"""
    h = table.horizontalHeader()
    h.setMinimumSectionSize(48)
    h.setSectionResizeMode(QHeaderView.Interactive)
    table.setColumnWidth(0, 104)
    table.setColumnWidth(1, 96)
    table.setColumnWidth(2, 200)
    table.setColumnWidth(3, 84)   # 期望DLC
    table.setColumnWidth(4, 88)   # 必须出现
    table.setColumnWidth(5, 80)   # 信号数
    table.setColumnWidth(6, 140)
    h.setSectionResizeMode(0, QHeaderView.Fixed)
    h.setSectionResizeMode(1, QHeaderView.Fixed)
    h.setSectionResizeMode(3, QHeaderView.Fixed)
    h.setSectionResizeMode(4, QHeaderView.Fixed)
    h.setSectionResizeMode(5, QHeaderView.Fixed)
    h.setSectionResizeMode(6, QHeaderView.Stretch)
    align_table(table, left_cols=(2, 6))  # 名称 / 备注


def layout_sig_table(table: QTableWidget):
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    table.setColumnWidth(0, 160)  # 信号名
    table.setColumnWidth(1, 70)
    table.setColumnWidth(2, 60)
    table.setColumnWidth(3, 90)
    table.setColumnWidth(4, 70)
    table.setColumnWidth(5, 80)
    table.setColumnWidth(6, 80)
    table.setColumnWidth(7, 70)
    h.setSectionResizeMode(8, QHeaderView.Stretch)  # 备注
    align_table(table, left_cols=(0, 8))  # 信号名 / 备注


def layout_right_table(table: QTableWidget):
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    table.setColumnWidth(0, 110)  # ID
    table.setColumnWidth(1, 90)   # 次数/序号
    table.setColumnWidth(2, 60)   # DLC
    table.setColumnWidth(4, 70)   # 协议内
    table.setColumnWidth(5, 90)   # 信号结果
    h.setSectionResizeMode(3, QHeaderView.Stretch)  # 数据
    h.setSectionResizeMode(6, QHeaderView.Stretch)  # 备注
    align_table(table, left_cols=(3, 6))  # 数据 / 备注


def paint_level(item, ci: int, level):
    """按等级给单元格上色（颜色取当前主题，浅色时与原先写死的值一致）

    ci 是要一并染前景色的列号，用来保证深色主题下重点列仍可读。
    """
    if level == "error":
        item.setBackground(QColor(COLORS['row_err_bg']))
        if ci in (0, 6):
            item.setForeground(QColor(COLORS['row_err_fg']))
    elif level == "warn":
        item.setBackground(QColor(COLORS['row_warn_bg']))
        if ci in (0, 6):
            item.setForeground(QColor(COLORS['row_warn_fg']))


def repaint_levels(table: QTableWidget):
    """主题切换后，把已显示的核对结果行按新颜色重画一遍"""
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item is not None:
                paint_level(item, c, item.data(LEVEL_ROLE))
