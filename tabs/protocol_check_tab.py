"""协议核对 Tab：三步核对流程（① 核对标准 → ② 实报来源 → ③ 开始核对）

打开界面按左→右走完就能出结果；模板编辑、实时采集、报文明细都是次级入口。
"""

import logging
import os
from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QTableWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bms_alarm_test.ui.panel_style import btn_danger, btn_neutral, btn_primary, btn_success
from protocol_check.checker import verify_frames
from protocol_check.excel_template import build_sample_template, load_template_excel
from protocol_check.log_parser import load_log_file
from protocol_check.models import CanFrame, CheckResult, TemplateBook
from protocol_check.zlg_live import LiveCanCollector
from shared.style import COLORS, on_theme_changed, themed_qss
from tabs.protocol_check_ui import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_FAMILY,
    FONT_MONO,
    FONT_MONO_BOLD,
    LEVEL_ROLE,
    PT_BODY,
    btn,
    common_qss,
    hex_col_width,
    layout_right_table,
    make_item,
    paint_level,
    repaint_levels,
    style_table,
)
from tabs.protocol_template_dialog import ProtocolTemplateDialog

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REF_DIR = os.path.join(_PROJECT_ROOT, "参考资料")
_SAMPLE_XLSX = os.path.join(_REF_DIR, "接收CAN协议核对模板.xlsx")

_BAUD_ITEMS = ["500k", "250k", "125k", "100k", "1M", "800k", "50k"]
_SRC_OFFLINE = "离线日志"
_SRC_LIVE = "实时采集"

RIGHT_COL = ["ID", "次数/序号", "DLC", "数据", "协议内", "信号结果", "备注"]


def _tab_qss() -> str:
    return f"""
ProtocolCheckTab {{
    background: {COLORS['bg_dark']};
    font-family: '{FONT_FAMILY}', 'Segoe UI', sans-serif;
    font-size: {PT_BODY}pt;
    color: {COLORS['text']};
}}
""" + common_qss()


class _LoadLogThread(QThread):
    finished_ok = pyqtSignal(list, str)
    failed = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            frames = load_log_file(self.path)
            self.finished_ok.emit(frames, self.path)
        except Exception as e:
            logger.exception("加载日志失败")
            self.failed.emit(str(e))


