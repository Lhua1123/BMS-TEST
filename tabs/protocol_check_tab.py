"""协议核对 Tab：内置 DBC/Excel 模板编辑器 + 实报自动核对"""

import logging
import os
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QFontMetrics
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QTextEdit,
    QAbstractItemView,
    QLineEdit,
    QCheckBox,
    QDoubleSpinBox,
    QSpinBox,
    QSizePolicy,
    QFrame,
    QScrollArea,
    QToolButton,
)

from shared.style import COLORS, FONTS
from bms_alarm_test.ui.panel_style import COMPACT_QSS, BTN_PRIMARY, BTN_DANGER, BTN_SUCCESS, BTN_NEUTRAL
from protocol_check.models import CanFrame, CheckResult, MessageTemplate, SignalTemplate, TemplateBook
from protocol_check.excel_template import (
    load_template_excel,
    save_template_excel,
    build_sample_template,
)
from protocol_check.dbc_import import parse_dbc_file
from protocol_check.log_parser import load_log_file
from protocol_check.checker import verify_frames
from protocol_check.zlg_live import LiveCanCollector

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REF_DIR = os.path.join(_PROJECT_ROOT, "参考资料")
_SAMPLE_XLSX = os.path.join(_REF_DIR, "接收CAN协议核对模板.xlsx")

_BAUD_ITEMS = ["500k", "250k", "125k", "100k", "1M", "800k", "50k"]

MSG_COL = ["总线ID", "DBC原ID", "名称", "期望DLC", "必须出现", "信号数", "备注"]
SIG_COL = ["信号名", "起始位", "长度", "字节序", "类型", "因子", "偏移", "单位", "备注"]

# ── 全 Tab 统一字体标尺（与 main.py 一致：Microsoft YaHei 10pt）──
# 正文/按钮/表体/表头 同为 10pt，仅用加粗区分层级；提示用 9pt。
_PT_BODY = 10
_PT_SMALL = 9
_FONT_FAMILY = "Microsoft YaHei"
_FONT_MONO_FAMILY = "Consolas"

_FONT_BODY = QFont(_FONT_FAMILY, _PT_BODY)
_FONT_BODY_BOLD = QFont(_FONT_FAMILY, _PT_BODY, QFont.Bold)
_FONT_MONO = QFont(_FONT_MONO_FAMILY, _PT_BODY)
_FONT_MONO_BOLD = QFont(_FONT_MONO_FAMILY, _PT_BODY, QFont.Bold)
_FONT_SMALL = QFont(_FONT_FAMILY, _PT_SMALL)

# 字号只写 pt，避免 px/pt 混用导致忽大忽小
_TAB_QSS = f"""
ProtocolCheckTab {{
    background: {COLORS['bg_dark']};
    font-family: '{_FONT_FAMILY}', 'Segoe UI', sans-serif;
    font-size: {_PT_BODY}pt;
    color: {COLORS['text']};
}}
QGroupBox {{
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    font-weight: bold;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    margin-top: 16px;
    padding: 6px;
    background: {COLORS['bg_panel']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {COLORS['accent']};
    background: {COLORS['bg_dark']};
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    font-weight: bold;
}}
QLabel {{
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    background: transparent;
    padding: 0;
}}
QLabel#hint, QLabel#status {{
    color: {COLORS['text_dim']};
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_SMALL}pt;
    font-weight: normal;
    padding: 1px 0;
}}
QLabel#path {{
    color: {COLORS['text']};
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_SMALL}pt;
    font-weight: normal;
    background: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 3px 6px;
}}
QPushButton {{
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    min-height: 28px;
    max-height: 32px;
    padding: 2px 8px;
    border-radius: 3px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    min-height: 26px;
    max-height: 28px;
    padding: 2px 6px;
    background: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}
QCheckBox {{
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    spacing: 6px;
}}
QTableWidget {{
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background: {COLORS['bg_panel']};
    alternate-background-color: {COLORS['row_even']};
    selection-background-color: #dbeafe;
    selection-color: {COLORS['text']};
}}
QTableWidget::item {{
    padding: 2px 6px;
}}
QHeaderView::section {{
    background: {COLORS['header_bg']};
    color: {COLORS['text']};
    padding: 4px;
    border: none;
    border-right: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['accent']};
    font-family: '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    font-weight: bold;
    text-align: center;
}}
QTextEdit {{
    font-family: '{_FONT_MONO_FAMILY}', '{_FONT_FAMILY}';
    font-size: {_PT_BODY}pt;
    background: {COLORS['bg_panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 4px;
}}
QSplitter::handle {{
    background: {COLORS['border']};
    width: 3px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
"""


def _btn(text: str, style: str = BTN_NEUTRAL, height: int = 30) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(_FONT_BODY)
    b.setStyleSheet(style + f"font-family: '{_FONT_FAMILY}'; font-size: {_PT_BODY}pt;")
    b.setFixedHeight(height)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return b


