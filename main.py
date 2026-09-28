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
logging.info(f"日志文件: {_log_dir / 'bms_test.log'}")

# ===== 卡顿/卡死诊断（转储所有线程调用栈到 logs/stall_trace.txt）=====
# 两路互补，缺一不可：
#   1) 线程看门狗：主线程每秒心跳，停顿 >= STALL_SEC 就转储一次（5 秒冷却防爆盘）。
#      能抓到释放 GIL 的卡顿（openpyxl / DBC 解析等）；但主线程被 C 调用堵住、
#      GIL 一直不放时，看门狗线程自身也拿不到 GIL，转不出栈。
#   2) C 级 faulthandler 看门狗：启动阶段（进事件循环前）挂一个不依赖 GIL 的
#      定时器，主线程被 Qt/Windows 的 C 调用堵死也能转储；进事件循环后取消。
# 排查"点了软件没反应"时看这个文件，主线程栈顶就是卡点。
import time as _diag_time
import threading as _diag_threading
import faulthandler as _diag_faulthandler

DIAG_STALL_SEC = 3.0      # 主线程心跳停顿多少秒算卡顿
DIAG_STARTUP_SEC = 10.0   # 启动阶段超过多少秒强制转储一次

_diag_stall_path = _log_dir / "stall_trace.txt"
_diag_text = open(_diag_stall_path, "a", encoding="utf-8", buffering=1)
_diag_bin = open(_diag_stall_path, "ab", buffering=0)
_diag_state = {"last_beat": _diag_time.time()}


def _diag_beat():
    """主线程心跳（由 MainWindow 的 QTimer 每秒调用）"""
    _diag_state["last_beat"] = _diag_time.time()


def _diag_watchdog():
    last_dump = 0.0
    while True:
        _diag_time.sleep(1.0)
        now = _diag_time.time()
        gap = now - _diag_state["last_beat"]
        if gap >= DIAG_STALL_SEC and now - last_dump >= 5.0:
            last_dump = now
            try:
                _diag_text.write(
                    f"{_diag_time.strftime('%H:%M:%S')} [diag] 主线程已 {gap:.0f}s 无心跳，转储所有线程调用栈:\n"
                )
                _diag_faulthandler.dump_traceback(file=_diag_bin, all_threads=True)
                _diag_text.write(f"{_diag_time.strftime('%H:%M:%S')} [diag] 转储结束\n")
            except Exception:
                pass


_diag_threading.Thread(target=_diag_watchdog, daemon=True, name="stall-watchdog").start()
_diag_faulthandler.dump_traceback_later(DIAG_STARTUP_SEC, exit=False, file=_diag_bin)
_diag_text.write(
    f"{_diag_time.strftime('%H:%M:%S')} [diag] 卡顿诊断已启动"
    f"（线程看门狗 {DIAG_STALL_SEC:.0f}s / 启动看门狗 {DIAG_STARTUP_SEC:.0f}s）\n"
)


def _progress(msg: str):
    """启动进度：同时写日志和控制台。

    界面出现前有 1~3 秒不可见的准备期（导 Qt、初始化数据库），
    这段时间控制台完全静音，容易被误判成卡死而 Ctrl+C（一中断就起不来）。
    打上带时间戳的进度后，等多久、卡在哪一步都能直接看出来。
    """
    logging.info(msg)
    try:
        print(f"{_diag_time.strftime('%H:%M:%S')} {msg}", flush=True)
    except Exception:
        pass  # pythonw 下没有控制台，print 会失败，忽略
# ===== 诊断与进度段结束 =====

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QLabel, QPushButton, QPlainTextEdit,
)
from PyQt5.QtCore import Qt, QTimer, QRunnable, QThreadPool, pyqtSignal, QObject
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


class TabLoadWorkerSignals(QObject):
    """worker → 主线程的通信信号（QObject 必须活在主线程）"""

    finished = pyqtSignal(object, str)   # (widget, error_str) — error_str 为空表示成功
    progress = pyqtSignal(str)           # 可选的阶段日志（暂留，factory 暂无内部阶段）


class TabLoadWorker(QRunnable):
    """后台线程：执行工厂函数创建 tab 页面，完成后通知主线程。"""

    def __init__(self, key: str, factory):
        super().__init__()
        self.key = key
        self.factory = factory
        self.signals = TabLoadWorkerSignals()

    def run(self):
        try:
            widget = self.factory()
            if widget is None:
                raise RuntimeError("工厂返回空页面")
            self.signals.finished.emit(widget, "")
        except Exception:
            import traceback
            self.signals.finished.emit(None, traceback.format_exc())


