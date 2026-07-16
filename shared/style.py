"""
统一样式定义
浅色工业风主题，适用于所有工具Tab
"""

# 颜色常量 - 浅色主题
COLORS = {
    'bg_dark': '#f5f5f5',
    'bg_panel': '#ffffff',
    'bg_input': '#ffffff',
    'bg_hover': '#e8e8e8',
    'text': '#1a1a1a',
    'text_dim': '#666666',
    'accent': '#0078d7',
    'accent_hover': '#1a8ceb',
    'success': '#107c10',
    'warning': '#ff8c00',
    'error': '#d13438',
    'border': '#d0d0d0',
    'row_even': '#f9f9f9',
    'row_odd': '#ffffff',
    'header_bg': '#e8e8e8',
}

# 字体
FONTS = {
    'title': ('Microsoft YaHei', 14, 'Bold'),
    'heading': ('Microsoft YaHei', 11, 'Bold'),
    'body': ('Microsoft YaHei', 10),
    'small': ('Microsoft YaHei', 9),
    'mono': ('Consolas', 11),
    'mono_small': ('Consolas', 9),
}

# QSS样式表
MAIN_STYLESHEET = f"""
QMainWindow {{
    background-color: {COLORS['bg_dark']};
}}

QWidget {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['text']};
    font-family: 'Microsoft YaHei';
    font-size: 10pt;
}}

QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    background-color: {COLORS['bg_panel']};
}}

QTabBar::tab {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text_dim']};
    padding: 10px 24px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-size: 11pt;
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
}}

QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    font-size: 10pt;
    background-color: {COLORS['bg_panel']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {COLORS['text']};
}}

QLabel {{
    color: {COLORS['text']};
    font-size: 10pt;
    background-color: transparent;
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 6px 10px;
    min-height: 20px;
    font-size: 10pt;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    selection-background-color: {COLORS['accent']};
    border: 1px solid {COLORS['border']};
}}

QPushButton {{
    background-color: {COLORS['accent']};
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    min-height: 24px;
    font-size: 10pt;
    font-weight: bold;
}}

QPushButton:hover {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton:pressed {{
    background-color: #005a9e;
}}

QPushButton:disabled {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_dim']};
}}

QPushButton#danger {{
    background-color: {COLORS['error']};
}}

QPushButton#danger:hover {{
    background-color: #b22d2d;
}}

QPushButton#success {{
    background-color: {COLORS['success']};
}}

QPushButton#success:hover {{
    background-color: #0e6b0e;
}}

QTableWidget {{
    background-color: {COLORS['bg_panel']};
    alternate-background-color: {COLORS['row_odd']};
    color: {COLORS['text']};
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent']};
    font-size: 9pt;
}}

QTableWidget::item {{
    padding: 4px 8px;
}}

QTableWidget::item:alternate {{
    background-color: {COLORS['row_odd']};
}}

QHeaderView::section {{
    background-color: {COLORS['header_bg']};
    color: {COLORS['text']};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
    font-weight: bold;
    font-size: 9pt;
}}

QScrollBar:vertical {{
    background-color: {COLORS['bg_dark']};
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['border']};
    min-height: 30px;
    border-radius: 4px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: #b0b0b0;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {COLORS['bg_dark']};
    height: 12px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS['border']};
    min-width: 30px;
    border-radius: 4px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: #b0b0b0;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QTextEdit {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    font-family: 'Consolas';
    font-size: 11pt;
}}

QStatusBar {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text_dim']};
    border-top: 1px solid {COLORS['border']};
    font-size: 9pt;
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
    spacing: 8px;
    font-size: 10pt;
    color: {COLORS['text']};
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}

QCheckBox {{
    spacing: 8px;
    font-size: 10pt;
    color: {COLORS['text']};
}}
"""


def apply_style(app):
    """应用统一样式到QApplication"""
    app.setStyleSheet(MAIN_STYLESHEET)
