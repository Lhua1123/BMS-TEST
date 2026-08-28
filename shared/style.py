"""
统一样式定义
浅色工业风主题，蓝色点缀
"""

import os
import tempfile

# 颜色常量 - 浅色工业风
COLORS = {
    'bg_dark': '#f0f4f8',        # 浅灰蓝背景
    'bg_panel': '#ffffff',       # 面板背景
    'bg_input': '#f8fafc',       # 输入框背景
    'bg_hover': '#e2e8f0',       # 悬停背景
    'text': '#1a202c',           # 主文字
    'text_dim': '#64748b',       # 次要文字
    'accent': '#2563eb',         # 蓝色强调
    'accent_hover': '#3b82f6',   # 强调悬停
    'accent_dim': 'rgba(37, 99, 235, 0.08)',  # 强调色半透明
    'success': '#059669',        # 成功
    'warning': '#d97706',        # 警告
    'error': '#dc2626',          # 错误
    'border': '#cbd5e1',         # 边框
    'row_even': '#f8fafc',       # 表格偶数行
    'row_odd': '#ffffff',        # 表格奇数行
    'header_bg': '#f1f5f9',      # 表头背景
    'terminal_bg': '#1e293b',    # 终端背景
    'terminal_text': '#38bdf8',  # 终端文字（天蓝）
}

# 字体
FONTS = {
    'display': ('Space Mono', 12, 'Bold'),
    'heading': ('Space Mono', 11, 'Bold'),
    'body': ('Inter', 10),
    'body_bold': ('Inter', 10, 'Bold'),
    'mono': ('JetBrains Mono', 10),
    'mono_large': ('JetBrains Mono', 13),
    'tab': ('Space Mono', 10, 'Bold'),
}

# QSS样式表
MAIN_STYLESHEET = f"""
QMainWindow {{
    background-color: {COLORS['bg_dark']};
}}

QWidget {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['text']};
    font-family: 'Inter', 'Microsoft YaHei';
    font-size: 10pt;
}}

QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    background-color: {COLORS['bg_panel']};
}}

QTabBar::tab {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text_dim']};
    padding: 12px 28px;
    margin-right: 2px;
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    font-family: 'Space Mono', 'Microsoft YaHei';
    font-size: 10pt;
    font-weight: bold;
    min-width: 120px;
    border: 1px solid {COLORS['border']};
    border-bottom: none;
}}

QTabBar::tab:selected {{
    background-color: {COLORS['accent']};
    color: #ffffff;
    border: 1px solid {COLORS['accent']};
    border-bottom: none;
}}

QTabBar::tab:hover:!selected {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text']};
}}

QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 0px;
    margin-top: 16px;
    padding-top: 20px;
    font-weight: bold;
    font-size: 10pt;
    font-family: 'Space Mono', 'Microsoft YaHei';
    background-color: {COLORS['bg_panel']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: {COLORS['accent']};
    letter-spacing: 0.5px;
}}

QLabel {{
    color: {COLORS['text']};
    font-size: 10pt;
    background-color: transparent;
    padding: 2px 0px;
}}

QLineEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 0px;
    padding: 8px 12px;
    min-height: 24px;
    font-size: 10pt;
    font-family: 'JetBrains Mono', 'Consolas';
}}

QLineEdit:focus {{
    border: 1px solid {COLORS['accent']};
    background-color: {COLORS['bg_panel']};
}}

/* ===== 数字调节框 WPS 风格 ===== */
QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 8px 30px 8px 12px;
    min-height: 24px;
    font-size: 10pt;
    font-family: 'JetBrains Mono', 'Consolas';
}}

QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {COLORS['accent']};
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
    background-color: {COLORS['bg_panel']};
}}

/* 注意：不要给 up-button/down-button 设置 height。
   实测 Qt 在 height:50% 时会把两个按钮的点击区域都算到控件顶部，
   导致点哪个箭头都是增加。去掉 height 让 Qt 按控件高度自动均分。 */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 16px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
    border-top-right-radius: 4px;
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
    width: 9px;
    height: 9px;
}}

QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 16px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-bottom-right-radius: 4px;
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
    width: 9px;
    height: 9px;
}}

QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_dim']};
    border-color: {COLORS['border']};
}}

/* ===== 下拉框 WPS 风格 ===== */
QComboBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 8px 34px 8px 12px;
    min-height: 24px;
    font-size: 10pt;
    font-family: 'JetBrains Mono', 'Consolas';
}}

QComboBox:hover {{
    border-color: {COLORS['accent']};
}}

QComboBox:focus {{
    border: 1px solid {COLORS['accent']};
    background-color: {COLORS['bg_panel']};
}}

QComboBox::drop-down {{
    border: none;
    border-left: 1px solid {COLORS['border']};
    width: 24px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}}

QComboBox::drop-down:hover {{
    background-color: {COLORS['accent_dim']};
}}

QComboBox::down-arrow {{
    image: url(__COMBO_ARROW__);
    width: 10px;
    height: 10px;
}}

QComboBox:disabled {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_dim']};
    border-color: {COLORS['border']};
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text']};
    selection-background-color: {COLORS['accent']};
    selection-color: #ffffff;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 4px;
    outline: 0;
}}

QComboBox QAbstractItemView::item {{
    min-height: 22px;
    padding: 4px 8px;
    border-radius: 3px;
}}

QComboBox QAbstractItemView::item:hover:!selected {{
    background-color: {COLORS['accent_dim']};
}}


QPushButton {{
    background-color: {COLORS['accent']};
    color: #ffffff;
    border: none;
    border-radius: 0px;
    padding: 10px 20px;
    min-height: 28px;
    font-size: 10pt;
    font-weight: bold;
    font-family: 'Space Mono', 'Microsoft YaHei';
    letter-spacing: 0.5px;
}}

QPushButton:hover {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton:pressed {{
    background-color: #1d4ed8;
}}

QPushButton:disabled {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_dim']};
    border: 1px solid {COLORS['border']};
}}

QPushButton#danger {{
    background-color: {COLORS['error']};
    color: #ffffff;
}}

QPushButton#danger:hover {{
    background-color: #b91c1c;
}}

QPushButton#success {{
    background-color: {COLORS['success']};
    color: #ffffff;
}}

QPushButton#success:hover {{
    background-color: #047857;
}}

QTableWidget {{
    background-color: {COLORS['bg_panel']};
    alternate-background-color: {COLORS['bg_panel']};
    color: {COLORS['text']};
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent']};
    font-size: 10pt;
    font-family: 'Inter', 'Microsoft YaHei';
}}

QTableWidget::item {{
}}

QTableWidget::item:selected {{
    background-color: {COLORS['accent']};
    color: #ffffff;
}}

QTableWidget::item:alternate {{
    background-color: {COLORS['row_odd']};
}}

QTableWidget::item:alternate:selected {{
    background-color: {COLORS['accent']};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {COLORS['header_bg']};
    color: {COLORS['accent']};
    padding: 6px 10px;
    border: none;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
    font-weight: bold;
    font-size: 10pt;
    font-family: 'Space Mono', 'Microsoft YaHei';
}}

QScrollBar:vertical {{
    background-color: {COLORS['bg_dark']};
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    min-height: 40px;
    border-radius: 0px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['accent']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {COLORS['bg_dark']};
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS['border']};
    min-width: 40px;
    border-radius: 0px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['accent']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QTextEdit {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    font-family: 'JetBrains Mono', 'Consolas';
    font-size: 11pt;
    padding: 8px;
}}

QStatusBar {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text_dim']};
    border-top: 1px solid {COLORS['border']};
    font-size: 9pt;
    font-family: 'JetBrains Mono', 'Consolas';
}}

QSplitter::handle {{
    background-color: {COLORS['border']};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

QRadioButton {{
    spacing: 10px;
    font-size: 10pt;
    color: {COLORS['text']};
    padding: 4px 0px;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLORS['border']};
    border-radius: 0px;
    background-color: {COLORS['bg_input']};
}}

QRadioButton::indicator:checked {{
    background-color: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}

QRadioButton::indicator:hover {{
    border-color: {COLORS['accent']};
}}

QCheckBox {{
    spacing: 10px;
    font-size: 10pt;
    color: {COLORS['text']};
    padding: 4px 0px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLORS['border']};
    border-radius: 0px;
    background-color: {COLORS['bg_input']};
}}

QCheckBox::indicator:checked {{
    background-color: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}
"""


