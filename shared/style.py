"""
统一样式定义
浅色工业风主题，蓝色点缀
"""

import json
import logging
import os
import tempfile
import weakref

# 颜色常量 - 浅色工业风（默认主题，取值不得随意改动）
_LIGHT_COLORS = {
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
    'alarm_l1': '#CA8A04',       # 一级报警（琥珀黄，与二级橙拉开距离）
    'alarm_l2': '#EA580C',       # 二级报警（橙）
    'alarm_l3': '#DC2626',       # 三级报警/故障（红）
    'border': '#cbd5e1',         # 边框
    'row_even': '#f8fafc',       # 表格偶数行
    'row_odd': '#ffffff',        # 表格奇数行
    'header_bg': '#f1f5f9',      # 表头背景
    'terminal_bg': '#1e293b',    # 终端背景
    'terminal_text': '#38bdf8',  # 终端文字（天蓝）
    'selection': '#dbeafe',      # 选中行底色（浅蓝）
    'reg_label': '#666666',      # 寄存器视图：地址文字
    'reg_dim': '#999999',        # 寄存器视图：未读到的占位
    'reg_value': '#000000',      # 寄存器视图：数值
    'status_on': 'green',        # 通讯已连接指示灯
    'status_off': 'gray',        # 通讯未连接指示灯
    'html_th': '#f0f0f0',        # 解析结果 HTML：表头底色
    'html_box': '#fafafa',       # 解析结果 HTML：计算步骤卡片底色
    'html_border': '#ccc',       # 解析结果 HTML：卡片边框
    'html_muted': '#666',        # 解析结果 HTML：说明文字
    'html_ok': '#0a0',           # 解析结果 HTML：计算结果高亮
    'row_err_bg': '#fee2e2',     # 协议核对：错误行底色
    'row_err_fg': '#b91c1c',     # 协议核对：错误行文字
    'row_warn_bg': '#fef3c7',    # 协议核对：警告行底色
    'row_warn_fg': '#b45309',    # 协议核对：警告行文字
    'tint_bg': '#eff6ff',        # 报告页「查看详情」按钮：浅蓝底
    'tint_fg': '#2563eb',        # 报告页「查看详情」按钮：文字
    'tint_border': '#93c5fd',    # 报告页「查看详情」按钮：边框
    'grid_line': '#ccc',         # 配置对话框：表格网格线/页签边框
    'list_text': '#1f2937',      # 配置对话框：下拉列表文字
}

# 深色主题：深蓝灰底 + 亮一点的文字和强调色，保证对比度
_DARK_COLORS = {
    'bg_dark': '#0f1724',
    'bg_panel': '#1a2332',
    'bg_input': '#111a29',
    'bg_hover': '#2a3649',
    'text': '#e2e8f0',
    'text_dim': '#94a3b8',
    'accent': '#3b82f6',
    'accent_hover': '#2563eb',
    'accent_dim': 'rgba(59, 130, 246, 0.18)',
    'success': '#059669',
    'warning': '#d97706',
    'error': '#ef4444',
    'alarm_l1': '#facc15',      # 一级：亮黄
    'alarm_l2': '#fb923c',      # 二级：橙
    'alarm_l3': '#f43f5e',      # 三级/故障：玫红
    'border': '#334155',
    'row_even': '#151f2e',
    'row_odd': '#1f2b3d',
    'header_bg': '#22304a',
    'terminal_bg': '#020617',
    'terminal_text': '#7dd3fc',
    'selection': '#1e3a5f',
    'reg_label': '#94a3b8',
    'reg_dim': '#64748b',
    'reg_value': '#e2e8f0',
    'status_on': '#22c55e',
    'status_off': '#64748b',
    'html_th': '#243247',
    'html_box': '#111a29',
    'html_border': '#334155',
    'html_muted': '#94a3b8',
    'html_ok': '#4ade80',
    'row_err_bg': '#4a1d22',
    'row_err_fg': '#fca5a5',
    'row_warn_bg': '#43330f',
    'row_warn_fg': '#fcd34d',
    'tint_bg': '#1b2d4a',
    'tint_fg': '#93c5fd',
    'tint_border': '#2d4f7c',
    'grid_line': '#334155',
    'list_text': '#e2e8f0',
}

