"""
BMS测试工具整合版
统一界面，各功能页独立加载：某页出错不影响其它页，切换时提示无法打开。
"""

import sys
import os
import logging
import traceback
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

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QLabel, QPushButton, QPlainTextEdit,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

from shared.style import apply_style, COLORS
from shared.constants import LOG_RETENTION_DAYS, LOG_MAX_SIZE_MB, CLEANUP_INTERVAL_HOURS
from shared.log_cleanup import run_cleanup


def _app_icon_path() -> str:
    """开发运行 / PyInstaller 打包后的应用图标路径"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'assets', 'app.ico')


def _make_tab_convert():
    from tabs.convert_ascii_tab import ConvertAsciiTab
    return ConvertAsciiTab()


def _make_tab_can_parser():
    from tabs.can_parser_tab import CanParserTab
    return CanParserTab()


def _make_tab_monitor():
    from tabs.bms_monitor_tab import BmsMonitorTab
    return BmsMonitorTab(mode='L2')


def _make_tab_alarm():
    from tabs.bms_alarm_test_tab import BmsAlarmTestTab
    return BmsAlarmTestTab()


def _make_tab_protocol():
    from tabs.protocol_check_tab import ProtocolCheckTab
    return ProtocolCheckTab()


# 各功能页：key / 显示名 / 工厂（import+创建都延迟到首次切换）
# 工厂失败时该页显示错误占位，不影响其它页
TAB_SPECS = [
    ("convert", "进制转换", _make_tab_convert),
    ("can_parser", "CAN报文解析", _make_tab_can_parser),
    ("monitor", "BMS监控(L2/L3)", _make_tab_monitor),
    ("alarm", "报警测试", _make_tab_alarm),
    ("protocol", "协议核对", _make_tab_protocol),
]


class TabErrorPlaceholder(QWidget):
    """某功能页加载失败时的占位：提示 + 错误详情 + 重试"""

    def __init__(self, tab_name: str, error: str, on_retry, parent=None):
        super().__init__(parent)
        self._on_retry = on_retry
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(f"「{tab_name}」无法正常打开")
        title.setStyleSheet(
            f"color: {COLORS.get('error', '#dc2626')}; font-weight: bold; font-size: 16px;"
        )
        layout.addWidget(title)

        hint = QLabel(
            "其它功能页不受影响，可继续使用。\n"
            "常见原因：该页对应的 .py 正在修改/语法错误、依赖模块缺失。\n"
            "修好代码后点「重新加载本页」，或重启软件。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS.get('text', '#111827')}; font-size: 13px;")
        layout.addWidget(hint)

        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(error or "（无错误详情）")
        detail.setStyleSheet(
            f"background: {COLORS.get('bg_panel', '#f3f4f6')}; "
            f"color: {COLORS.get('text', '#111827')}; "
            f"font-family: Consolas, 'Microsoft YaHei'; font-size: 12px;"
        )
        layout.addWidget(detail, 1)

        btn_row = QVBoxLayout()
        btn = QPushButton("重新加载本页")
        btn.setMinimumHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"background-color: {COLORS.get('accent', '#2563eb')}; color: white; "
            f"border-radius: 4px; font-weight: bold; font-size: 13px; padding: 6px 16px;"
        )
        btn.clicked.connect(self._on_retry)
        btn_row.addWidget(btn, 0, Qt.AlignLeft)
        layout.addLayout(btn_row)


class TabHost(QWidget):
    """
    页签宿主：页签位置固定，只替换内部内容。
    避免 removeTab/insertTab，切换已加载页时不会额外闪烁/卡顿。
    """

    def __init__(self, key: str, title: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.title = title
        self.loaded = False
        self.content = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._hint = QLabel(f"「{title}」尚未加载")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setStyleSheet("color: #6b7280; font-size: 14px;")
        self._layout.addWidget(self._hint)

    def set_content(self, widget: QWidget):
        if self.content is not None:
            self._layout.removeWidget(self.content)
            self.content.setParent(None)
            self.content.deleteLater()
            self.content = None
        self._layout.removeWidget(self._hint)
        self._hint.setParent(None)
        self.content = widget
        self._layout.addWidget(widget)
        self.loaded = True

    def set_error(self, widget: QWidget):
        self.loaded = False
        self.set_content(widget)
        self.loaded = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMS测试工具整合版")
        self.setMinimumSize(1200, 900)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setDocumentMode(False)
        self.setCentralWidget(self.tab_widget)

        self._tab_specs = {key: (title, factory) for key, title, factory in TAB_SPECS}
        self._hosts = {}
        self._loading_tabs = set()
        self._preload_queue = []
        self._preload_timer = QTimer(self)
        self._preload_timer.setSingleShot(True)
        self._preload_timer.timeout.connect(self._preload_one)

        # 每个功能页一个常驻 TabHost，切换 tab 本身应接近原生速度
        for key, title, _factory in TAB_SPECS:
            host = TabHost(key, title)
            self.tab_widget.addTab(host, title)
            self._hosts[key] = host

        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.resize(1400, 1200)
        try:
            self.showMaximized()
        except Exception as e:
            logging.warning(f"showMaximized 失败，改用普通显示: {e}")
            self.show()

        # 先加载当前页，其余页后台预加载，避免之后切换发卡
        QTimer.singleShot(0, self._load_current_tab)
        QTimer.singleShot(400, self._start_preload)

        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._scheduled_cleanup)
        self.cleanup_timer.start(CLEANUP_INTERVAL_HOURS * 3600 * 1000)

    def _key_of_index(self, index: int):
        if index < 0 or index >= self.tab_widget.count():
            return None
        w = self.tab_widget.widget(index)
        return getattr(w, "key", None)

    def _on_tab_changed(self, index: int):
        key = self._key_of_index(index)
        if key:
            self._load_tab(key)

    def _load_current_tab(self):
        self._load_tab(self._key_of_index(self.tab_widget.currentIndex()))

    def _start_preload(self):
        """后台按顺序预加载其它页，预加载完的页切换时几乎无感"""
        self._preload_queue = [
            key for key, _t, _f in TAB_SPECS
            if key not in self._loading_tabs and not self._hosts[key].loaded
        ]
        if self._preload_queue:
            logging.info(f"后台预加载标签页: {self._preload_queue}")
            self._preload_timer.start(200)

    def _preload_one(self):
        if not self._preload_queue:
            return
        key = self._preload_queue.pop(0)
        host = self._hosts.get(key)
        if host is not None and not host.loaded:
            # 不抢当前页：仅在非当前页时预加载，当前页由切换逻辑负责
            current_key = self._key_of_index(self.tab_widget.currentIndex())
            if key != current_key:
                self._load_tab(key)
        if self._preload_queue:
            # 间隔加载，避免连续创建重型页时界面长时间无响应
            self._preload_timer.start(350)

    def _load_tab(self, key):
        if not key or key not in self._tab_specs:
            return
        host = self._hosts.get(key)
        if host is None or host.loaded:
            return
        if key in self._loading_tabs:
            return

        title, factory = self._tab_specs[key]
        self._loading_tabs.add(key)
        logging.info(f"加载标签页: {title} ({key})")
        try:
            widget = factory()
            if widget is None:
                raise RuntimeError("工厂返回空页面")
            host.set_content(widget)
            logging.info(f"标签页加载成功: {title}")
        except Exception as e:
            err = traceback.format_exc()
            logging.error(f"标签页加载失败: {title}\n{err}")
            placeholder = TabErrorPlaceholder(
                title, f"{e}\n\n{err}", on_retry=lambda k=key: self._retry_tab(k)
            )
            host.set_error(placeholder)
        finally:
            self._loading_tabs.discard(key)

    def _retry_tab(self, key):
        host = self._hosts.get(key)
        if host is not None:
            host.loaded = False
        self._load_tab(key)

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

    def _iter_loaded_tabs(self):
        for key, host in self._hosts.items():
            if host is not None and host.loaded and host.content is not None:
                yield key, host.content

    def closeEvent(self, event):
        for key, tab in self._iter_loaded_tabs():
            try:
                if key == "monitor" and hasattr(tab, "comm"):
                    tab.comm.disconnect()
                elif key == "alarm" and hasattr(tab, "cleanup"):
                    tab.cleanup()
                elif key == "protocol" and hasattr(tab, "cleanup"):
                    tab.cleanup()
            except Exception as e:
                logging.warning(f"关闭标签页清理失败 {key}: {e}")
        self._preload_queue.clear()
        self._preload_timer.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei', 10))

    icon_path = _app_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    apply_style(app)

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
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