def _make_item(text: str, align=Qt.AlignCenter, mono: bool = False, bold: bool = False):
    """统一表格单元格：10pt 字体 + 对齐 + 截断提示。"""
    item = QTableWidgetItem("" if text is None else str(text))
    if mono:
        item.setFont(_FONT_MONO_BOLD if bold else _FONT_MONO)
    else:
        item.setFont(_FONT_BODY_BOLD if bold else _FONT_BODY)
    item.setTextAlignment(int(align))
    full = item.text()
    if full:
        item.setToolTip(full)
    return item


def _section_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setFont(_FONT_BODY_BOLD)
    lab.setStyleSheet(
        f"color: {COLORS['accent']}; background: transparent; padding: 2px 0;"
        f"font-family: '{_FONT_FAMILY}'; font-size: {_PT_BODY}pt; font-weight: bold;"
    )
    return lab


def _apply_table_font(table: QTableWidget):
    """表体与表头同字号 10pt，仅表头加粗。"""
    table.setFont(_FONT_BODY)
    hh = table.horizontalHeader()
    hh.setFont(_FONT_BODY_BOLD)
    hh.setDefaultAlignment(Qt.AlignCenter)
    table.verticalHeader().setDefaultSectionSize(28)
    hh.setMinimumHeight(30)


def _style_table(table: QTableWidget, min_h: int = 120):
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setMinimumHeight(min_h)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(False)
    _apply_table_font(table)


def _hex_col_width(texts, font: QFont, minimum: int = 96) -> int:
    fm = QFontMetrics(font)
    w = minimum
    for t in texts:
        if not t:
            continue
        w = max(w, fm.horizontalAdvance(str(t)) + 22)
    return w


def _layout_msg_table(table: QTableWidget):
    """报文表：ID 列固定宽度防截断，名称/备注可拖，短列居中。"""
    h = table.horizontalHeader()
    h.setMinimumSectionSize(48)
    h.setSectionResizeMode(QHeaderView.Interactive)
    table.setColumnWidth(0, 104)
    table.setColumnWidth(1, 96)
    table.setColumnWidth(2, 200)
    table.setColumnWidth(3, 70)
    table.setColumnWidth(4, 72)
    table.setColumnWidth(5, 64)
    table.setColumnWidth(6, 140)
    h.setSectionResizeMode(0, QHeaderView.Fixed)
    h.setSectionResizeMode(1, QHeaderView.Fixed)
    h.setSectionResizeMode(3, QHeaderView.Fixed)
    h.setSectionResizeMode(4, QHeaderView.Fixed)
    h.setSectionResizeMode(5, QHeaderView.Fixed)
    h.setSectionResizeMode(6, QHeaderView.Stretch)


def _layout_sig_table(table: QTableWidget):
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    table.setColumnWidth(0, 160)  # 信号名
    table.setColumnWidth(1, 70)
    table.setColumnWidth(2, 60)
    table.setColumnWidth(3, 90)
    table.setColumnWidth(4, 70)
    table.setColumnWidth(5, 80)
    table.setColumnWidth(6, 80)
    table.setColumnWidth(7, 70)
    h.setSectionResizeMode(8, QHeaderView.Stretch)  # 备注


def _layout_right_table(table: QTableWidget):
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    table.setColumnWidth(0, 110)  # ID
    table.setColumnWidth(1, 90)   # 次数/序号
    table.setColumnWidth(2, 60)   # DLC
    table.setColumnWidth(4, 70)   # 协议内
    table.setColumnWidth(5, 90)   # 信号结果
    h.setSectionResizeMode(3, QHeaderView.Stretch)  # 数据
    h.setSectionResizeMode(6, QHeaderView.Stretch)  # 备注


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