class _StepCard(QFrame):
    """流程条上的一步：序号徽标 + 标题 + 状态行 + 动作行"""

    def __init__(self, number: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stepCard")
        themed_qss(self, lambda: (
            f"QFrame#stepCard {{ border: 1px solid {COLORS['border']};"
            f" border-radius: 6px; background: {COLORS['bg_panel']}; }}"
        ))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        badge = QLabel(number)
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFont(FONT_BODY_BOLD)
        themed_qss(badge, lambda: (
            f"color: {COLORS['accent']}; background: {COLORS['accent_dim']};"
            f"border: 1px solid {COLORS['accent']}; border-radius: 13px;"
            f"font-family: '{FONT_FAMILY}'; font-size: {PT_BODY}pt; font-weight: bold;"
        ))
        title_lab = QLabel(title)
        title_lab.setFont(FONT_BODY_BOLD)
        head.addWidget(badge)
        head.addWidget(title_lab)
        head.addStretch(1)
        lay.addLayout(head)

        self.status = QLabel("-")
        self.status.setObjectName("status")
        self.status.setMinimumHeight(28)
        lay.addWidget(self.status)

        self.actions = QVBoxLayout()
        self.actions.setSpacing(4)
        lay.addLayout(self.actions)
        lay.addStretch(1)

    def set_status(self, text: str, tooltip: str = ""):
        self.status.setText(text)
        self.status.setToolTip(tooltip or text)


class ProtocolCheckTab(QWidget):
    """协议核对大 Tab：三步流程 + 核对结果"""

    def __init__(self, parent=None):
        super().__init__(parent)
        themed_qss(self, _tab_qss)
        on_theme_changed(self._on_theme_changed)
        self.setFont(FONT_BODY)
        self._template: Optional[TemplateBook] = None
        self._template_path: str = ""
        self._offline_frames: List[CanFrame] = []
        self._live_frames: List[CanFrame] = []
        self._live_log_name: str = ""
        self._collector_running = False
        self._result: Optional[CheckResult] = None
        self._collector = LiveCanCollector()
        self._load_thread: Optional[_LoadLogThread] = None
        self._template_dialog = None
        self._detail_expanded_once = False
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._on_live_tick)
        self._init_ui()
        self._ensure_template_loaded()
        self._refresh_source_status()

    def _on_theme_changed(self):
        if hasattr(self, 'tbl_right'):
            repaint_levels(self.tbl_right)

    # ───────── UI ─────────
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.addWidget(self._build_flow_bar(), 0)
        root.addWidget(self._build_result_panel(), 1)

    def _build_flow_bar(self) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        # ── ① 核对标准 ──
        self.card1 = _StepCard("1", "核对标准")
        b_edit = btn("编辑模板…", btn_primary)
        b_edit.setToolTip("导入 DBC/Excel、增删报文与信号、保存模板")
        b_edit.clicked.connect(self._on_open_template_dialog)
        self.card1.actions.addWidget(b_edit)
        row.addWidget(self.card1, 1)

        # ── ② 实报来源 ──
        self.card2 = _StepCard("2", "实报来源")
        src_row = QHBoxLayout()
        src_row.setSpacing(6)
        src_row.addWidget(QLabel("来源"))
        self.cmb_source = QComboBox()
        self.cmb_source.addItems([_SRC_OFFLINE, _SRC_LIVE])
        self.cmb_source.setToolTip("「开始核对」时用哪份报文")
        self.cmb_source.currentIndexChanged.connect(self._refresh_source_status)
        src_row.addWidget(self.cmb_source, 1)
        self.card2.actions.addLayout(src_row)

        act_row = QHBoxLayout()
        act_row.setSpacing(6)
        b_log = btn("导入日志…", btn_primary)
        b_log.setToolTip("导入 asc / blf / txt 离线报文")
        b_log.clicked.connect(self._on_import_log)
        self.btn_live_toggle = QToolButton()
        self.btn_live_toggle.setText("实时采集 ▾")
        self.btn_live_toggle.setCheckable(True)
        self.btn_live_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_live_toggle.setFixedHeight(30)
        self.btn_live_toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        themed_qss(self.btn_live_toggle, lambda: (
            f"QToolButton {{ color: {COLORS['accent']}; background: transparent;"
            f" border: 1px solid {COLORS['border']}; border-radius: 3px;"
            f" padding: 2px 8px; font-family: '{FONT_FAMILY}'; font-size: {PT_BODY}pt; }}"
            f"QToolButton:hover {{ border: 1px solid {COLORS['accent']}; }}"
            f"QToolButton:checked {{ background: {COLORS['accent_dim']};"
            f" border: 1px solid {COLORS['accent']}; }}"
        ))
        self.btn_live_toggle.toggled.connect(self._toggle_live_panel)
        act_row.addWidget(b_log, 1)
        act_row.addWidget(self.btn_live_toggle, 1)
        self.card2.actions.addLayout(act_row)

        self.card2.actions.addWidget(self._build_live_panel())
        row.addWidget(self.card2, 1)

        # ── ③ 开始核对 ──
        self.card3 = _StepCard("3", "开始核对")
        verify_row = QHBoxLayout()
        verify_row.setSpacing(6)
        self.btn_verify = btn("开始核对", btn_primary, height=40)
        self.btn_verify.clicked.connect(self._on_verify)
        b_clear = btn("清空结果", btn_neutral, height=40)
        b_clear.clicked.connect(self._on_clear_result)
        verify_row.addWidget(self.btn_verify, 3)
        verify_row.addWidget(b_clear, 2)
        self.card3.actions.addLayout(verify_row)
        row.addWidget(self.card3, 1)

        return wrap

    def _build_live_panel(self) -> QWidget:
        """实时 CAN 采集：默认收起，采集时状态仍写在卡片②"""
        panel = QWidget()
        gl = QHBoxLayout(panel)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(4)
        gl.addWidget(QLabel("通道"))
        self.cmb_channel = QComboBox()
        self.cmb_channel.addItems(["CH1", "CH2"])
        gl.addWidget(self.cmb_channel)
        gl.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(_BAUD_ITEMS)
        self.cmb_baud.setCurrentText("500k")
        gl.addWidget(self.cmb_baud)

        self.btn_live_start = btn("开始", btn_success)
        self.btn_live_start.clicked.connect(self._on_live_start)
        self.btn_live_stop = btn("停止", btn_danger)
        self.btn_live_stop.setEnabled(False)
        self.btn_live_stop.clicked.connect(self._on_live_stop)
        self.btn_live_clear = btn("清空", btn_neutral)
        self.btn_live_clear.clicked.connect(self._on_live_clear)
        gl.addWidget(self.btn_live_start)
        gl.addWidget(self.btn_live_stop)
        gl.addWidget(self.btn_live_clear)

        self._live_panel = panel
        panel.hide()
        return panel

    def _build_result_panel(self) -> QWidget:
        grp = QGroupBox("核对结果")
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        self.lbl_stats = QLabel("尚未核对 — 从左侧 ①②③ 走完即可")
        self.lbl_stats.setFont(FONT_BODY_BOLD)
        themed_qss(self.lbl_stats, lambda: (
            f"color: {COLORS['text']}; background: transparent; border: none;"
            f"font-family: '{FONT_FAMILY}'; font-size: {PT_BODY}pt; font-weight: bold;"
        ))
        lay.addWidget(self.lbl_stats)

        self.txt_issues = QTextEdit()
        self.txt_issues.setReadOnly(True)
        self.txt_issues.setFont(FONT_MONO)
        self.txt_issues.setPlaceholderText("点上方「开始核对」，此处列出异常与警告")
        lay.addWidget(self.txt_issues, 3)

        drawer = self._build_detail_drawer()
        lay.addWidget(drawer, 2)
        return grp

    def _build_detail_drawer(self) -> QWidget:
        """报文明细抽屉：标题行常驻，表格默认收起"""
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.btn_detail = QToolButton()
        self.btn_detail.setText("报文明细 ▾")
        self.btn_detail.setCheckable(True)
        self.btn_detail.setCursor(Qt.PointingHandCursor)
        themed_qss(self.btn_detail, lambda: (
            f"QToolButton {{ color: {COLORS['accent']}; background: transparent;"
            f" border: none; padding: 2px 6px; font-family: '{FONT_FAMILY}';"
            f" font-size: {PT_BODY}pt; font-weight: bold; text-align: left; }}"
            f"QToolButton:hover {{ color: {COLORS['accent_hover']}; }}"
        ))
        self.btn_detail.toggled.connect(self._toggle_detail_drawer)
        head.addWidget(self.btn_detail)
        head.addWidget(QLabel("视图"))
        self.cmb_right_view = QComboBox()
        self.cmb_right_view.addItems(["按ID统计", "帧明细(截断)"])
        self.cmb_right_view.currentIndexChanged.connect(self._refresh_right_table)
        head.addWidget(self.cmb_right_view)
        self.lbl_right_status = QLabel("尚未核对")
        self.lbl_right_status.setObjectName("hint")
        head.addWidget(self.lbl_right_status, 1)
        lay.addLayout(head)

        self.tbl_right = QTableWidget(0, len(RIGHT_COL))
        self.tbl_right.setHorizontalHeaderLabels(RIGHT_COL)
        style_table(self.tbl_right, min_h=160)
        self.tbl_right.setSortingEnabled(True)
        layout_right_table(self.tbl_right)
        lay.addWidget(self.tbl_right, 1)
        self.tbl_right.hide()
        return wrap

    def _toggle_live_panel(self, checked: bool):
        self._live_panel.setVisible(checked)
        self.btn_live_toggle.setText("实时采集 ▴" if checked else "实时采集 ▾")

    def _toggle_detail_drawer(self, checked: bool):
        self.tbl_right.setVisible(checked)
        self.btn_detail.setText("报文明细 ▴" if checked else "报文明细 ▾")

    # ───────── 状态行 ─────────
    def _refresh_source_status(self, *_args):
        # ① 核对标准
        book = self._template
        if not book:
            self.card1.set_status("未加载模板")
        else:
            sig_total = sum(len(m.signals) for m in book.messages.values())
            name = os.path.basename(self._template_path) if self._template_path else "-"
            self.card1.set_status(
                f"✓ {book.message_count} 条报文 / {sig_total} 个信号\n{name}",
                self._template_path or "-",
            )

        # ② 实报来源：两行都显示，「来源」下拉只决定核对用哪份
        off = self._offline_frames
        off_name = os.path.basename(self._live_log_name) if self._live_log_name else "未导入"
        if self._collector_running:
            ch = self.cmb_channel.currentText()
            baud = self.cmb_baud.currentText()
            live_txt = f"● 采集中 {ch}@{baud} · {len(self._live_frames)} 帧"
        elif self._live_frames:
            live_txt = f"已停止 · {len(self._live_frames)} 帧"
        else:
            live_txt = "未采集"
        self.card2.set_status(
            f"离线：{off_name} · {len(off)} 帧\n实时：{live_txt}",
        )

        # ③ 上次核对
        r = self._result
        if r:
            self.card3.set_status(f"已核对 · 异常 {r.error_count} · 警告 {r.warn_count}")
        else:
            self.card3.set_status("尚未核对")

    def _refresh_template_ui(self):
        self._refresh_source_status()

    # ───────── 模板 ─────────
    def _ensure_template_loaded(self):
        if os.path.isfile(_SAMPLE_XLSX):
            try:
                self._load_template_from_path(_SAMPLE_XLSX)
                return
            except Exception as e:
                logger.warning(f"加载默认 Excel 失败: {e}")
        sample_asc = os.path.join(_REF_DIR, "test1.asc")
        self._template = build_sample_template(
            asc_path=sample_asc if os.path.isfile(sample_asc) else None
        )
        self._template_path = "(内存示例)"
        self._refresh_template_ui()

    def _load_template_from_path(self, path: str):
        self._template = load_template_excel(path)
        self._template_path = path
        self._refresh_template_ui()

    def _on_open_template_dialog(self):
        dlg = ProtocolTemplateDialog(
            book=self._template or TemplateBook(),
            book_path=self._template_path,
            offline_frames=self._offline_frames,
            ref_dir=_REF_DIR if os.path.isdir(_REF_DIR) else _PROJECT_ROOT,
            sample_path=_SAMPLE_XLSX,
            parent=self,
        )
        self._template_dialog = dlg
        try:
            if dlg.exec_() == QDialog.Accepted:
                self._template = dlg.book
                self._template_path = dlg.book_path
                self._refresh_template_ui()
        finally:
            self._template_dialog = None

    # ───────── 离线 ─────────
    def _on_import_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 CAN 日志",
            _REF_DIR if os.path.isdir(_REF_DIR) else _PROJECT_ROOT,
            "CAN 日志 (*.asc *.blf *.txt *.log *.hex);;全部文件 (*.*)",
        )
        if not path:
            return
        self.btn_verify.setEnabled(False)
        self.card2.set_status("离线：加载中…")
        self._load_thread = _LoadLogThread(path, self)
        self._load_thread.finished_ok.connect(self._on_log_loaded)
        self._load_thread.failed.connect(self._on_log_failed)
        self._load_thread.start()

    def _on_log_loaded(self, frames: List[CanFrame], path: str):
        self._offline_frames = frames
        self._live_log_name = path
        self.btn_verify.setEnabled(True)
        self.cmb_source.setCurrentIndex(0)
        self._refresh_source_status()

    def _on_log_failed(self, err: str):
        self.btn_verify.setEnabled(True)
        self._refresh_source_status()
        QMessageBox.critical(self, "日志导入失败", err)

    # ───────── 实时 ─────────
    def _on_live_start(self):
        ch = 1 if self.cmb_channel.currentText() == "CH1" else 2
        baud = self.cmb_baud.currentText()
        ok = self._collector.start(ch, baud)
        if not ok:
            QMessageBox.warning(self, "实时采集", self._collector.last_error or "启动失败")
            return
        self._live_frames = []
        self._collector_running = True
        self.btn_live_start.setEnabled(False)
        self.btn_live_stop.setEnabled(True)
        self.cmb_source.setCurrentIndex(1)
        self._live_timer.start()
        self._refresh_source_status()

    def _on_live_stop(self):
        self._live_timer.stop()
        self._collector.stop()
        self._collector_running = False
        self.btn_live_start.setEnabled(True)
        self.btn_live_stop.setEnabled(False)
        self._refresh_source_status()

    def _on_live_clear(self):
        self._live_frames = []
        self._collector.take_frames()
        self._refresh_source_status()

    def _on_live_tick(self):
        frames = self._collector.take_frames()
        if frames:
            self._live_frames.extend(frames)
        self._refresh_source_status()

    def cleanup(self):
        try:
            if self._template_dialog is not None:
                self._template_dialog.reject()
        except Exception:
            pass
        try:
            self._live_timer.stop()
            self._collector.stop()
        except Exception:
            pass
        try:
            if self._load_thread and self._load_thread.isRunning():
                self._load_thread.wait(500)
        except Exception:
            pass

    # ───────── 核对 ─────────
    def _on_verify(self):
        if not self._template or not self._template.messages:
            QMessageBox.warning(self, "协议核对", "请先在「编辑模板」里导入 DBC/Excel")
            return
        use_live = self.cmb_source.currentIndex() == 1
        frames = self._live_frames if use_live else self._offline_frames
        if not frames:
            QMessageBox.warning(
                self,
                "协议核对",
                "没有可核对的报文：请导入 asc/blf/txt，或先开始实时采集",
            )
            return
        self._result = verify_frames(frames, self._template, keep_frames=True)
        self._refresh_result_ui()
        self._refresh_right_table()
        self._refresh_source_status()

    def _on_clear_result(self):
        self._result = None
        self.lbl_stats.setText("尚未核对 — 从左侧 ①②③ 走完即可")
        self.txt_issues.clear()
        self.lbl_right_status.setText("尚未核对")
        self._detail_expanded_once = False
        self._refresh_right_table()
        self._refresh_source_status()

    def _refresh_result_ui(self):
        r = self._result
        if not r:
            return
        self.lbl_stats.setText(r.summary_text)
        self.lbl_right_status.setText(f"已核对 | {r.summary_text}")
        lines = []
        if not r.issues:
            lines.append("未发现异常：实报 ID / DLC / 信号位段与模板一致。")
        else:
            for issue in r.issues:
                prefix = {"error": "[异常]", "warn": "[警告]", "info": "[信息]"}.get(issue.level, "[?]")
                line = f"{prefix} {issue.category} | 0x{issue.msg_id_hex} | {issue.message}"
                if issue.detail:
                    line += f" | {issue.detail}"
                if issue.sample:
                    line += f" | 样例: {issue.sample}"
                lines.append(line)
        self.txt_issues.setPlainText("\n".join(lines))
        # 首次核对后展开一次明细，之后尊重用户的折叠状态
        if not self._detail_expanded_once:
            self._detail_expanded_once = True
            self.btn_detail.setChecked(True)

    def _refresh_right_table(self, *_args):
        self.tbl_right.setSortingEnabled(False)
        view = self.cmb_right_view.currentIndex()
        r = self._result
        rows = []
        if view == 0:
            if r:
                for aid, st in r.id_stats.items():
                    in_t = "是" if st.get("in_template") else "否"
                    sig_fail = st.get("signal_fail") or []
                    sig_txt = "OK" if not sig_fail else "位段异常"
                    if not st.get("in_template"):
                        note = "协议外"
                        level = "error"
                    elif st.get("expected_dlc") is not None and st.get("dlc") != st.get("expected_dlc"):
                        note = f"DLC不符(期望{st.get('expected_dlc')})"
                        level = "warn"
                    elif sig_fail:
                        note = "; ".join(sig_fail[:2])
                        level = "error"
                    else:
                        note = st.get("name", "") or "匹配"
                        level = "ok"
                    sample = st.get("decoded_sample") or st.get("first_data", "")
                    rows.append(
                        (
                            level,
                            [
                                f"0x{aid:X}",
                                str(st.get("count", 0)),
                                str(st.get("dlc", "")),
                                sample,
                                in_t,
                                sig_txt,
                                note,
                            ],
                        )
                    )
            if r and r.template:
                for aid, tpl in r.template.messages.items():
                    if aid not in r.id_stats and tpl.required:
                        rows.append(
                            (
                                "error",
                                [
                                    f"0x{aid:X}",
                                    "0",
                                    "-",
                                    "",
                                    "是",
                                    "-",
                                    f"缺失: {tpl.name}",
                                ],
                            )
                        )
        else:
            if r:
                for i, fr in enumerate(r.frames[:1000], 1):
                    if r.template and fr.arbitration_id in r.template.messages:
                        tpl = r.template.messages[fr.arbitration_id]
                        in_t = "是"
                        if tpl.expected_dlc != fr.dlc:
                            note = f"DLC不符(期望{tpl.expected_dlc})"
                            level = "warn"
                        else:
                            note = tpl.name or "匹配"
                            level = "ok"
                    else:
                        in_t = "否"
                        note = "协议外"
                        level = "error"
                    rows.append(
                        (
                            level,
                            [
                                f"0x{fr.arbitration_id:X}",
                                str(i),
                                str(fr.dlc),
                                fr.data_hex,
                                in_t,
                                "",
                                note,
                            ],
                        )
                    )

        self.tbl_right.setRowCount(len(rows))
        ids = [row[1][0] for row in rows]
        self.tbl_right.setColumnWidth(0, hex_col_width(ids, FONT_MONO_BOLD, 104))
        aligns = [
            Qt.AlignCenter,
            Qt.AlignCenter,
            Qt.AlignCenter,
            Qt.AlignLeft | Qt.AlignVCenter,
            Qt.AlignCenter,
            Qt.AlignCenter,
            Qt.AlignLeft | Qt.AlignVCenter,
        ]
        monos = [True, True, True, True, False, False, False]
        for ri, (level, row) in enumerate(rows):
            for ci, val in enumerate(row):
                item = make_item(val, aligns[ci], mono=monos[ci])
                item.setData(LEVEL_ROLE, level)
                paint_level(item, ci, level)
                self.tbl_right.setItem(ri, ci, item)
        self.tbl_right.setSortingEnabled(True)
