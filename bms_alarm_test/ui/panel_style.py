"""
报警测试面板共享工具
"""

from shared.style import COLORS
from shared.style import combo_arrow_url, spin_up_arrow_url, spin_down_arrow_url

# 紧凑按钮样式
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