class ProtocolCheckTab(QWidget):
    """协议核对大 Tab：模板编辑器 + 离线/实时核对"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_TAB_QSS)
        self.setFont(_FONT_BODY)
        self._template: Optional[TemplateBook] = None
        self._template_path: str = ""
        self._offline_frames: List[CanFrame] = []
        self._live_frames: List[CanFrame] = []
        self._result: Optional[CheckResult] = None
        self._collector = LiveCanCollector()
        self._load_thread: Optional[_LoadLogThread] = None
        self._selected_msg_id: Optional[int] = None
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._on_live_tick)
        self._init_ui()
        self._ensure_template_loaded()

    # ───────── UI ─────────
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 顶：三栏工作台
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)
        left = self._build_left_panel()
        center = self._build_center_panel()
        right = self._build_right_panel()
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([320, 680, 480])
        left.setMinimumWidth(300)
        left.setMaximumWidth(360)
        center.setMinimumWidth(520)
        right.setMinimumWidth(380)
        root.addWidget(splitter, 1)

        # 底：统计条 + 异常（固定高度，不抢三栏）
        bottom = self._build_bottom_panel()
        bottom.setFixedHeight(150)
        root.addWidget(bottom)

    def _build_left_panel(self) -> QWidget:
        """左栏：可滚动，避免控件挤压重叠"""
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)

        # ── 模板 ──
        tpl = QGroupBox("接收模板")
        tl = QVBoxLayout(tpl)
        tl.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        btn_dbc = _btn("导入 DBC", BTN_PRIMARY)
        btn_dbc.clicked.connect(self._on_import_dbc)
        btn_xlsx = _btn("导入 Excel", BTN_NEUTRAL)
        btn_xlsx.clicked.connect(self._on_load_template_excel)
        row1.addWidget(btn_dbc)
        row1.addWidget(btn_xlsx)
        tl.addLayout(row1)

        self.chk_map_id = QCheckBox("DBC ID → 总线ID（&0x1FFFFFFF）")
        self.chk_map_id.setChecked(True)
        self.chk_map_id.setToolTip(
            "DBC 文档 ID 常见 0x98xxxxxx，总线实报多为 0x18xxxxxx；默认自动映射，表中可改"
        )
        tl.addWidget(self.chk_map_id)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        btn_save = _btn("保存 Excel", BTN_SUCCESS)
        btn_save.clicked.connect(self._on_save_excel)
        btn_apply = _btn("应用到核对", BTN_PRIMARY)
        btn_apply.clicked.connect(self._on_apply_editor)
        row2.addWidget(btn_save)
        row2.addWidget(btn_apply)
        tl.addLayout(row2)

        self.lbl_path = QLabel("未加载模板")
        self.lbl_path.setObjectName("path")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setMinimumHeight(32)
        tl.addWidget(self.lbl_path)

        self.lbl_tpl_info = QLabel("模板：-")
        self.lbl_tpl_info.setObjectName("status")
        self.lbl_tpl_info.setWordWrap(True)
        tl.addWidget(self.lbl_tpl_info)

        self.lbl_editor_hint = QLabel("中栏改报文/信号 → 应用到核对 / 保存 Excel")
        self.lbl_editor_hint.setObjectName("hint")
        self.lbl_editor_hint.setWordWrap(True)
        tl.addWidget(self.lbl_editor_hint)
        lay.addWidget(tpl)

        # ── 离线 ──
        offline = QGroupBox("离线报文")
        ol = QVBoxLayout(offline)
        ol.setSpacing(6)
        btn_import_log = _btn("导入 asc / blf / txt", BTN_PRIMARY)
        btn_import_log.clicked.connect(self._on_import_log)
        ol.addWidget(btn_import_log)
        self.edt_log = QLineEdit()
        self.edt_log.setReadOnly(True)
        self.edt_log.setPlaceholderText("未导入日志")
        self.edt_log.setClearButtonEnabled(True)
        ol.addWidget(self.edt_log)
        self.lbl_log_info = QLabel("报文：-")
        self.lbl_log_info.setObjectName("status")
        self.lbl_log_info.setWordWrap(True)
        ol.addWidget(self.lbl_log_info)
        lay.addWidget(offline)

        # ── 实时 ──
        live = QGroupBox("实时 CAN（ZLG）")
        gl = QGridLayout(live)
        gl.setSpacing(6)
        gl.addWidget(QLabel("通道"), 0, 0)
        self.cmb_channel = QComboBox()
        self.cmb_channel.addItems(["CH1", "CH2"])
        gl.addWidget(self.cmb_channel, 0, 1)
        gl.addWidget(QLabel("波特率"), 1, 0)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(_BAUD_ITEMS)
        self.cmb_baud.setCurrentText("500k")
        gl.addWidget(self.cmb_baud, 1, 1)

        row3 = QHBoxLayout()
        row3.setSpacing(4)
        self.btn_live_start = _btn("开始采集", BTN_SUCCESS)
        self.btn_live_start.clicked.connect(self._on_live_start)
        self.btn_live_stop = _btn("停止", BTN_DANGER)
        self.btn_live_stop.setEnabled(False)
        self.btn_live_stop.clicked.connect(self._on_live_stop)
        self.btn_live_clear = _btn("清空", BTN_NEUTRAL)
        self.btn_live_clear.clicked.connect(self._on_live_clear)
        row3.addWidget(self.btn_live_start)
        row3.addWidget(self.btn_live_stop)
        row3.addWidget(self.btn_live_clear)
        gl.addLayout(row3, 2, 0, 1, 2)

        self.lbl_live_info = QLabel("实时：未采集")
        self.lbl_live_info.setObjectName("status")
        self.lbl_live_info.setWordWrap(True)
        gl.addWidget(self.lbl_live_info, 3, 0, 1, 2)
        lay.addWidget(live)

        # ── 核对 ──
        chk = QGroupBox("一键核对")
        cl = QVBoxLayout(chk)
        cl.setSpacing(4)
        self.chk_use_live = QCheckBox("使用实时帧（否则用离线日志）")
        cl.addWidget(self.chk_use_live)
        row4 = QHBoxLayout()
        row4.setSpacing(4)
        self.btn_verify = _btn("开始核对", BTN_PRIMARY, height=36)
        self.btn_verify.clicked.connect(self._on_verify)
        btn_clear = _btn("清空结果", BTN_NEUTRAL, height=36)
        btn_clear.setMaximumWidth(88)
        btn_clear.clicked.connect(self._on_clear_result)
        row4.addWidget(self.btn_verify, 1)
        row4.addWidget(btn_clear, 0)
        cl.addLayout(row4)
        lay.addWidget(chk)

        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return scroll

    def _build_center_panel(self) -> QWidget:
        grp = QGroupBox("内置模板编辑器")
        outer = QVBoxLayout(grp)
        outer.setSpacing(6)

        # 工具条
        tools = QHBoxLayout()
        tools.setSpacing(6)
        btn_add_msg = _btn("添加报文", BTN_NEUTRAL)
        btn_add_msg.clicked.connect(self._on_add_message)
        btn_del_msg = _btn("删除报文", BTN_NEUTRAL)
        btn_del_msg.clicked.connect(self._on_del_message)
        btn_from_log = _btn("按实报补齐ID", BTN_NEUTRAL)
        btn_from_log.setToolTip("把离线日志里出现、但模板没有的 ID 加进来（默认必须出现=否）")
        btn_from_log.clicked.connect(self._on_add_ids_from_log)
        tools.addWidget(btn_add_msg)
        tools.addWidget(btn_del_msg)
        tools.addWidget(btn_from_log)
        tools.addStretch(1)
        outer.addLayout(tools)

        self.lbl_editor_path = QLabel("当前模板：-")
        self.lbl_editor_path.setObjectName("hint")
        self.lbl_editor_path.setWordWrap(True)
        outer.addWidget(self.lbl_editor_path)

        # 上下分割：报文表 / 信号编辑
        v_split = QSplitter(Qt.Vertical)
        v_split.setHandleWidth(4)
        v_split.setChildrenCollapsible(False)

        # 报文表
        msg_wrap = QWidget()
        mv = QVBoxLayout(msg_wrap)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(4)
        mv.addWidget(_section_title("报文表（可编辑）"))
        self.tbl_template = QTableWidget(0, len(MSG_COL))
        self.tbl_template.setHorizontalHeaderLabels(MSG_COL)
        _style_table(self.tbl_template, min_h=160)
        self.tbl_template.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.tbl_template.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_template.itemSelectionChanged.connect(self._on_msg_row_selected)
        self.tbl_template.itemChanged.connect(self._on_msg_item_changed)
        _layout_msg_table(self.tbl_template)
        mv.addWidget(self.tbl_template, 1)
        v_split.addWidget(msg_wrap)

        # 信号区
        sig_wrap = QWidget()
        sv = QVBoxLayout(sig_wrap)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(4)
        sv.addWidget(_section_title("选中报文的信号"))

        # 紧凑两行表单
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)

        self.edt_sig_name = QLineEdit()
        self.edt_sig_name.setPlaceholderText("信号名")
        self.spn_sig_start = QSpinBox()
        self.spn_sig_start.setRange(0, 512)
        self.spn_sig_len = QSpinBox()
        self.spn_sig_len.setRange(1, 64)
        self.cmb_sig_order = QComboBox()
        self.cmb_sig_order.addItems(["Intel", "Motorola"])
        self.cmb_sig_type = QComboBox()
        self.cmb_sig_type.addItems(["uint", "int"])
        self.spn_sig_factor = QDoubleSpinBox()
        self.spn_sig_factor.setDecimals(4)
        self.spn_sig_factor.setRange(-1e9, 1e9)
        self.spn_sig_factor.setValue(1.0)
        self.spn_sig_offset = QDoubleSpinBox()
        self.spn_sig_offset.setDecimals(4)
        self.spn_sig_offset.setRange(-1e9, 1e9)
        self.edt_sig_unit = QLineEdit()
        self.edt_sig_unit.setPlaceholderText("单位")
        self.edt_sig_note = QLineEdit()
        self.edt_sig_note.setPlaceholderText("备注")

        # 第1行：信号名 起始位 长度 字节序
        form.addWidget(QLabel("信号名"), 0, 0)
        form.addWidget(self.edt_sig_name, 0, 1)
        form.addWidget(QLabel("起始位"), 0, 2)
        form.addWidget(self.spn_sig_start, 0, 3)
        form.addWidget(QLabel("长度"), 0, 4)
        form.addWidget(self.spn_sig_len, 0, 5)
        form.addWidget(QLabel("字节序"), 0, 6)
        form.addWidget(self.cmb_sig_order, 0, 7)
        # 第2行：类型 因子 偏移 单位 备注
        form.addWidget(QLabel("类型"), 1, 0)
        form.addWidget(self.cmb_sig_type, 1, 1)
        form.addWidget(QLabel("因子"), 1, 2)
        form.addWidget(self.spn_sig_factor, 1, 3)
        form.addWidget(QLabel("偏移"), 1, 4)
        form.addWidget(self.spn_sig_offset, 1, 5)
        form.addWidget(QLabel("单位"), 1, 6)
        form.addWidget(self.edt_sig_unit, 1, 7)
        # 第3行窄条：备注 + 按钮
        form.addWidget(QLabel("备注"), 2, 0)
        form.addWidget(self.edt_sig_note, 2, 1, 1, 3)
        btn_sig_add = _btn("添加信号", BTN_SUCCESS)
        btn_sig_add.clicked.connect(self._on_add_signal)
        btn_del_sig = _btn("删除信号", BTN_NEUTRAL)
        btn_del_sig.clicked.connect(self._on_del_signal)
        form.addWidget(btn_sig_add, 2, 5, 1, 2)
        form.addWidget(btn_del_sig, 2, 7)
        form.setColumnStretch(1, 2)
        form.setColumnStretch(3, 1)
        form.setColumnStretch(5, 1)
        form.setColumnStretch(7, 1)
        sv.addLayout(form)

        self.tbl_signals = QTableWidget(0, len(SIG_COL))
        self.tbl_signals.setHorizontalHeaderLabels(SIG_COL)
        _style_table(self.tbl_signals, min_h=100)
        self.tbl_signals.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.tbl_signals.itemChanged.connect(self._on_sig_item_changed)
        _layout_sig_table(self.tbl_signals)
        sv.addWidget(self.tbl_signals, 1)

        self.lbl_sig_status = QLabel("未选中报文")
        self.lbl_sig_status.setObjectName("status")
        sv.addWidget(self.lbl_sig_status)

        v_split.addWidget(sig_wrap)
        v_split.setStretchFactor(0, 3)
        v_split.setStretchFactor(1, 2)
        v_split.setSizes([360, 260])
        outer.addWidget(v_split, 1)
        return grp

    def _build_right_panel(self) -> QWidget:
        grp = QGroupBox("实报列表 / ID 统计")
        lay = QVBoxLayout(grp)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("视图"))
        self.cmb_right_view = QComboBox()
        self.cmb_right_view.addItems(["按ID统计", "帧明细(截断)"])
        self.cmb_right_view.currentIndexChanged.connect(self._refresh_right_table)
        row.addWidget(self.cmb_right_view, 1)
        lay.addLayout(row)

        self.lbl_right_status = QLabel("尚未核对 — 导入日志并「开始核对」后显示")
        self.lbl_right_status.setObjectName("hint")
        self.lbl_right_status.setWordWrap(True)
        lay.addWidget(self.lbl_right_status)

        self.tbl_right = QTableWidget(0, 7)
        self.tbl_right.setHorizontalHeaderLabels(
            ["ID", "次数/序号", "DLC", "数据", "协议内", "信号结果", "备注"]
        )
        _style_table(self.tbl_right, min_h=200)
        self.tbl_right.setSortingEnabled(True)
        _layout_right_table(self.tbl_right)
        lay.addWidget(self.tbl_right, 1)
        return grp

    def _build_bottom_panel(self) -> QWidget:
        grp = QGroupBox("核对结果")
        bl = QVBoxLayout(grp)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(4)

        top = QHBoxLayout()
        self.lbl_stats = QLabel("尚未核对")
        self.lbl_stats.setFont(_FONT_BODY_BOLD)
        self.lbl_stats.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent; border: none;"
            f"font-family: '{_FONT_FAMILY}'; font-size: {_PT_BODY}pt; font-weight: bold;"
        )
        top.addWidget(self.lbl_stats)
        top.addStretch(1)
        bl.addLayout(top)

        self.txt_issues = QTextEdit()
        self.txt_issues.setReadOnly(True)
        self.txt_issues.setFont(_FONT_MONO)
        self.txt_issues.setPlaceholderText("一键核对后，此处列出异常与警告")
        bl.addWidget(self.txt_issues)
        return grp

    # ───────── 模板加载/保存 ─────────
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

    def _short_path(self, path: str, keep: int = 48) -> str:
        if not path:
            return "-"
        if len(path) <= keep:
            return path
        return "…" + path[-keep:]

    def _refresh_template_ui(self):
        book = self._template
        path_txt = self._template_path or "-"
        self.lbl_path.setText(self._short_path(path_txt, 42))
        self.lbl_path.setToolTip(path_txt)
        if hasattr(self, "lbl_editor_path"):
            self.lbl_editor_path.setText(f"当前模板：{self._short_path(path_txt, 50)}")
        if not book:
            self.lbl_tpl_info.setText("模板：-")
            self.tbl_template.setRowCount(0)
            self.tbl_signals.setRowCount(0)
            return
        sig_total = sum(len(m.signals) for m in book.messages.values())
        self.lbl_tpl_info.setText(f"模板：{book.message_count} 条报文 / {sig_total} 个信号")
        self._fill_message_table()

    def _fill_message_table(self):
        book = self._template
        self.tbl_template.blockSignals(True)
        if not book:
            self.tbl_template.setRowCount(0)
            self.tbl_template.blockSignals(False)
            return
        msgs = sorted(book.messages.values(), key=lambda m: m.msg_id)
        self.tbl_template.setRowCount(len(msgs))
        # 列对齐约定：0,1 ID 居中等宽；2 名称左；3-5 居中；6 备注左
        for r, m in enumerate(msgs):
            dbc_orig = ""
            note = m.note or ""
            if "DBC:" in note:
                try:
                    part = note.split("DBC:", 1)[1]
                    dbc_orig = part.split("→")[0].split()[0]
                except Exception:
                    dbc_orig = ""
            items = [
                _make_item(f"{m.msg_id:X}", Qt.AlignCenter, mono=True, bold=True),
                _make_item(dbc_orig, Qt.AlignCenter, mono=True),
                _make_item(m.name, Qt.AlignLeft | Qt.AlignVCenter),
                _make_item(str(m.expected_dlc), Qt.AlignCenter, mono=True),
                _make_item("是" if m.required else "否", Qt.AlignCenter),
                _make_item(str(len(m.signals)), Qt.AlignCenter, mono=True),
                _make_item(note, Qt.AlignLeft | Qt.AlignVCenter),
            ]
            for c, item in enumerate(items):
                self.tbl_template.setItem(r, c, item)
        # 按实际文字度量 ID 列宽，避免 Consolas 下被省略号截断
        bus_ids = [self.tbl_template.item(r, 0).text() for r in range(self.tbl_template.rowCount()) if self.tbl_template.item(r, 0)]
        dbc_ids = [self.tbl_template.item(r, 1).text() for r in range(self.tbl_template.rowCount()) if self.tbl_template.item(r, 1)]
        self.tbl_template.setColumnWidth(0, _hex_col_width(bus_ids, _FONT_MONO_BOLD, 104))
        self.tbl_template.setColumnWidth(1, _hex_col_width(dbc_ids, _FONT_MONO, 92))
        self.tbl_template.blockSignals(False)

    def _read_message_table_to_template(self):
        if not self._template:
            self._template = TemplateBook()
        old = self._template.messages
        new_map: Dict[int, MessageTemplate] = {}
        for r in range(self.tbl_template.rowCount()):
            id_item = self.tbl_template.item(r, 0)
            id_txt = (id_item.text() if id_item else "").strip()
            name = self.tbl_template.item(r, 2).text() if self.tbl_template.item(r, 2) else ""
            dlc_txt = self.tbl_template.item(r, 3).text() if self.tbl_template.item(r, 3) else "8"
            req_txt = self.tbl_template.item(r, 4).text() if self.tbl_template.item(r, 4) else "是"
            note = self.tbl_template.item(r, 6).text() if self.tbl_template.item(r, 6) else ""
            if not id_txt:
                continue
            try:
                msg_id = int(id_txt.replace("0x", "").replace("0X", ""), 16)
            except Exception:
                continue
            try:
                dlc = int(float(dlc_txt))
            except Exception:
                dlc = 8
            required = str(req_txt).strip() in ("是", "Y", "y", "1", "true", "True")
            prev = old.get(msg_id)
            signals = list(prev.signals) if prev else []
            new_map[msg_id] = MessageTemplate(
                msg_id=msg_id,
                name=name.strip(),
                expected_dlc=dlc,
                required=required,
                note=note.strip(),
                signals=signals,
            )
        self._template.messages = new_map
        self._fill_signal_table()

    def _on_apply_editor(self):
        self._read_message_table_to_template()
        self._refresh_template_ui()
        QMessageBox.information(self, "已应用", "编辑器中的模板已应用到核对引擎。")

    def _on_save_excel(self):
        self._read_message_table_to_template()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存接收 Excel 模板",
            _SAMPLE_XLSX if os.path.isfile(_SAMPLE_XLSX)
            else os.path.join(_REF_DIR, "接收CAN协议核对模板.xlsx"),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            save_template_excel(self._template, path)
            self._template_path = path
            self._template = load_template_excel(path)
            self._refresh_template_ui()
            QMessageBox.information(self, "已保存", f"接收模板已保存：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _on_import_dbc(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入标准 DBC",
            _REF_DIR if os.path.isdir(_REF_DIR) else _PROJECT_ROOT,
            "DBC (*.dbc);;全部文件 (*.*)",
        )
        if not path:
            return
        try:
            book, notes = parse_dbc_file(path, map_id=self.chk_map_id.isChecked())
        except Exception as e:
            QMessageBox.critical(self, "DBC 导入失败", str(e))
            return
        for m in book.messages.values():
            m.required = False
        self._template = book
        self._template_path = f"DBC:{os.path.basename(path)}"
        self._refresh_template_ui()
        note_txt = "\n".join(notes[:8])
        QMessageBox.information(
            self,
            "DBC 已导入",
            f"{os.path.basename(path)}\n\n{note_txt}\n\n"
            "已在中栏生成可编辑列表：\n"
            "· 默认 ID 已映射为总线 ID（可改）\n"
            "· 「必须出现」默认=否，请按测试范围改成「是」\n"
            "· 选中报文后可在下方增删信号\n"
            "· 完成后：应用到核对 / 保存 Excel",
        )

    def _on_load_template_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入接收 Excel 模板",
            _REF_DIR if os.path.isdir(_REF_DIR) else _PROJECT_ROOT,
            "Excel (*.xlsx *.xlsm)",
        )
        if not path:
            return
        try:
            self._load_template_from_path(path)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    # ───────── 编辑器 ─────────
    def _on_msg_row_selected(self):
        rows = self.tbl_template.selectionModel().selectedRows() if self.tbl_template.selectionModel() else []
        if not rows:
            self._selected_msg_id = None
        else:
            r = rows[0].row()
            item = self.tbl_template.item(r, 0)
            try:
                self._selected_msg_id = int((item.text() or "").replace("0x", ""), 16) if item else None
            except Exception:
                self._selected_msg_id = None
        self._fill_signal_table()

    def _on_msg_item_changed(self, item: QTableWidgetItem):
        if item.column() != 0:
            return
        try:
            msg_id = int((item.text() or "").replace("0x", "").replace("0X", ""), 16)
        except Exception:
            return
        self._selected_msg_id = msg_id
        self._fill_signal_table()

    def _fill_signal_table(self):
        self.tbl_signals.blockSignals(True)
        self.tbl_signals.setRowCount(0)
        book = self._template
        msg = None
        if book and self._selected_msg_id is not None:
            msg = book.messages.get(self._selected_msg_id)
        if not msg:
            self.lbl_sig_status.setText("未选中报文 — 请在上方报文表中选择一行")
            self.tbl_signals.blockSignals(False)
            return
        sigs = msg.signals
        self.tbl_signals.setRowCount(len(sigs))
        for r, s in enumerate(sigs):
            items = [
                _make_item(s.name, Qt.AlignLeft | Qt.AlignVCenter),
                _make_item(str(s.start_bit), Qt.AlignCenter, mono=True),
                _make_item(str(s.length), Qt.AlignCenter, mono=True),
                _make_item(s.byte_order, Qt.AlignCenter),
                _make_item("int" if s.signed else "uint", Qt.AlignCenter),
                _make_item(str(s.factor), Qt.AlignCenter, mono=True),
                _make_item(str(s.offset), Qt.AlignCenter, mono=True),
                _make_item(s.unit, Qt.AlignCenter),
                _make_item(s.note, Qt.AlignLeft | Qt.AlignVCenter),
            ]
            for c, item in enumerate(items):
                self.tbl_signals.setItem(r, c, item)
        self.lbl_sig_status.setText(
            f"0x{msg.msg_id:X}  {msg.name}  |  信号 {len(sigs)} 条  |  DLC={msg.expected_dlc}"
            f"  |  必须出现={'是' if msg.required else '否'}"
        )
        self.tbl_signals.blockSignals(False)

    def _on_sig_item_changed(self, item: QTableWidgetItem):
        if not self._template or self._selected_msg_id is None:
            return
        msg = self._template.messages.get(self._selected_msg_id)
        if not msg:
            return
        r = item.row()
        if r < 0 or r >= len(msg.signals):
            return
        sig = msg.signals[r]
        col = item.column()
        text = item.text().strip()
        try:
            if col == 0:
                sig.name = text
            elif col == 1:
                sig.start_bit = int(float(text))
            elif col == 2:
                sig.length = int(float(text))
            elif col == 3:
                sig.byte_order = text if text in ("Intel", "Motorola") else (
                    "Motorola" if text.lower().startswith("m") or text == "大端" else "Intel"
                )
            elif col == 4:
                sig.signed = text.lower() in ("int", "signed", "有符号", "sint")
            elif col == 5:
                sig.factor = float(text)
            elif col == 6:
                sig.offset = float(text)
            elif col == 7:
                sig.unit = text
            elif col == 8:
                sig.note = text
        except Exception as e:
            logger.debug(f"信号编辑无效: {e}")

    def _on_add_message(self):
        if not self._template:
            self._template = TemplateBook()
        self._read_message_table_to_template()
        new_id = 0x18FFFF00
        while new_id in self._template.messages:
            new_id += 1
        self._template.messages[new_id] = MessageTemplate(
            msg_id=new_id,
            name="新报文",
            expected_dlc=8,
            required=False,
            note="手动添加",
        )
        self._fill_message_table()
        self.tbl_template.selectRow(self.tbl_template.rowCount() - 1)

    def _on_del_message(self):
        rows = self.tbl_template.selectionModel().selectedRows() if self.tbl_template.selectionModel() else []
        if not rows:
            return
        self._read_message_table_to_template()
        r = rows[0].row()
        item = self.tbl_template.item(r, 0)
        if not item:
            return
        try:
            msg_id = int(item.text().replace("0x", ""), 16)
        except Exception:
            return
        self._template.messages.pop(msg_id, None)
        self._selected_msg_id = None
        self._fill_message_table()
        self._fill_signal_table()

    def _on_add_signal(self):
        if not self._template or self._selected_msg_id is None:
            QMessageBox.information(self, "添加信号", "请先在报文表中选中一条报文")
            return
        self._read_message_table_to_template()
        msg = self._template.messages.get(self._selected_msg_id)
        if not msg:
            return
        name = self.edt_sig_name.text().strip() or f"sig_{len(msg.signals)+1}"
        sig = SignalTemplate(
            msg_id=msg.msg_id,
            name=name,
            start_bit=self.spn_sig_start.value(),
            length=self.spn_sig_len.value(),
            byte_order=self.cmb_sig_order.currentText(),
            signed=self.cmb_sig_type.currentText() == "int",
            factor=self.spn_sig_factor.value(),
            offset=self.spn_sig_offset.value(),
            unit=self.edt_sig_unit.text().strip(),
            note=self.edt_sig_note.text().strip(),
        )
        msg.signals.append(sig)
        self._fill_message_table()
        self._fill_signal_table()

    def _on_del_signal(self):
        if not self._template or self._selected_msg_id is None:
            return
        msg = self._template.messages.get(self._selected_msg_id)
        if not msg:
            return
        rows = self.tbl_signals.selectionModel().selectedRows() if self.tbl_signals.selectionModel() else []
        if not rows:
            return
        indices = sorted((idx.row() for idx in rows), reverse=True)
        for r in indices:
            if 0 <= r < len(msg.signals):
                del msg.signals[r]
        self._fill_message_table()
        self._fill_signal_table()

    def _on_add_ids_from_log(self):
        frames = self._offline_frames
        if not frames:
            QMessageBox.warning(self, "补齐 ID", "请先导入离线 asc/blf 日志")
            return
        self._read_message_table_to_template()
        if not self._template:
            self._template = TemplateBook()
        added = 0
        for fr in frames:
            if fr.arbitration_id not in self._template.messages:
                self._template.messages[fr.arbitration_id] = MessageTemplate(
                    msg_id=fr.arbitration_id,
                    name=f"CAN_{fr.arbitration_id:X}",
                    expected_dlc=fr.dlc or 8,
                    required=False,
                    note="按实报补齐",
                )
                added += 1
        self._fill_message_table()
        QMessageBox.information(self, "补齐 ID", f"新增 {added} 个实报 ID（默认必须出现=否）")

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
        self.edt_log.setText(path)
        self.lbl_log_info.setText("报文：加载中…")
        self.btn_verify.setEnabled(False)
        self._load_thread = _LoadLogThread(path, self)
        self._load_thread.finished_ok.connect(self._on_log_loaded)
        self._load_thread.failed.connect(self._on_log_failed)
        self._load_thread.start()

    def _on_log_loaded(self, frames: List[CanFrame], path: str):
        self._offline_frames = frames
        self.btn_verify.setEnabled(True)
        unique = len({f.arbitration_id for f in frames})
        self.lbl_log_info.setText(
            f"报文：{len(frames)} 帧 / 唯一ID {unique}  |  {os.path.basename(path)}"
        )
        self.chk_use_live.setChecked(False)

    def _on_log_failed(self, err: str):
        self.btn_verify.setEnabled(True)
        self.lbl_log_info.setText("报文：加载失败")
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
        self.btn_live_start.setEnabled(False)
        self.btn_live_stop.setEnabled(True)
        self.chk_use_live.setChecked(True)
        self._live_timer.start()
        self.lbl_live_info.setText(f"实时：采集中  CH{ch} @ {baud}")

    def _on_live_stop(self):
        self._live_timer.stop()
        self._collector.stop()
        self.btn_live_start.setEnabled(True)
        self.btn_live_stop.setEnabled(False)
        self.lbl_live_info.setText(f"实时：已停止，累计 {len(self._live_frames)} 帧")

    def _on_live_clear(self):
        self._live_frames = []
        self._collector.take_frames()
        self.lbl_live_info.setText("实时：已清空")

    def _on_live_tick(self):
        frames = self._collector.take_frames()
        if frames:
            self._live_frames.extend(frames)
        self.lbl_live_info.setText(
            f"实时：采集中，累计 {len(self._live_frames)} 帧  |  "
            f"{self.cmb_channel.currentText()} @ {self.cmb_baud.currentText()}"
        )

    def cleanup(self):
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
        self._read_message_table_to_template()
        if not self._template or not self._template.messages:
            QMessageBox.warning(self, "协议核对", "请先导入 DBC/Excel，并应用模板")
            return
        use_live = self.chk_use_live.isChecked()
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

    def _on_clear_result(self):
        self._result = None
        self.lbl_stats.setText("尚未核对")
        self.txt_issues.clear()
        self.lbl_right_status.setText("尚未核对 — 导入日志并「开始核对」后显示")
        self._refresh_right_table()

    def _refresh_result_ui(self):
        r = self._result
        if not r:
            return
        self.lbl_stats.setText(r.summary_text)
        self.lbl_right_status.setText(
            f"已核对  |  {r.summary_text}"
        )
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
        self.tbl_right.setColumnWidth(0, _hex_col_width(ids, _FONT_MONO_BOLD, 104))
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
                item = _make_item(val, aligns[ci], mono=monos[ci])
                if level == "error":
                    item.setBackground(QColor("#fee2e2"))
                    if ci in (0, 6):
                        item.setForeground(QColor("#b91c1c"))
                elif level == "warn":
                    item.setBackground(QColor("#fef3c7"))
                    if ci in (0, 6):
                        item.setForeground(QColor("#b45309"))
                self.tbl_right.setItem(ri, ci, item)
        self.tbl_right.setSortingEnabled(True)