class StartupErrorWindow(QMainWindow):
    """主窗口都创建失败时的兜底：至少把错误原因显示出来。

    否则用户看到的是"点了没反应"，只能 Ctrl+C，拿到一段和真实原因无关的
    KeyboardInterrupt，无从排查。
    """

    def __init__(self, error: str):
        super().__init__()
        self.setWindowTitle("BMS测试工具整合版 - 启动失败")
        self.setMinimumSize(900, 600)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("主窗口创建失败，软件无法正常启动")
        title.setStyleSheet(
            f"color: {COLORS.get('error', '#dc2626')}; font-weight: bold; font-size: 16px;"
        )
        layout.addWidget(title)

        hint = QLabel(
            "下面的错误详情已写入 logs/bms_test.log 和 logs/stall_trace.txt，可据此排查；\n"
            "常见原因是某个功能页的 .py 正在保存/有语法错误、或依赖模块缺失。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS.get('text', '#111827')}; font-size: 13px;")
        layout.addWidget(hint)

        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(error)
        detail.setStyleSheet(
            f"background: {COLORS.get('bg_panel', '#f3f4f6')}; "
            f"color: {COLORS.get('text', '#111827')}; "
            f"font-family: Consolas, 'Microsoft YaHei'; font-size: 12px;"
        )
        layout.addWidget(detail, 1)


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
        self._load_gen = 0          # 加载世代：重试时递增，丢弃旧 worker 的结果
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

    # ---- 异步加载辅助 ----

    def show_loading(self):
        """切换为加载占位，返回当前世代（worker 完成时需比对）"""
        if self.content is not None:
            self._layout.removeWidget(self.content)
            self.content.setParent(None)
            self.content.deleteLater()
            self.content = None
        if self._hint.parent() is None:
            self._layout.addWidget(self._hint)
        self._hint.setText(f"「{self.title}」正在加载…")
        self._hint.setStyleSheet("color: #3b82f6; font-size: 14px;")
        self._hint.show()
        self.loaded = False
        return self._load_gen

    def on_loaded(self, gen: int, widget: QWidget):
        """worker 成功回调：世代匹配才应用结果"""
        if gen != self._load_gen:
            return
        self._restore_hint()
        self.set_content(widget)

    def on_load_error(self, gen: int, error: str, on_retry=None):
        """worker 失败回调：世代匹配才显示错误

        Parameters
        ----------
        on_retry : callable | None
            由 MainWindow 传入 _retry_tab，绑定到错误占位板的「重新加载」按钮。
        """
        if gen != self._load_gen:
            return
        self._restore_hint()
        placeholder = TabErrorPlaceholder(
            self.title, error,
            on_retry=on_retry or (lambda k=self.key: None)
        )
        self.set_error(placeholder)

    def _restore_hint(self):
        self._hint.setText(f"「{self.title}」尚未加载")
        self._hint.setStyleSheet("color: #6b7280; font-size: 14px;")


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

        # 全局线程池：所有 tab 加载共用，默认最大线程数 = CPU 核心数
        self._pool = QThreadPool.globalInstance()

        self.resize(1400, 1200)
        # 先把窗口显示出来，再建页签：页签创建若因系统原因（字体枚举/外壳/DWM）
        # 偶发变慢，也不会出现"点了软件、控制台也静默"被误判成打不开的情况。
        try:
            self.showMaximized()
        except Exception as e:
            logging.warning(f"showMaximized 失败，改用普通显示: {e}")
            self.show()

        # 每个功能页一个常驻 TabHost，切换 tab 本身应接近原生速度
        for key, title, _factory in TAB_SPECS:
            host = TabHost(key, title)
            self.tab_widget.addTab(host, title)
            self._hosts[key] = host

        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # 首个 tab 由 _load_tab 异步加载（后台线程，不阻塞界面绘制）
        QTimer.singleShot(0, self._load_current_tab)
        QTimer.singleShot(400, self._start_preload)

        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._scheduled_cleanup)
        self.cleanup_timer.start(CLEANUP_INTERVAL_HOURS * 3600 * 1000)

        # 诊断：主线程心跳（配合卡顿看门狗，见文件头说明）
        self._diag_hb_timer = QTimer(self)
        self._diag_hb_timer.timeout.connect(_diag_beat)
        self._diag_hb_timer.start(1000)

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
        """异步加载：立即显示加载态，后台线程执行工厂，完成后替换内容。"""
        if not key or key not in self._tab_specs:
            return
        host = self._hosts.get(key)
        if host is None or host.loaded:
            return
        if key in self._loading_tabs:
            return

        title, factory = self._tab_specs[key]
        self._loading_tabs.add(key)
        gen = host.show_loading()
        logging.info(f"加载标签页（异步）: {title} ({key})")

        worker = TabLoadWorker(key, factory)
        worker.signals.finished.connect(
            lambda widget, error, k=key, g=gen: self._on_loading_finished(k, g, widget, error)
        )
        self._pool.start(worker)

    def _on_loading_finished(self, key, gen, widget, error):
        """worker 完成回调（主线程）"""
        self._loading_tabs.discard(key)
        host = self._hosts.get(key)
        if host is None:
            return
        if error:
            host.on_load_error(gen, error, on_retry=lambda: self._retry_tab(key))
            logging.error(f"标签页加载失败: {key}\n{error}")
        else:
            host.on_loaded(gen, widget)
            logging.info(f"标签页加载成功: {key}")

    def _retry_tab(self, key):
        host = self._hosts.get(key)
        if host is not None:
            host._load_gen += 1
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
    _progress("初始化 Qt 应用...")
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei', 10))

    icon_path = _app_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    _progress("加载界面样式...")
    apply_style(app)

    _progress("清理过期日志/测试记录...")
    try:
        run_cleanup(
            log_dir="logs",
            db_path="data/test_results.db",
            days_to_keep=LOG_RETENTION_DAYS,
            max_file_size_mb=LOG_MAX_SIZE_MB,
        )
    except Exception as e:
        logging.error(f"启动清理失败: {e}")

    _progress("创建主窗口...")
    try:
        window = MainWindow()
    except Exception:
        err = traceback.format_exc()
        logging.error(f"主窗口创建失败:\n{err}")
        # 兜底：至少把错误显示出来，别让用户只看到"点了没反应"
        window = StartupErrorWindow(err)
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))

    _progress("显示主窗口...")
    window.show()

    _progress("进入事件循环，界面准备就绪")
    _diag_faulthandler.cancel_dump_traceback_later()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
