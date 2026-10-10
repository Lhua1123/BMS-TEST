"""
BMS测试工具整合版
统一界面，各功能页独立：某页出错只显示该页的错误占位，不影响其它页。

启动策略（本文件的核心约定）：
    主窗口出现之前，所有功能页一次性建完（QWidget 必须在 GUI 线程创建），
    主界面在全部页面就绪后才由 main() 显示。因此进入主界面后，任意页签都是
    现成页面，切换不需要任何等待——页签上不再有"未就绪禁止点击"的门槛。

    等待期间屏幕上有 StartupSplash 显示进度。这一条不是装饰：建页是几秒钟的
    纯 GUI 线程工作，若这段时间屏幕上什么都没有，用户会以为软件没启动、
    进而 Ctrl+C 强杀（一中断就起不来），所以可见的进度反馈是必须的。
"""

import sys
import os
import logging
import traceback
import time
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
# 两路分工，缺一不可：
#   1) 线程看门狗：主线程每秒心跳，停顿 >= STALL_SEC 就转储一次（5 秒冷却防爆盘）。
#      能抓到释放 GIL 的卡顿（openpyxl / DBC 解析等）；但主线程被 C 调用堵住、
#      GIL 一直不放时，看门狗线程自身也拿不到 GIL，转不出栈。
#      它只在主界面显示之后生效（_diag_state["ready"]）：启动阶段主线程本来就在
#      建页、根本不转事件循环，那时转储出来的全是"假卡顿"，只会刷满日志文件。
#   2) C 级 faulthandler 看门狗：启动阶段（进事件循环前）挂一个不依赖 GIL 的
#      定时器，主线程被 Qt/Windows 的 C 调用堵死也能转储；进事件循环后取消。
#      启动阶段真正的"卡死"由它负责，所以第 1 路不参与也不留盲区。
# 排查"点了软件没反应"时看这个文件，主线程栈顶就是卡点。
import time as _diag_time
import threading as _diag_threading
import faulthandler as _diag_faulthandler

DIAG_STALL_SEC = 3.0      # 主线程心跳停顿多少秒算卡顿
DIAG_STARTUP_SEC = 10.0   # 启动阶段超过多少秒强制转储一次

_diag_stall_path = _log_dir / "stall_trace.txt"
_diag_text = open(_diag_stall_path, "a", encoding="utf-8", buffering=1)
_diag_bin = open(_diag_stall_path, "ab", buffering=0)
_diag_state = {"last_beat": _diag_time.time(), "ready": False}


def _diag_beat():
    """主线程心跳（由 MainWindow 的 QTimer 每秒调用）"""
    _diag_state["last_beat"] = _diag_time.time()


def _diag_mark_ready():
    """主界面已显示：从这一刻起，主线程停顿才算真正的卡顿"""
    _diag_state["ready"] = True
    _diag_beat()


def _diag_watchdog():
    last_dump = 0.0
    while True:
        _diag_time.sleep(1.0)
        now = _diag_time.time()
        gap = now - _diag_state["last_beat"]
        # 启动阶段（主界面还没出来）主线程正在建页，停顿是预期的，不转储
        if not _diag_state["ready"]:
            continue
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
    f"（线程看门狗 {DIAG_STALL_SEC:.0f}s，主界面显示后生效 / 启动看门狗 {DIAG_STARTUP_SEC:.0f}s）\n"
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
    QVBoxLayout, QLabel, QPushButton, QPlainTextEdit, QProgressBar,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

from shared.style import (
    apply_style, COLORS, themed_qss, set_dark_mode, save_dark_mode, is_dark_mode,
)
from shared.titlebar import apply_titlebar
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


# 各功能页：key / 显示名 / 工厂（工厂失败时该页显示错误占位，不影响其它页）
TAB_SPECS = [
    ("convert", "进制转换", _make_tab_convert),
    ("can_parser", "CAN报文解析", _make_tab_can_parser),
    ("monitor", "BMS监控(L2/L3)", _make_tab_monitor),
    ("alarm", "报警测试", _make_tab_alarm),
    ("protocol", "协议核对", _make_tab_protocol),
]

# 预热相邻两页之间的间隔（毫秒）：给事件循环一个让位点，让用户操作不被连成一串
WARM_STEP_MS = 30