# 当前生效的颜色表。注意：只能「原地修改」这个 dict（见 set_dark_mode），
# 不能重新赋值，否则各模块 `from shared.style import COLORS` 拿到的会是旧对象。
COLORS = dict(_LIGHT_COLORS)
_dark_mode = False

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

# QSS样式表（每次切换主题都会重新生成，取的是当前 COLORS）
def main_stylesheet() -> str:
    return f"""
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

/* 选择态一律用「打勾 / 空白」表达，不靠颜色填充。
   此前 checked 只是把方块填成蓝色，用户看不出"这是可以勾选的地方"，
   也分不清蓝色到底代表选中还是仅代表强调。 */
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLORS['border']};
    border-radius: 0px;
    background-color: {COLORS['bg_panel']};
}}

QRadioButton::indicator:hover {{
    border-color: {COLORS['accent']};
}}

QRadioButton::indicator:checked {{
    border-color: {COLORS['accent']};
    background-color: {COLORS['bg_panel']};
    image: url(__CHECK_MARK__);
}}

QRadioButton::indicator:disabled {{
    border-color: {COLORS['border']};
    background-color: {COLORS['bg_hover']};
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
    background-color: {COLORS['bg_panel']};
}}

QCheckBox::indicator:hover {{
    border-color: {COLORS['accent']};
}}

QCheckBox::indicator:checked {{
    border-color: {COLORS['accent']};
    background-color: {COLORS['bg_panel']};
    image: url(__CHECK_MARK__);
}}

QCheckBox::indicator:disabled {{
    border-color: {COLORS['border']};
    background-color: {COLORS['bg_hover']};
}}
"""


def _icon_path(name: str) -> str:
    """图标 PNG 路径。深色主题用单独文件名：Qt 会按路径缓存样式表里的图片，
    同一个文件名被重画成另一种颜色时，界面上仍会显示旧颜色。"""
    suffix = '_dark' if _dark_mode else ''
    return os.path.join(tempfile.gettempdir(), f'bms_{name}{suffix}.png')


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
    return _chevron_png(_icon_path('combo_arrow'), up=False)


def spin_up_arrow_url() -> str:
    """数字调节框上箭头：直接生成"朝上"的图（⌃），与顶部按钮一致。
    注意：此前的"Qt 渲染时垂直翻转"结论在去掉 height 的配置下不成立，
    文件方向即显示方向，因此这里生成的就是朝上的图。"""
    return _chevron_png(_icon_path('spin_up_arrow'), up=True)


def spin_down_arrow_url() -> str:
    """数字调节框下箭头：直接生成"朝下"的图（⌄），与底部按钮一致。"""
    return _chevron_png(_icon_path('spin_down_arrow'), up=False)


def _check_png(path: str) -> str:
    """运行时生成打勾 ✓ PNG，返回可被 QSS url() 引用的路径（正斜杠）。

    选择框（复选框/单选按钮）的选中态用「打勾」表达，而不是把方块填成纯色，
    让用户一眼看出"这是可勾选/已勾选"的地方。同样每次重新生成、不缓存，
    与 chevron 一套做法。
    """
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QPolygonF
        from PyQt5.QtCore import Qt, QPointF

        img = QImage(16, 16, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(COLORS['accent']))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        # ✓ 三段折线：左下短撇 → 底尖 → 右上挑，画在 16x16 指示器里
        # 用 QPolygonF 而非解包多个 QPointF：后者在 PyQt5 里可能抛异常，
        # 一旦被吞掉返回空串，image: url() 就加载失败、Qt 回退到原生样式，
        # 于是复选框出现"灰/蓝混杂"的怪样子。
        poly = QPolygonF()
        poly.append(QPointF(3.6, 8.5))
        poly.append(QPointF(6.4, 11.2))
        poly.append(QPointF(12.4, 4.6))
        painter.drawPolyline(poly)
        painter.end()
        img.save(path, 'PNG')
    except Exception:
        return ''
    return path.replace('\\', '/')


def check_mark_url() -> str:
    """选择框选中态的打勾 ✓"""
    return _check_png(_icon_path('check_mark'))


