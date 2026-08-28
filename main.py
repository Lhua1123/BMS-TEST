"""
BMS测试工具整合版
统一界面，支持进制转换、CAN报文解析、L2-BMS监控、L3-BMS监控
"""

import sys
import os
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置文件日志
_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
_log_file = _log_dir / "bms_test.log"
_handler = logging.FileHandler(str(_log_file), encoding='utf-8', mode='w')
_handler.setLevel(logging.INFO)
_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)-5s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
))
logging.getLogger().addHandler(_handler)
# INFO级别：过滤报文级DEBUG刷屏（收到CAN报文/忽略未监控/接收缓冲区等），
# 保留连接、测试流程、阈值设置、验证等关键日志；需要报文级调试时再开DEBUG
logging.getLogger().setLevel(logging.INFO)
logging.info(f"日志文件: {_log_file}")

from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from shared.style import apply_style, COLORS
from shared.constants import LOG_RETENTION_DAYS, LOG_MAX_SIZE_MB, CLEANUP_INTERVAL_HOURS
from shared.log_cleanup import run_cleanup
from tabs.convert_ascii_tab import ConvertAsciiTab
from tabs.can_parser_tab import CanParserTab
from tabs.bms_monitor_tab import BmsMonitorTab
from tabs.bms_alarm_test_tab import BmsAlarmTestTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMS测试工具整合版")
        self.setMinimumSize(1200, 900)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setDocumentMode(False)
        self.setCentralWidget(self.tab_widget)

        self.tab_widget.addTab(ConvertAsciiTab(), "进制转换")
        self.tab_widget.addTab(CanParserTab(), "CAN报文解析")
        self.tab_widget.addTab(BmsMonitorTab(mode='L2'), "BMS监控(L2/L3)")
        self.tab_widget.addTab(BmsAlarmTestTab(), "报警测试")

        self.resize(1400, 1200)
        self.showMaximized()

        # 每日定时清理过期日志与测试记录
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._scheduled_cleanup)
        self.cleanup_timer.start(CLEANUP_INTERVAL_HOURS * 3600 * 1000)

    def _scheduled_cleanup(self):
        try:
            run_cleanup(
                log_dir="logs",
                db_path="data/test_results.db",
                days_to_keep=LOG_RETENTION_DAYS,
                max_file_size_mb=LOG_MAX_SIZE_MB,
            )
        except Exception as e:
            logging.error(f"定时清理失败: {e}")

    def closeEvent(self, event):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, BmsMonitorTab):
                tab.comm.disconnect()
            elif isinstance(tab, BmsAlarmTestTab):
                tab.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei', 10))

    apply_style(app)

    # 启动时先清理一次过期日志与旧测试记录
    try:
        run_cleanup(
            log_dir="logs",
            db_path="data/test_results.db",
            days_to_keep=LOG_RETENTION_DAYS,
            max_file_size_mb=LOG_MAX_SIZE_MB,
        )
    except Exception as e:
        logging.error(f"启动清理失败: {e}")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