# 启动进度窗的阶段说明
STAGE_BUILD = "正在准备功能页"


class StartupSplash(QWidget):
    """启动进度窗：主界面出现之前唯一可见的窗口。

    为什么必须有它：主界面要等所有功能页建完才显示（这样进来就能切页签、不用等），
    而建页是几秒钟的纯 GUI 线程工作。这期间如果屏幕上什么都没有，用户看到的是
    "双击了没反应"，很容易 Ctrl+C 强杀（一中断就起不来）。所以先立一个轻量进度窗，
    把"正在做什么、还剩几页"直接显示出来。

    刻意做成无边框 + 置顶 + 无按钮：它只是个进度指示，不需要也不应该被操作。
    """

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("startupSplash")
        # 自定义 QWidget 子类默认不画样式表背景，必须显式打开
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(460, 174)
        self.setWindowTitle("BMS测试工具整合版")
        self.setStyleSheet(
            f"QWidget#startupSplash {{"
            f" background-color: {COLORS['bg_panel']};"
            f" border: 1px solid {COLORS['accent']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(10)

        title = QLabel("BMS测试工具整合版")
        title.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 16px; font-weight: bold;"
            f" background: transparent;")
        layout.addWidget(title)

        self._stage = QLabel(STAGE_BUILD)
        self._stage.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent;")
        layout.addWidget(self._stage)

        self._bar = QProgressBar()
        self._bar.setObjectName("startupBar")
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(12)
        self._bar.setRange(0, 1)
        self._bar.setValue(0)
        # 主题里没有 QProgressBar 规则，走 Windows 原生样式在 12px 高度下只画得出来
        # 1px 宽的竖条、连槽都没有，所以就地按主题 COLORS 上色。
        self._bar.setStyleSheet(
            f"QProgressBar#startupBar {{"
            f" background-color: {COLORS['bg_input']};"
            f" border: 1px solid {COLORS['border']};"
            f" border-radius: 5px; }}"
            f"QProgressBar#startupBar::chunk {{"
            f" background-color: {COLORS['accent']};"
            f" border-radius: 4px; }}"
        )
        layout.addWidget(self._bar)

        hint = QLabel("首次启动需准备各功能页，完成后自动进入主界面")
        hint.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;")
        layout.addWidget(hint)
        layout.addStretch(1)

        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)

    def set_progress(self, done: int, total: int, text: str):
        """更新进度并立刻重绘。

        建页占满 GUI 线程、事件循环不转，不主动 processEvents 的话进度窗会从头到尾
        冻在第一帧。这里是整个启动阶段唯一的让位点。
        """
        self._bar.setRange(0, max(total, 1))
        self._bar.setValue(done)
        self._stage.setText(f"{text} {done}/{total}" if total else text)
        try:
            QApplication.processEvents()
        except Exception:
            pass


class TabErrorPlaceholder(QWidget):
    """某功能页加载失败时的占位：提示 + 错误详情 + 重试"""

    def __init__(self, tab_name: str, error: str, on_retry, parent=None):
        super().__init__(parent)
        self._on_retry = on_retry
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(f"「{tab_name}」无法正常打开")
        themed_qss(title, lambda: (
            f"color: {COLORS.get('error', '#dc2626')}; font-weight: bold; font-size: 16px;"
        ))
        layout.addWidget(title)

        hint = QLabel(
            "其它功能页不受影响，可继续使用。\n"
            "常见原因：该页对应的 .py 正在修改/语法错误、依赖模块缺失。\n"
            "修好代码后点「重新加载本页」，或重启软件。"
        )
        hint.setWordWrap(True)
        themed_qss(hint, lambda: f"color: {COLORS.get('text', '#111827')}; font-size: 13px;")
        layout.addWidget(hint)

        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(error or "（无错误详情）")
        themed_qss(detail, lambda: (
            f"background: {COLORS.get('bg_panel', '#f3f4f6')}; "
            f"color: {COLORS.get('text', '#111827')}; "
            f"font-family: Consolas, 'Microsoft YaHei'; font-size: 12px;"
        ))
        layout.addWidget(detail, 1)

        btn_row = QVBoxLayout()
        btn = QPushButton("重新加载本页")
        btn.setMinimumHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        themed_qss(btn, lambda: (
            f"background-color: {COLORS.get('accent', '#2563eb')}; color: white; "
            f"border-radius: 4px; font-weight: bold; font-size: 13px; padding: 6px 16px;"
        ))
        btn.clicked.connect(self._on_retry)
        btn_row.addWidget(btn, 0, Qt.AlignLeft)
        layout.addLayout(btn_row)


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
        themed_qss(title, lambda: (
            f"color: {COLORS.get('error', '#dc2626')}; font-weight: bold; font-size: 16px;"
        ))
        layout.addWidget(title)

        hint = QLabel(
            "下面的错误详情已写入 logs/bms_test.log 和 logs/stall_trace.txt，可据此排查；\n"
            "常见原因是某个功能页的 .py 正在保存/有语法错误、或依赖模块缺失。"
        )
        hint.setWordWrap(True)
        themed_qss(hint, lambda: f"color: {COLORS.get('text', '#111827')}; font-size: 13px;")
        layout.addWidget(hint)

        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(error)
        themed_qss(detail, lambda: (
            f"background: {COLORS.get('bg_panel', '#f3f4f6')}; "
            f"color: {COLORS.get('text', '#111827')}; "
            f"font-family: Consolas, 'Microsoft YaHei'; font-size: 12px;"
        ))
        layout.addWidget(detail, 1)


