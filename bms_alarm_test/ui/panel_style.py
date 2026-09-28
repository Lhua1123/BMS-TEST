"""
报警测试面板共享工具
"""

from PyQt5.QtWidgets import QLabel, QSizePolicy

from shared.style import COLORS
from shared.style import combo_arrow_url, spin_up_arrow_url, spin_down_arrow_url

class WrapLabel(QLabel):
    """状态行标签：文本超宽时换行显示全文，不再静默截断（吞字）。

    Qt5 的 QHBoxLayout/QGridLayout 的 sizeHint 不会按 heightForWidth 计算换行
    高度（固定约两行），窄宽度下换行文字仍会被竖向裁剪。这里在文本或宽度
    变化时同步设置最小高度，强制布局给足行高。
    水平方向保持 QSizePolicy.Ignored：文本长短变化不参与布局宽度计算，
    避免进度刷新时整行左右抖动。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str):
        super().setText(text)
        self._sync_min_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_min_height()

    def _sync_min_height(self):
        w = self.width()
        if w <= 0:  # 首次布局前宽度未知，等 resizeEvent 再同步
            return
        need = self.heightForWidth(w)
        if need > 0 and need != self.minimumHeight():
            self.setMinimumHeight(need)


def button_fixed_size_qss(width: int, height: int) -> str:
    """强制按钮等宽等高（写入样式表，避免被 padding/字体撑开）"""
    return (
        f"min-width: {width}px; max-width: {width}px; "
        f"min-height: {height}px; max-height: {height}px; "
        f"padding: 0px; margin: 0px;"
    )


# 报警测试「测试控制」四按钮统一尺寸
FAULT_CTRL_BTN_W = 132
FAULT_CTRL_BTN_H = 34

BTN_PRIMARY = (
    f"background-color: {COLORS['accent']}; color: white; "
    f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
)
BTN_WARNING = (
    f"background-color: {COLORS['warning']}; color: white; "
    f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
)
BTN_SUCCESS = (
    f"background-color: {COLORS['success']}; color: white; "
    f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
)
BTN_DANGER = (
    f"background-color: {COLORS['error']}; color: white; "
    f"padding: 3px 10px; border-radius: 3px; font-size: 12px;"
)
BTN_NEUTRAL = (
    f"background-color: {COLORS['bg_input']}; color: {COLORS['text']}; "
    f"padding: 3px 10px; border-radius: 3px; font-size: 12px; border: 1px solid {COLORS['border']}; "
    f"text-align: left;"
)

# 紧凑面板 QSS（应用于 QWidget）
COMPACT_QSS = f"""
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
    padding: 2px 26px 2px 6px;
}}
/* 注意：不能给 up-button/down-button 设 height，否则 Qt 会把两个按钮
   的点击区域都算到顶部，点哪个箭头都是增加（与全局样式保持一致）。 */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 14px;
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
    width: 8px;
    height: 8px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 14px;
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
    width: 8px;
    height: 8px;
}}
"""


def compact_qss() -> str:
    """面板用 QSS：替换 SpinBox 箭头资源占位符。

    COMPACT_QSS 直接 setStyleSheet 时占位符不会被全局 apply_style 替换，
    会导致上下箭头空白。必须经本函数解析后再应用。
    """
    sheet = COMPACT_QSS
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
                        painter.fillRect(option.rect, QColor("#dbeafe"))
                        painter.setPen(QColor("#1a202c"))
                    else:
                        painter.setPen(QColor("#1a202c"))
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