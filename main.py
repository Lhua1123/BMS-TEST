"""
BMS测试工具整合版
统一界面，支持进制转换、L2-BMS监控、L3-BMS监控
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from shared.style import apply_style, COLORS
from tabs.convert_ascii_tab import ConvertAsciiTab
from tabs.bms_monitor_tab import BmsMonitorTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMS测试工具整合版")
        self.setMinimumSize(1200, 800)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setDocumentMode(False)
        self.setCentralWidget(self.tab_widget)

        self.tab_widget.addTab(ConvertAsciiTab(), "进制转换")
        self.tab_widget.addTab(BmsMonitorTab(mode='L2'), "L2-BMS监控")
        self.tab_widget.addTab(BmsMonitorTab(mode='L3'), "L3-BMS监控")

        self.resize(1400, 900)
        self.showMaximized()

    def closeEvent(self, event):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, BmsMonitorTab):
                tab.comm.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei', 10))

    apply_style(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