class TabHost(QWidget):
    """
    页签宿主：页签位置固定，只替换内部内容。
    避免 removeTab/insertTab，切换已加载页时不会额外闪烁/卡顿。

    启动阶段内容一次装好（成功=真实页面，失败=错误占位），此后本页不再变化，
    所以这里只有"装上内容"这一种状态迁移，没有加载中/世代的中间态。
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

    def _clear(self):
        """移除当前内容（错误占位或上一次的真实页），交给 deleteLater 回收"""
        if self.content is not None:
            self._layout.removeWidget(self.content)
            self.content.setParent(None)
            self.content.deleteLater()
            self.content = None

    def set_content(self, widget: QWidget):
        """装入真实功能页"""
        self._clear()
        self.content = widget
        self._layout.addWidget(widget)
        self.loaded = True

    def set_error(self, widget: QWidget):
        """装入错误占位（不算 loaded，便于重试与清理判断）"""
        self._clear()
        self.content = widget
        self._layout.addWidget(widget)
        self.loaded = False


def _theme_btn_qss() -> str:
    """主题切换按钮：描边小按钮，不抢页面主色"""
    return (
        f"QPushButton {{ background-color: {COLORS['bg_panel']}; color: {COLORS['text']}; "
        f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
        f"padding: 4px 12px; margin: 2px 6px; min-height: 22px; "
        f"font-size: 10pt; font-weight: bold; }}\n"
        f"QPushButton:hover {{ border-color: {COLORS['accent']}; color: {COLORS['accent']}; }}"
    )


class MainWindow(QMainWindow):
    """主窗口。

    构造期间同步建完所有功能页；窗口的显示由 main() 在所有页就绪后统一触发，
    因此 __init__ 里刻意不调用 show()——"没建好就不要出现主界面"。
    """

    def __init__(self, progress_cb=None):
        super().__init__()
        self._progress_cb = progress_cb
        self.setWindowTitle("BMS测试工具整合版")
        self.setMinimumSize(1200, 900)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setDocumentMode(False)
        self.setCentralWidget(self.tab_widget)

        # 右上角的主题切换按钮：浅色 <-> 深色，选择会记住（见 shared/style.py）
        self.theme_btn = QPushButton()
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("切换浅色 / 深色界面")
        self.theme_btn.clicked.connect(self._toggle_theme)
        themed_qss(self.theme_btn, _theme_btn_qss)
        self._refresh_theme_button()
        self.tab_widget.setCornerWidget(self.theme_btn, Qt.TopRightCorner)

        self.resize(1400, 1200)
        self._sync_titlebar()

        self._tab_specs = {key: (title, factory) for key, title, factory in TAB_SPECS}
        self._hosts = {}

        # 每个功能页一个常驻 TabHost。页签顺序一次排定，之后不再增删，
        # 切换页签就是纯 QStackedWidget 换页，接近原生速度。
        for key, title, _factory in TAB_SPECS:
            host = TabHost(key, title)
            self.tab_widget.addTab(host, title)
            self._hosts[key] = host

        # 启动阶段一次性把所有页建完（QWidget 必须在 GUI 线程创建）。
        # 这一步发生在主窗口显示之前，是"进来就能切页签"的前提。
        self._build_all_tabs()

        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._scheduled_cleanup)
        self.cleanup_timer.start(CLEANUP_INTERVAL_HOURS * 3600 * 1000)

        # 诊断：主线程心跳（配合卡顿看门狗，见文件头说明）
        self._diag_hb_timer = QTimer(self)
        self._diag_hb_timer.timeout.connect(_diag_beat)
        self._diag_hb_timer.start(1000)

        # 预热：主窗口显示之后由 start_warmup() 触发，见该方法说明
        self._warm_queue = []
        self._warm_t0 = 0.0
        self._warm_timer = QTimer(self)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.timeout.connect(self._warm_one)

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------

    def _refresh_theme_button(self):
        # 按钮上写的是「点了会变成什么」
        self.theme_btn.setText("浅色模式" if is_dark_mode() else "深色模式")

    def _toggle_theme(self):
        dark = not is_dark_mode()
        set_dark_mode(QApplication.instance(), dark)
        save_dark_mode(dark)
        self._refresh_theme_button()
        self._sync_titlebar()

    def _sync_titlebar(self):
        # 系统标题栏跟随主题：标题栏颜色与页面背景一致（Win11 生效），按钮明暗随主题
        apply_titlebar(self, is_dark_mode(), COLORS['bg_dark'], COLORS['text'])

    # ------------------------------------------------------------------
    # 建页：启动阶段同步建完
    # ------------------------------------------------------------------

    def _report_progress(self, done: int, total: int, text: str):
        if self._progress_cb is not None:
            try:
                self._progress_cb(done, total, text)
            except Exception:
                pass

    def _build_all_tabs(self):
        """启动阶段把 TAB_SPECS 里所有页建完。

        串行建页是刻意的：QWidget 只能在 GUI 线程创建，并行无从谈起；
        页与页之间的让位点由 StartupSplash.set_progress 里的 processEvents 提供。
        """
        total = len(TAB_SPECS)
        self._report_progress(0, total, STAGE_BUILD)
        t0 = time.monotonic()
        for done, (key, title, factory) in enumerate(TAB_SPECS):
            self._report_progress(done, total, f"{STAGE_BUILD}：{title}")
            self._build_one(key, title, factory)
            self._report_progress(done + 1, total, f"{STAGE_BUILD}：{title}")
        _progress(
            f"功能页已全部就绪 {total}/{total}，耗时 {time.monotonic() - t0:.1f}s"
        )

    def _build_one(self, key: str, title: str, factory):
        """建一页：失败只让这一页显示错误占位，不影响其它页"""
        host = self._hosts.get(key)
        if host is None:
            return
        try:
            widget = factory()          # QWidget 必须在 GUI 线程创建
            if widget is None:
                raise RuntimeError("工厂返回空页面")
        except Exception:
            err = traceback.format_exc()
            # 注意用 0 参数 lambda：btn.clicked 会带一个 bool 参数发射，
            # 写成 lambda k=key: ... 的话 bool 会覆盖 k，key 变成 False 而静默失效。
            # key 是 _build_one 的形参，闭包按每次调用各自捕获，不存在晚绑定问题。
            host.set_error(TabErrorPlaceholder(
                title, err, on_retry=lambda: self._retry_tab(key)))
            logging.error(f"标签页创建失败: {key}\n{err}")
            return
        host.set_content(widget)
        logging.info(f"标签页加载成功: {key}")

    def _retry_tab(self, key):
        """错误占位板上的「重新加载本页」：同步重建这一页"""
        spec = self._tab_specs.get(key)
        if spec is None:
            return
        title, factory = spec
        logging.info(f"重新加载标签页: {title} ({key})")
        self._build_one(key, title, factory)

    # ------------------------------------------------------------------
    # 预热：主窗口显示后把各页离屏画一遍
    # ------------------------------------------------------------------

    def start_warmup(self):
        """主窗口已显示、所有页已建好 → 把非当前页离屏画一遍。

        为什么非做不可：QWidget 建好只是"对象在内存里"。从没 show 过的控件，
        第一次切过去要付一次性的 layout + paint（实测监控/报警/协议各 ~100ms）。
        这里在用户进来后的头一两百毫秒里把这份开销先付掉，之后切换就是纯换页。

        刻意**不动 currentIndex**：早先的写法是「切过去 → 让事件循环画一帧 →
        切回来」，收益一样但页签会自己翻页，用户看到软件启动后自动逐页跳，
        只会当成程序抽风（实测每个中间页会在屏幕上停留 200+ ms）。
        离屏画全程不改变选中页。
        """
        gate = self.tab_widget.currentIndex()
        self._warm_queue = []
        for idx in range(self.tab_widget.count()):
            if idx == gate:
                continue
            host = self._hosts.get(self._key_of_index(idx))
            # 建页失败的页是错误占位板，本来就很轻，不进预热队列
            if host is not None and host.loaded and host.content is not None:
                self._warm_queue.append(idx)
        if not self._warm_queue:
            return
        self._warm_t0 = time.monotonic()
        self._warm_timer.start(0)

    def _warm_one(self):
        """预热的一拍：把队首那一页离屏画一遍，然后让事件循环转一圈再画下一页"""
        if not self._warm_queue:
            _progress(f"界面预热完成，耗时 {time.monotonic() - self._warm_t0:.1f}s")
            return
        idx = self._warm_queue.pop(0)
        self._warm_paint(idx)
        self._warm_timer.start(WARM_STEP_MS)

    def _warm_paint(self, idx: int):
        """把 idx 这一页按「它将来真实显示时的尺寸」离屏画一遍，付掉首次 layout+paint。

        尺寸必须问当前可见的那一页：QStackedLayout::setGeometry 只给**当前**
        widget 摆位置，从没显示过的页还停在默认尺寸。用它自己的尺寸量出来的布局
        和真实首帧完全不是一回事——实测那样预热等于没预热（首次切换仍是 362ms）。
        """
        host = self.tab_widget.widget(idx)
        gate = self.tab_widget.currentWidget()
        if host is None or gate is None or host is gate:
            return
        size = gate.size()
        saved = host.geometry()
        # 按真实尺寸摆好并激活布局，再走一遍 polish
        host.setGeometry(0, 0, size.width(), size.height())
        host.ensurePolished()
        lay = host.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()
        host.ensurePolished()
        # grab() 是官方离屏绘制：会真的调 paintEvent，但不往屏幕上送
        pm = host.grab()
        # 全屏 pixmap 约 7MB，逐张画逐张扔，不攒着
        pm = None
        host.setGeometry(saved)

    def _key_of_index(self, index: int):
        if index < 0 or index >= self.tab_widget.count():
            return None
        w = self.tab_widget.widget(index)
        return getattr(w, "key", None)

    # ------------------------------------------------------------------
    # 资源清理
    # ------------------------------------------------------------------

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
        self._warm_queue.clear()
        self._warm_timer.stop()
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

    # 先立进度窗：主界面要等所有功能页建完才显示，这段等待必须有可见反馈
    splash = StartupSplash()
    if os.path.exists(icon_path):
        splash.setWindowIcon(QIcon(icon_path))
    splash.show()
    app.processEvents()

    _progress("创建主窗口并准备功能页...")
    try:
        window = MainWindow(progress_cb=splash.set_progress)
    except Exception:
        err = traceback.format_exc()
        logging.error(f"主窗口创建失败:\n{err}")
        # 兜底：至少把错误显示出来，别让用户只看到"点了没反应"
        splash.close()
        window = StartupErrorWindow(err)
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))

    # 所有功能页已就绪，此时才让主界面出现
    _progress("显示主窗口...")
    try:
        window.showMaximized()
    except Exception as e:
        logging.warning(f"showMaximized 失败，改用普通显示: {e}")
        window.show()
    window.raise_()
    window.activateWindow()
    # 让主窗口先画上第一帧再撤进度窗，避免中间露出一瞬桌面
    app.processEvents()
    splash.close()

    # 主界面已可见：页签全部现成，切换不再等；预热只是把各页首帧绘制提前付掉
    if isinstance(window, MainWindow):
        QTimer.singleShot(0, window.start_warmup)

    _diag_mark_ready()

    _progress("进入事件循环，界面准备就绪")
    _diag_faulthandler.cancel_dump_traceback_later()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