_COMBO_ARROW_PATH = os.path.join(tempfile.gettempdir(), 'bms_combo_arrow.png')
_SPIN_UP_ARROW_PATH = os.path.join(tempfile.gettempdir(), 'bms_spin_up_arrow.png')
_SPIN_DOWN_ARROW_PATH = os.path.join(tempfile.gettempdir(), 'bms_spin_down_arrow.png')


def _chevron_png(path: str, up: bool = False) -> str:
    """运行时生成 WPS 风格 chevron 箭头 PNG，返回可被 QSS url() 引用的路径（正斜杠）。
    注意：每次都重新生成，不缓存——因为曾出现过旧版本缓存了相反方向箭头、
    导致修复后用户机器上仍显示旧方向的问题。16x16 PNG 生成开销极小。"""
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QPen
        from PyQt5.QtCore import Qt, QPointF

        img = QImage(16, 16, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(COLORS['accent']))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if up:
            # chevron 向上箭头：⌃
            painter.drawLine(QPointF(3.5, 10.5), QPointF(8.0, 6.0))
            painter.drawLine(QPointF(8.0, 6.0), QPointF(12.5, 10.5))
        else:
            # chevron 向下箭头：⌄
            painter.drawLine(QPointF(3.5, 5.5), QPointF(8.0, 10.0))
            painter.drawLine(QPointF(8.0, 10.0), QPointF(12.5, 5.5))
        painter.end()
        img.save(path, 'PNG')
    except Exception:
        return ''
    return path.replace('\\', '/')


def combo_arrow_url() -> str:
    """下拉框箭头（向下）"""
    return _chevron_png(_COMBO_ARROW_PATH, up=False)


def spin_up_arrow_url() -> str:
    """数字调节框上箭头：直接生成"朝上"的图（⌃），与顶部按钮一致。
    注意：此前的"Qt 渲染时垂直翻转"结论在去掉 height 的配置下不成立，
    文件方向即显示方向，因此这里生成的就是朝上的图。"""
    return _chevron_png(_SPIN_UP_ARROW_PATH, up=True)


def spin_down_arrow_url() -> str:
    """数字调节框下箭头：直接生成"朝下"的图（⌄），与底部按钮一致。"""
    return _chevron_png(_SPIN_DOWN_ARROW_PATH, up=False)


def apply_style(app):
    """应用统一样式到QApplication"""
    sheet = MAIN_STYLESHEET
    sheet = sheet.replace('__COMBO_ARROW__', combo_arrow_url())
    sheet = sheet.replace('__SPIN_UP_ARROW__', spin_up_arrow_url())
    sheet = sheet.replace('__SPIN_DOWN_ARROW__', spin_down_arrow_url())
    app.setStyleSheet(sheet)
