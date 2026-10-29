"""
报警测试面板共享工具
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QLabel, QSizePolicy, QPushButton


class RowButton(QPushButton):
    """表格行内操作按钮：强制文字居中绘制（QSS 的 text-align 对按钮不可靠）"""

    def paintEvent(self, event):
        from PyQt5.QtWidgets import QStyle, QStyleOptionButton, QStylePainter

        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.rect = self.rect()
        option.textAlignment = Qt.AlignCenter
        text = option.text
        option.text = ""
        painter.drawControl(QStyle.CE_PushButton, option)
        option.text = text
        painter.drawItemText(
            self.rect(),
            int(Qt.AlignCenter),
            option.palette,
            self.isEnabled(),
            text,
            QPalette.ButtonText,
        )

from shared.style import COLORS
from shared.style import combo_arrow_url, spin_up_arrow_url, spin_down_arrow_url


def button_fixed_size_qss(width: int, height: int) -> str:
    """强制按钮等宽等高（写入样式表，避免被 padding/字体撑开）"""
    return (
        f"min-width: {width}px; max-width: {width}px; "
        f"min-height: {height}px; max-height: {height}px; "
        f"padding: 0px; margin: 0px;"
    )


# 按钮样式：都是函数，每次调用读取当前主题颜色（切换主题后重新生成）
def btn_primary() -> str:
    return (
        f"background-color: {COLORS['accent']}; color: white; "
        f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
    )


def btn_warning() -> str:
    return (
        f"background-color: {COLORS['warning']}; color: white; "
        f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
    )


def btn_success() -> str:
    return (
        f"background-color: {COLORS['success']}; color: white; "
        f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
    )


def btn_danger() -> str:
    return (
        f"background-color: {COLORS['error']}; color: white; "
        f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
    )


def btn_neutral() -> str:
    return (
        f"background-color: {COLORS['bg_input']}; color: {COLORS['text']}; "
        f"padding: 3px 10px; border-radius: 3px; font-size: 12px; border: 1px solid {COLORS['border']}; "
        f"text-align: left;"
    )


def compact_qss_template() -> str:
    """紧凑面板 QSS 模板（应用于 QWidget）。占位符由 compact_qss() 替换。"""
    return f"""
QGroupBox {{
    font-size: 12px;
    font-weight: bold;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    margin-top: 14px;
    padding: 4px 6px 6px 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {COLORS['accent']};
    font-size: 12px;
}}
/* 面板内控件统一字号/字体，保证输入框、下拉框、复选框与外部标签一致 */
QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit, QCheckBox {{
    font-size: 12px;
    font-family: 'Microsoft YaHei', 'Segoe UI';
}}
QCheckBox {{
    background-color: transparent;
    spacing: 8px;
    padding: 2px 0px;
}}
QTableWidget {{
    font-size: 11px;
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    selection-background-color: {COLORS['accent_dim']};
}}
QTableWidget::item {{
    padding: 2px 4px;
    text-align: left;
}}
QHeaderView::section {{
    background-color: {COLORS['header_bg']};
    padding: 3px 4px;
    border: none;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
    font-size: 11px;
    font-weight: bold;
    text-align: center;
}}
QPushButton {{
    font-size: 12px;
}}
QLabel {{
    font-size: 12px;
}}
QSpinBox, QDoubleSpinBox {{
    font-size: 12px;
    min-height: 30px;
    max-height: 30px;
    padding: 2px 26px 2px 8px;
}}
QComboBox {{
    min-height: 30px;
    max-height: 30px;
    padding: 2px 26px 2px 8px;
}}
QLineEdit {{
    min-height: 30px;
    max-height: 30px;
    padding: 2px 8px;
}}
/* 注意：不能给 up-button/down-button 设 height，否则 Qt 会把两个按钮
   的点击区域都算到顶部，点哪个箭头都是增加（与全局样式保持一致）。 */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
    border-top-right-radius: 3px;
    background-color: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
    background-color: {COLORS['accent_dim']};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed {{
    background-color: rgba(37, 99, 235, 0.16);
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url(__SPIN_UP_ARROW__);
    width: 10px;
    height: 10px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 24px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-top: 1px solid {COLORS['border']};
    border-bottom-right-radius: 3px;
    background-color: transparent;
}}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {COLORS['accent_dim']};
}}
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background-color: rgba(37, 99, 235, 0.16);
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url(__SPIN_DOWN_ARROW__);
    width: 10px;
    height: 10px;
}}
"""


def compact_qss() -> str:
    """面板用 QSS：替换 SpinBox 箭头资源占位符。

    compact_qss_template 直接 setStyleSheet 时占位符不会被全局 apply_style 替换，
    会导致上下箭头空白。必须经本函数解析后再应用。
    """
    sheet = compact_qss_template()
    try:
        up = spin_up_arrow_url()
        down = spin_down_arrow_url()
        if up:
            sheet = sheet.replace("__SPIN_UP_ARROW__", up)
        if down:
            sheet = sheet.replace("__SPIN_DOWN_ARROW__", down)
    except Exception:
        pass
    return sheet


def table_qss() -> str:
    """混合对齐表格用 QSS：去掉 COMPACT_QSS 对 item 的 text-align 强制。

    否则 QSS 会覆盖 QTableWidgetItem.setTextAlignment，文本列/数字列无法区分。
    """
    return compact_qss().replace("text-align: left;", "")


class LeftAlignDelegate:
    """强制文本左对齐绘制（延迟导入 PyQt，避免无 GUI 环境 import 失败）。"""

    _cls = None

    @classmethod
    def get(cls):
        if cls._cls is None:
            from PyQt5.QtCore import Qt
            from PyQt5.QtGui import QColor, QFontMetrics
            from PyQt5.QtWidgets import QStyledItemDelegate, QStyle

            class _LeftAlignDelegate(QStyledItemDelegate):
                """单元格文字强制左对齐；选中态保持可读。"""

                def paint(self, painter, option, index):
                    painter.save()
                    if option.state & QStyle.State_Selected:
                        painter.fillRect(option.rect, QColor(COLORS["selection"]))
                        painter.setPen(QColor(COLORS["text"]))
                    else:
                        painter.setPen(QColor(COLORS["text"]))
                    painter.setFont(option.font)
                    text = index.data(Qt.DisplayRole)
                    text = "" if text is None else str(text)
                    # 与列内容左缘对齐：固定 10px 内边距
                    text_rect = option.rect.adjusted(10, 0, -8, 0)
                    painter.drawText(text_rect, int(Qt.AlignLeft | Qt.AlignVCenter), text)
                    painter.restore()

                def sizeHint(self, option, index):
                    text = index.data(Qt.DisplayRole)
                    text = "" if text is None else str(text)
                    try:
                        fm = QFontMetrics(option.font) if option.font is not None else QFontMetrics()
                        w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
                    except Exception:
                        w = len(text) * 12
                    return option.rect.size().__class__(w + 28, max(option.rect.height(), 28))

            cls._cls = _LeftAlignDelegate
        return cls._cls

    @staticmethod
    def attach(table, columns, parent=None):
        """给指定列挂上左对齐委托。"""
        delegate_cls = LeftAlignDelegate.get()
        parent = parent or table
        for col in columns:
            table.setItemDelegateForColumn(col, delegate_cls(parent))
