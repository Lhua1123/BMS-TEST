"""
统一样式定义
浅色工业风主题，蓝色点缀
"""

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
    'mono_large': ('JetBrains Mono', 11),
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

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 0px;
    padding: 8px 12px;
    min-height: 24px;
    font-size: 10pt;
    font-family: 'JetBrains Mono', 'Consolas';
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
    background-color: {COLORS['bg_panel']};
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
    alternate-background-color: {COLORS['row_odd']};
    color: {COLORS['text']};
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent']};
    font-size: 10pt;
    font-family: 'Inter', 'Microsoft YaHei';
}}

QTableWidget::item {{
    padding: 8px 12px;
}}

QTableWidget::item:alternate {{
    background-color: {COLORS['row_odd']};
}}

QHeaderView::section {{
    background-color: {COLORS['header_bg']};
    color: {COLORS['accent']};
    padding: 10px 12px;
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
    background-color: {COLORS['terminal_bg']};
    color: {COLORS['terminal_text']};
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


def apply_style(app):
    """应用统一样式到QApplication"""
    app.setStyleSheet(MAIN_STYLESHEET)