# ---------------------------------------------------------------------------
# 主题切换（浅色 / 深色）
# ---------------------------------------------------------------------------

# 浅色/深色偏好保存位置：与 protocol_user_config.json 放在同一目录
_THEME_FILE_NAME = 'ui_theme.json'

# 页面里用 setStyleSheet 写死颜色的控件：登记后切换主题时会重新调用工厂函数刷新。
# 用弱引用保存，控件销毁后自动跳过，不会阻止回收。
_THEMED_WIDGETS = []        # [(weakref 到控件, 返回样式表字符串的函数)]
# 其它需要跟随主题刷新的回调（如按颜色重画的列表项），同样用弱引用
_THEME_CALLBACKS = []


def is_dark_mode() -> bool:
    return _dark_mode


def themed_qss(widget, factory):
    """给控件设置样式表，并在切换主题时自动重新生成。

    factory 必须是无参函数，每次调用都重新读取 COLORS，例如：
        themed_qss(btn, lambda: f"color: {COLORS['text']};")
    """
    _THEMED_WIDGETS.append((weakref.ref(widget), factory))
    widget.setStyleSheet(factory())
    return widget


def on_theme_changed(callback):
    """注册主题切换回调（切换后调用 callback()）。绑定方法只保留弱引用。"""
    try:
        ref = weakref.WeakMethod(callback)
    except TypeError:
        ref = (lambda cb=callback: cb)
    _THEME_CALLBACKS.append(ref)


def _widget_alive(widget) -> bool:
    try:
        from PyQt5 import sip
        return not sip.isdeleted(widget)
    except Exception:
        return True


def _refresh_themed() -> None:
    alive = []
    for ref, factory in _THEMED_WIDGETS:
        widget = ref()
        if widget is None or not _widget_alive(widget):
            continue
        alive.append((ref, factory))
        try:
            widget.setStyleSheet(factory())
        except Exception:
            logging.getLogger(__name__).exception('主题刷新样式失败')
    _THEMED_WIDGETS[:] = alive

    alive_cb = []
    for ref in _THEME_CALLBACKS:
        cb = ref()
        if cb is None:
            continue
        alive_cb.append(ref)
        try:
            cb()
        except Exception:
            logging.getLogger(__name__).exception('主题刷新回调失败')
    _THEME_CALLBACKS[:] = alive_cb


def _build_app_sheet() -> str:
    sheet = main_stylesheet()
    sheet = sheet.replace('__COMBO_ARROW__', combo_arrow_url())
    sheet = sheet.replace('__SPIN_UP_ARROW__', spin_up_arrow_url())
    sheet = sheet.replace('__SPIN_DOWN_ARROW__', spin_down_arrow_url())
    sheet = sheet.replace('__CHECK_MARK__', check_mark_url())
    return sheet


def load_dark_mode() -> bool:
    """读取已保存的主题偏好；文件不存在或损坏时默认深色"""
    try:
        from shared.utils import get_protocol_config_path
        path = os.path.join(os.path.dirname(get_protocol_config_path()), _THEME_FILE_NAME)
        with open(path, 'r', encoding='utf-8') as f:
            return bool(json.load(f).get('dark_mode', True))
    except Exception:
        return True


def save_dark_mode(dark: bool) -> None:
    """保存主题偏好。写失败不影响使用，只记日志。"""
    try:
        from shared.utils import get_protocol_config_path
        path = os.path.join(os.path.dirname(get_protocol_config_path()), _THEME_FILE_NAME)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'dark_mode': bool(dark)}, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.getLogger(__name__).exception('保存主题设置失败')


def set_dark_mode(app, dark: bool) -> None:
    """切换整个应用的主题：更新颜色表 → 重画全局样式 → 刷新所有已登记的控件。"""
    global _dark_mode
    _dark_mode = bool(dark)
    COLORS.clear()
    COLORS.update(_DARK_COLORS if _dark_mode else _LIGHT_COLORS)
    if app is None:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(_build_app_sheet())
    _refresh_themed()


def apply_style(app):
    """应用统一样式到QApplication（启动时调用，会读取上次保存的主题）"""
    set_dark_mode(app, load_dark_mode())
