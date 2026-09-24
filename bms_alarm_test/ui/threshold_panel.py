"""
阈值测试面板 (PyQt5)
布局与故障码测试同构：左配置+PID列表，右控制+详情。
回读验证与故障码测试共用引擎侧 BMSVerifier。
"""

import logging
import time
from typing import Optional, List, Dict, Any

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QSpinBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QTextEdit, QLineEdit, QSplitter, QCheckBox,
    QAbstractItemView, QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor

from shared.style import COLORS, FONTS
from bms_alarm_test.ui.panel_style import (
    compact_qss, table_qss, LeftAlignDelegate,
    BTN_PRIMARY, BTN_WARNING, BTN_SUCCESS, BTN_DANGER, BTN_NEUTRAL,
)
from bms_alarm_test.config.pid_table import PIDTable, PIDConfig
from bms_alarm_test.models.test_result import TestResult, CheckStatus

logger = logging.getLogger(__name__)

_PID_ROLE = Qt.UserRole + 1
_LEVEL_ROLE = Qt.UserRole + 2

# 引擎 ThresholdTestState → 界面中文（与故障码测试风格一致）
TEST_STATE_CN = {
    "idle": "就绪",
    "preparing": "准备中",
    "reading_env": "读取环境值",
    "setting": "下发阈值",
    "verifying": "验证中",
    "releasing": "恢复阈值",
    "completed": "已完成",
    "failed": "失败",
}


def _state_cn(state) -> str:
    if state is None:
        return "就绪"
    key = getattr(state, "value", None) or str(state)
    key = str(key).lower()
    return TEST_STATE_CN.get(key, str(key))


class ThresholdTestPanel(QWidget):
    """阈值测试面板"""

    test_started = pyqtSignal()
    test_stopped = pyqtSignal()
    test_completed = pyqtSignal(list)

    _sig_progress = pyqtSignal(object)
    _sig_result = pyqtSignal(object)
    _sig_complete = pyqtSignal(list)
    _sig_oper_done = pyqtSignal(object)

    def __init__(self, pid_table: Optional[PIDTable] = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(compact_qss())
        self.pid_table = pid_table
        self.threshold_engine = None
        self._test_logger = None
        self._can_manager = None
        self._row_index: Dict[tuple, int] = {}  # (pid, level) -> row
        self.test_results: List[TestResult] = []
        self._oper_buttons: Dict[tuple, List[QPushButton]] = {}

        self.setup_ui()
        self.setup_connections()

        if self.pid_table and self.pid_table.is_loaded():
            self.refresh_pid_list()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # 左：配置 + PID列表（优先保证列表横向完整）
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(self.create_config_group(), 0)
        left.addWidget(self.create_pid_list_group(), 1)
        left_c = QWidget()
        left_c.setLayout(left)
        left_c.setMinimumWidth(460)
        root.addWidget(left_c, 3)

        # 右：控制 + 详情（控制区竖向：按钮→进度条→状态横排）
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(self.create_control_group(), 0)
        right.addWidget(self.create_detail_group(), 1)
        right_c = QWidget()
        right_c.setLayout(right)
        root.addWidget(right_c, 2)

    def create_config_group(self) -> QGroupBox:
        group = QGroupBox("阈值测试配置")
        layout = QGridLayout()

        layout.addWidget(QLabel("BMS地址:"), 0, 0)
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(1, 255)
        self.addr_spin.setValue(161)
        layout.addWidget(self.addr_spin, 0, 1)

        layout.addWidget(QLabel("域类型:"), 0, 2)
        self.domain_combo = QComboBox()
        self.domain_combo.addItems(["NBCMU", "SBCMU"])
        layout.addWidget(self.domain_combo, 0, 3)

        layout.addWidget(QLabel("测试类型:"), 1, 0)
        self.test_type_combo = QComboBox()
        self.test_type_combo.addItems(["上限测试", "下限测试", "上下限测试"])
        self.test_type_combo.setCurrentText("上下限测试")
        layout.addWidget(self.test_type_combo, 1, 1, 1, 3)

        layout.addWidget(QLabel("阈值偏移:"), 2, 0)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setDecimals(2)
        self.offset_spin.setRange(0.01, 10000.0)
        self.offset_spin.setValue(1.0)
        layout.addWidget(self.offset_spin, 2, 1)

        layout.addWidget(QLabel("报警等待(s):"), 2, 2)
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(1, 60)
        self.wait_spin.setValue(5)
        layout.addWidget(self.wait_spin, 2, 3)

        group.setLayout(layout)
        return group

    def create_pid_list_group(self) -> QGroupBox:
        group = QGroupBox("PID列表")
        layout = QVBoxLayout()

        bar = QHBoxLayout()
        for text, slot in (
            ("全选", self.select_all_pids),
            ("全不选", self.select_none_pids),
            ("反选", self.invert_selection),
            ("刷新", self.refresh_pid_list),
        ):
            btn = QPushButton(text)
            btn.setStyleSheet(BTN_NEUTRAL)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("PID / 名称")
        self.search_edit.textChanged.connect(self.filter_pid_list)
        bar.addWidget(self.search_edit, 1)
        layout.addLayout(bar)

        self.pid_table_widget = QTableWidget()
        self.pid_table_widget.setColumnCount(12)
        self.pid_table_widget.setHorizontalHeaderLabels([
            "选择", "PID", "名称", "告警使能", "确认时间",
            "上限", "下限", "充放等级", "精度", "状态", "设置故障", "清除故障",
        ])
        self.pid_table_widget.verticalHeader().setVisible(False)
        self.pid_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pid_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.pid_table_widget.horizontalHeader()
        header.setMinimumSectionSize(0)
        # 自适应列宽：按内容/权重分配，避免 PID 列表被挤得显示不全
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self._pid_column_weights = [0.6, 0.95, 2.1, 0.9, 0.9, 0.85, 0.85, 1.0, 0.75, 0.8, 1.15, 1.15]
        self._pid_column_min_widths = [48, 68, 130, 70, 70, 64, 64, 80, 64, 70, 88, 88]
        layout.addWidget(self.pid_table_widget, 1)
        LeftAlignDelegate.attach(self.pid_table_widget, [2], self.pid_table_widget)
        group.setLayout(layout)
        return group

    def create_control_group(self) -> QGroupBox:
        """阈值测试控制：按钮行 + 通栏进度条 + 状态横排（与故障码测试一致）"""
        from PyQt5.QtWidgets import QSizePolicy

        group = QGroupBox("阈值测试控制")
        outer = QVBoxLayout()
        outer.setSpacing(6)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_start = QPushButton("开始阈值测试")
        self.btn_start.setStyleSheet(BTN_PRIMARY)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_test)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setStyleSheet(BTN_DANGER)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_test)
        self.btn_step = QPushButton("单步测试")
        self.btn_step.setStyleSheet(BTN_WARNING)
        self.btn_step.setCursor(Qt.PointingHandCursor)
        self.btn_step.clicked.connect(self.step_test)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_step)
        btns.addStretch(1)
        outer.addLayout(btns)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("0%")
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setMaximumHeight(28)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                text-align: center;
                font-size: 12px;
                background-color: {COLORS['bg_panel']};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent']};
                border-radius: 3px;
            }}
            """
        )
        outer.addWidget(self.progress_bar)

        # 状态横排：徽章 + 进度说明 + 统计（占满进度条下一行，少占竖向空间）
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self.state_badge = QLabel("就绪")
        self.state_badge.setFixedWidth(88)
        self.state_badge.setFixedHeight(24)
        self.state_badge.setAlignment(Qt.AlignCenter)
        self.state_badge.setStyleSheet(
            f"background-color: {COLORS['border']}; color: {COLORS['text']}; "
            f"border-radius: 3px; padding: 2px 6px; font-weight: bold; font-size: 12px;"
        )
        info_row.addWidget(self.state_badge)

        self.progress_label = QLabel("状态=就绪 | 进度: 0/0 | —")
        self.progress_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        info_row.addWidget(self.progress_label, 1)

        self.stat_label = QLabel("通过: 0  失败: 0")
        self.stat_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        info_row.addWidget(self.stat_label)
        outer.addLayout(info_row)

        group.setLayout(outer)
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return group

    def _set_state_badge(self, state_name: str, failed: int = 0):
        if state_name in ("失败",) or (failed > 0 and state_name == "已完成"):
            bg, fg = COLORS.get("error", "#dc2626"), "#ffffff"
        elif state_name == "已完成":
            bg, fg = COLORS.get("success", "#059669"), "#ffffff"
        elif state_name == "已停止":
            bg, fg = COLORS.get("warning", "#d97706"), "#ffffff"
        elif state_name == "就绪":
            bg, fg = COLORS.get("border", "#e5e7eb"), COLORS.get("text", "#111827")
        else:
            bg, fg = COLORS.get("accent", "#2563eb"), "#ffffff"
        self.state_badge.setText(state_name)
        self.state_badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 3px; "
            f"padding: 2px 6px; font-weight: bold; font-size: 12px;"
        )

    def create_detail_group(self) -> QGroupBox:
        group = QGroupBox("测试详情")
        layout = QVBoxLayout()
        splitter = QSplitter(Qt.Vertical)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("实时日志")
        splitter.addWidget(self.log_text)

        self.param_table = QTableWidget()
        self.param_table.setColumnCount(7)
        self.param_table.setHorizontalHeaderLabels([
            "参数", "原始值", "设置值", "实际报警值", "报警状态", "解除值", "测试结果",
        ])
        self.param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.setStyleSheet(
            table_qss()
            + "\nQTableWidget { font-size: 12px; }"
            + "\nQTableWidget::item { padding: 6px 8px; }"
        )
        LeftAlignDelegate.attach(self.param_table, [0, 2, 5], self.param_table)
        splitter.addWidget(self.param_table)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        group.setLayout(layout)
        return group

    def setup_connections(self):
        self.domain_combo.currentTextChanged.connect(self._on_domain_changed)
        self.test_type_combo.currentTextChanged.connect(self.on_test_type_changed)
        self._sig_progress.connect(self.on_progress_update)
        self._sig_result.connect(self.on_test_result)
        self._sig_complete.connect(self.on_test_complete)
        self._sig_oper_done.connect(self._on_fault_oper_done)

    def _on_domain_changed(self, text: str):
        if text == "NBCMU":
            self.addr_spin.setValue(161)
        else:
            self.addr_spin.setValue(177)

    # ------------------------------------------------------------------
    # 注入依赖
    # ------------------------------------------------------------------
    def set_threshold_engine(self, threshold_engine):
        self.threshold_engine = threshold_engine
        if not threshold_engine:
            return
        self._can_manager = getattr(threshold_engine, "can_manager", None)
        try:
            threshold_engine.set_callbacks(
                on_progress_update=lambda p: self._sig_progress.emit(p),
                on_test_result=lambda r: self._sig_result.emit(r),
                on_test_complete=lambda rs: self._sig_complete.emit(rs),
            )
        except Exception as e:
            logger.error(f"绑定阈值引擎回调失败: {e}")

    def set_test_logger(self, test_logger):
        self._test_logger = test_logger

    def set_pid_table(self, pid_table: PIDTable):
        self.pid_table = pid_table
        self.refresh_pid_list()

    # ------------------------------------------------------------------
    # PID 列表
    # ------------------------------------------------------------------
    @staticmethod
    def _infer_pid_test_type(pid: PIDConfig) -> str:
        name = (pid.alarm_category or "")
        lower_kw = ("过低", "偏低", "不足", "欠压")
        upper_kw = ("过高", "过大", "偏高", "过温", "超温")
        if any(k in name for k in lower_kw):
            return "下限"
        if any(k in name for k in upper_kw):
            return "上限"
        t1, t3 = pid.level1_threshold, pid.level3_threshold
        if t1 is not None and t3 is not None:
            return "上限" if t1 <= t3 else "下限"
        return "上下限"

    @staticmethod
    def _format_threshold(value) -> str:
        if value is None:
            return "—"
        return f"{value:g}"

    @staticmethod
    def _format_mature_time(value) -> str:
        if value is None:
            return "—"
        return f"{value:g}"

    @staticmethod
    def _format_precision(pid: PIDConfig) -> str:
        prec = pid.precision
        unit = pid.unit or ""
        if prec is None:
            return unit or "—"
        return f"{prec:g}{unit}"

    def _make_checkbox(self) -> QCheckBox:
        cb = QCheckBox()
        cb.setChecked(True)
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(cb)
        wrapper.checkbox = cb
        return wrapper

    @staticmethod
    def _get_checkbox(table: QTableWidget, row: int) -> Optional[QCheckBox]:
        w = table.cellWidget(row, 0)
        return getattr(w, "checkbox", None) if w else None

    @staticmethod
    def _charge_level_hint(pid: PIDConfig, level: int) -> str:
        hx = getattr(pid, "threshold_hex", None)
        if not hx or len(hx) < 17:
            return "—"
        idx = {3: 6, 2: 11, 1: 16}.get(level)
        if idx is None:
            return "—"
        return str(hx[idx])

    def refresh_pid_list(self):
        table = self.pid_table_widget
        table.setRowCount(0)
        self._row_index.clear()
        self._oper_buttons.clear()
        if not self.pid_table or not self.pid_table.is_loaded():
            self.log_message("错误: PID表未加载", "ERROR")
            return

        rows = self.pid_table.get_level_rows()
        test_type_filter = self.test_type_combo.currentText()
        table.setRowCount(len(rows))
        for i, (pid, level, threshold) in enumerate(rows):
            inferred = self._infer_pid_test_type(pid)
            # 行隐藏过滤在 filter / test_type 中处理
            wrapper = self._make_checkbox()
            table.setCellWidget(i, 0, wrapper)

            pid_item = QTableWidgetItem(f"0x{pid.pid:04X}")
            pid_item.setData(_PID_ROLE, pid.pid)
            pid_item.setData(_LEVEL_ROLE, level)
            pid_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 1, pid_item)

            name_item = QTableWidgetItem(f"{pid.alarm_category} {level}级")
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(i, 2, name_item)

            en_item = QTableWidgetItem(str(pid.alarm_enable))
            en_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 3, en_item)

            mature_item = QTableWidgetItem(self._format_mature_time(pid.mature_time))
            mature_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 4, mature_item)

            upper = pid.level3_threshold if inferred != "下限" else None
            lower = pid.level1_threshold if inferred != "上限" else None
            # 显示该级阈值
            up_item = QTableWidgetItem(self._format_threshold(
                threshold if inferred in ("上限", "上下限") and threshold is not None else None
            ))
            lo_item = QTableWidgetItem(self._format_threshold(
                threshold if inferred in ("下限", "上下限") and threshold is not None else (
                    threshold if inferred == "下限" else None
                )
            ))
            if inferred == "上限":
                up_item = QTableWidgetItem(self._format_threshold(threshold))
                lo_item = QTableWidgetItem("—")
            elif inferred == "下限":
                up_item = QTableWidgetItem("—")
                lo_item = QTableWidgetItem(self._format_threshold(threshold))
            else:
                up_item = QTableWidgetItem(self._format_threshold(threshold))
                lo_item = QTableWidgetItem(self._format_threshold(threshold))
            up_item.setTextAlignment(Qt.AlignCenter)
            lo_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 5, up_item)
            table.setItem(i, 6, lo_item)

            chg = QTableWidgetItem(self._charge_level_hint(pid, level))
            chg.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 7, chg)

            prec = QTableWidgetItem(self._format_precision(pid))
            prec.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 8, prec)

            status = QTableWidgetItem("待测试")
            status.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 9, status)

            btn_set = QPushButton("设置")
            btn_set.setStyleSheet(BTN_PRIMARY)
            btn_clr = QPushButton("清除")
            btn_clr.setStyleSheet(BTN_NEUTRAL)
            key = (pid.pid, level)
            btn_set.clicked.connect(lambda _, r=i, k=key: self._operate_fault(r, "set", k[1]))
            btn_clr.clicked.connect(lambda _, r=i, k=key: self._operate_fault(r, "clear", k[1]))
            table.setCellWidget(i, 10, btn_set)
            table.setCellWidget(i, 11, btn_clr)
            self._oper_buttons[key] = [btn_set, btn_clr]
            self._row_index[key] = i

        self.filter_pid_list()
        self.log_message(f"已加载 PID 等级行: {len(rows)}（默认全部勾选）")
        self._resize_pid_columns()

    def _resize_pid_columns(self):
        """PID 列表列宽自适应：优先保证名称/阈值等列完整显示"""
        table = getattr(self, "pid_table_widget", None)
        if table is None:
            return
        viewport_width = table.viewport().width()
        if viewport_width <= 0:
            viewport_width = max(520, table.width())
        minimums = self._pid_column_min_widths
        weights = self._pid_column_weights
        minimum_total = sum(minimums)
        if viewport_width <= minimum_total:
            widths = minimums[:]
        else:
            extra = viewport_width - minimum_total
            weight_total = sum(weights) or 1
            widths = [
                minimum + int(extra * weight / weight_total)
                for minimum, weight in zip(minimums, weights)
            ]
            widths[-1] += viewport_width - sum(widths)
        header = table.horizontalHeader()
        for column, width in enumerate(widths):
            header.resizeSection(column, max(1, width))

    def filter_pid_list(self):
        keyword = (self.search_edit.text() or "").strip().lower()
        test_type = self.test_type_combo.currentText()
        table = self.pid_table_widget
        for row in range(table.rowCount()):
            pid_item = table.item(row, 1)
            name_item = table.item(row, 2)
            if not pid_item:
                continue
            pid_val = pid_item.data(_PID_ROLE)
            level = pid_item.data(_LEVEL_ROLE)
            pid_cfg = self.pid_table.get_pid_by_code(pid_val) if self.pid_table else None
            show = True
            if keyword:
                pid_text = (pid_item.text() or "").lower()
                name_text = (name_item.text() if name_item else "").lower()
                show = keyword in pid_text or keyword in name_text
            if show and pid_cfg and test_type in ("上限测试", "下限测试"):
                inferred = self._infer_pid_test_type(pid_cfg)
                if test_type == "上限测试" and inferred == "下限":
                    show = False
                elif test_type == "下限测试" and inferred == "上限":
                    show = False
            table.setRowHidden(row, not show)

    def on_test_type_changed(self, _text: str):
        self.filter_pid_list()

    def select_all_pids(self):
        for row in range(self.pid_table_widget.rowCount()):
            cb = self._get_checkbox(self.pid_table_widget, row)
            if cb and not self.pid_table_widget.isRowHidden(row):
                cb.setChecked(True)

    def select_none_pids(self):
        for row in range(self.pid_table_widget.rowCount()):
            cb = self._get_checkbox(self.pid_table_widget, row)
            if cb:
                cb.setChecked(False)

    def invert_selection(self):
        for row in range(self.pid_table_widget.rowCount()):
            cb = self._get_checkbox(self.pid_table_widget, row)
            if cb:
                cb.setChecked(not cb.isChecked())

    def get_selected_pid_codes(self) -> List[str]:
        """按 PID 合并选择，返回如 ["0xF001", ...]"""
        selected = []
        seen = set()
        for row in range(self.pid_table_widget.rowCount()):
            cb = self._get_checkbox(self.pid_table_widget, row)
            if not cb or not cb.isChecked():
                continue
            item = self.pid_table_widget.item(row, 1)
            if not item:
                continue
            pid_val = item.data(_PID_ROLE)
            if pid_val is None:
                continue
            code = f"0x{int(pid_val):04X}"
            if code not in seen:
                seen.add(code)
                selected.append(code)
        return selected

    def _check_can_connected(self) -> bool:
        if not self._can_manager or not self._can_manager.is_connected():
            self.log_message("错误: CAN 未连接，请先连接 CAN 后再开始测试", "ERROR")
            return False
        return True

    def _test_type_key(self) -> str:
        text = self.test_type_combo.currentText()
        return {"上限测试": "upper", "下限测试": "lower", "上下限测试": "both"}.get(text, "both")

    def _current_config(self):
        return {
            "target_address": self.addr_spin.value(),
            "domain": self.domain_combo.currentText(),
            "test_type": self._test_type_key(),
            "offset_value": self.offset_spin.value(),
            "alarm_wait_time_sec": float(self.wait_spin.value()),
        }

    # ------------------------------------------------------------------
    # 测试控制
    # ------------------------------------------------------------------
    def start_test(self):
        if not self.threshold_engine:
            self.log_message("错误: 阈值测试引擎未设置", "ERROR")
            return
        if not self._check_can_connected():
            return
        codes = self.get_selected_pid_codes()
        if not codes:
            self.log_message("错误: 请先勾选 PID", "ERROR")
            return
        cfg = self._current_config()
        ok = self.threshold_engine.start_test(pid_codes=codes, **cfg)
        if not ok:
            self.log_message("阈值测试启动失败，请查看日志", "ERROR")
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_step.setEnabled(False)
        self.progress_bar.setMaximum(max(1, len(codes)))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0%  (0/{len(codes)})")
        self._set_state_badge("准备中")
        self.stat_label.setText("通过: 0  失败: 0")
        self.progress_label.setText(f"状态=准备中 | 进度: 0/{len(codes)} | —")
        self.test_started.emit()
        self.log_message(f"开始阈值测试: {len(codes)} 个PID, {cfg}")

    def stop_test(self):
        if self.threshold_engine:
            self.threshold_engine.stop_test()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_step.setEnabled(True)
        self._set_state_badge("已停止")
        self.progress_label.setText(
            f"状态=已停止 | 进度: {self.progress_bar.value()}/{self.progress_bar.maximum()} | —"
        )
        self.log_message("测试已停止", "INFO")
        self.test_stopped.emit()

    def step_test(self):
        if not self.threshold_engine:
            self.log_message("错误: 阈值测试引擎未设置", "ERROR")
            return
        if not self._check_can_connected():
            return
        codes = self.get_selected_pid_codes()
        if not codes:
            self.log_message("错误: 请先勾选 PID", "ERROR")
            return
        cfg = self._current_config()
        self.btn_step.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.log_message(f"单步测试: {codes[0]}")

        def worker():
            try:
                result = self.threshold_engine.run_single_pid(codes[0], **cfg)
                self._sig_result.emit(result)
                if result:
                    self._sig_complete.emit([result])
            except Exception as e:
                self.log_message(f"单步测试异常: {e}", "ERROR")
                self._sig_complete.emit([])

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _operate_fault(self, row: int, op: str, level: int):
        if not self.threshold_engine:
            self.log_message("错误: 阈值测试引擎未设置", "ERROR")
            return
        if not self._check_can_connected():
            return
        item = self.pid_table_widget.item(row, 1)
        if not item:
            return
        pid_val = item.data(_PID_ROLE)
        pid_code = f"0x{int(pid_val):04X}"
        cfg = self._current_config()
        buttons = self._oper_buttons.get((pid_val, level), [])
        for b in buttons:
            b.setEnabled(False)

        def worker():
            ok = False
            try:
                if op == "set":
                    r = self.threshold_engine.set_fault_by_threshold(
                        pid_code, level,
                        cfg["target_address"], cfg["domain"], cfg["offset_value"],
                    )
                    ok = bool(r and r.overall_status == CheckStatus.PASSED)
                else:
                    ok = self.threshold_engine.clear_fault_by_threshold(
                        pid_code, cfg["target_address"], cfg["domain"], cfg["offset_value"],
                    )
            except Exception as e:
                logger.error(f"阈值操作异常: {e}")
            self._sig_oper_done.emit({
                "row": row, "op": op, "ok": ok,
                "pid": pid_val, "level": level, "pid_code": pid_code,
            })

        import threading
        threading.Thread(target=worker, daemon=True).start()

    @pyqtSlot(object)
    def _on_fault_oper_done(self, data: dict):
        row = data.get("row", -1)
        key = (data.get("pid"), data.get("level"))
        for b in self._oper_buttons.get(key, []):
            b.setEnabled(True)
        ok = data.get("ok")
        msg = f"[{'设置' if data.get('op')=='set' else '清除'}] {data.get('pid_code')} L{data.get('level')}: {'成功' if ok else '失败'}"
        self.log_message(msg, "INFO" if ok else "ERROR")
        if 0 <= row < self.pid_table_widget.rowCount():
            item = self.pid_table_widget.item(row, 9)
            if item:
                item.setText("成功" if ok else "失败")
                item.setForeground(QColor(COLORS["success"] if ok else COLORS["error"]))

    # ------------------------------------------------------------------
    # 回调
    # ------------------------------------------------------------------
    @pyqtSlot(object)
    def on_progress_update(self, progress):
        total = max(1, getattr(progress, "total", 1) or 1)
        current = getattr(progress, "current_index", 0) or 0
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(min(current, total))
        if total > 0:
            pct = int(round(100.0 * min(current, total) / total))
            self.progress_bar.setFormat(f"{pct}%  ({current}/{total})")
        else:
            self.progress_bar.setFormat("0%")

        pid = getattr(progress, "current_pid", "") or "—"
        level = getattr(progress, "current_level", None)
        state_name = _state_cn(getattr(progress, "current_state", None))
        pid_txt = f"PID={pid}" if pid and pid != "—" else "PID=—"
        if level is not None:
            pid_txt += f" L{level}"
        passed = getattr(progress, "passed_count", 0) or 0
        failed = getattr(progress, "failed_count", 0) or 0
        self._set_state_badge(state_name, failed=failed)
        self.stat_label.setText(f"通过: {passed}  失败: {failed}")
        self.progress_label.setText(
            f"状态={state_name} | 进度: {current}/{total} | {pid_txt}"
        )

    @pyqtSlot(object)
    def on_test_result(self, result: TestResult):
        if not result:
            return
        self.test_results.append(result)
        status = result.overall_status
        status_text = status.value if status else "未知"
        self.log_message(
            f"[结果] {getattr(result, 'pid_name', '')} "
            f"{getattr(result, 'fault_name', '')}: {status_text}"
        )
        self.update_pid_table_status(result)
        self.update_param_table(result)

    @pyqtSlot(list)
    def on_test_complete(self, results: list):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_step.setEnabled(True)
        passed = sum(1 for r in results or [] if getattr(r, "is_passed", None) and r.is_passed())
        failed = len(results or []) - passed
        total = max(1, self.progress_bar.maximum())
        if self.progress_bar.value() < total:
            self.progress_bar.setValue(total)
        self.progress_bar.setFormat("100%")
        self._set_state_badge("已完成", failed=failed)
        self.stat_label.setText(f"通过: {passed}  失败: {failed}")
        self.progress_label.setText(
            f"状态=已完成 | 进度: {self.progress_bar.value()}/{total}"
        )
        self.log_message(f"阈值测试完成，共 {len(results or [])} 条 PID 结果")
        self._save_results(results or [])
        self.test_completed.emit(results or [])

    def _save_results(self, results: list):
        if not self._test_logger or not results:
            return
        try:
            self._test_logger.log_test_batch(results, test_type="threshold")
        except Exception as e:
            self.log_message(f"保存阈值测试报告失败: {e}", "ERROR")

    def update_pid_table_status(self, result: TestResult):
        meta = getattr(result, "metadata", {}) or {}
        pid_hex = meta.get("pid")
        if not pid_hex:
            return
        try:
            pid_val = int(str(pid_hex), 16) if isinstance(pid_hex, str) else int(pid_hex)
        except (TypeError, ValueError):
            return
        levels_raw = str(meta.get("levels") or meta.get("level") or "")
        status_text = "成功" if result.is_passed() else "失败"
        color = QColor(COLORS["success"] if result.is_passed() else COLORS["error"])
        levels = []
        for part in levels_raw.split(","):
            part = part.strip()
            if part.isdigit():
                levels.append(int(part))
        if not levels:
            # 按该 PID 所有已知行更新
            for (p, lv), row in self._row_index.items():
                if p == pid_val:
                    item = self.pid_table_widget.item(row, 9)
                    if item:
                        item.setText(status_text)
                        item.setForeground(color)
            return
        for lv in levels:
            row = self._row_index.get((pid_val, lv))
            if row is None:
                continue
            item = self.pid_table_widget.item(row, 9)
            if item:
                item.setText(status_text)
                item.setForeground(color)

    def update_param_table(self, result: TestResult):
        table = self.param_table
        row = table.rowCount()
        table.insertRow(row)
        pid_name = getattr(result, "pid_name", "") or ""
        checks = getattr(result, "checks", []) or []
        env_val = ""
        set_val = ""
        alarm_val = ""
        alarm_st = ""
        release_val = ""
        for c in checks:
            n = c.name or ""
            if "环境" in n:
                env_val = str(c.actual_value if c.actual_value is not None else "")
            elif "阈值设置" in n:
                set_val = c.message or str(c.expected_value or "")
            elif "阈值恢复" in n or "解除" in n:
                release_val = c.message or str(c.actual_value or "")
            elif c.check_type and "验证" in getattr(c.check_type, "value", ""):
                alarm_val = str(c.actual_value if c.actual_value is not None else "")
                alarm_st = c.status.value if c.status else ""
            elif c.check_type and "对外" in getattr(c.check_type, "value", ""):
                alarm_val = str(c.actual_value if c.actual_value is not None else "")
                alarm_st = c.status.value if c.status else ""

        values = [
            pid_name,
            env_val,
            set_val,
            alarm_val,
            alarm_st or (result.overall_status.value if result.overall_status else ""),
            release_val,
            result.overall_status.value if result.overall_status else "",
        ]
        left = Qt.AlignLeft | Qt.AlignVCenter
        center = Qt.AlignCenter
        # 参数名左对齐；数值/状态类短字段居中
        col_aligns = [left, center, left, center, center, left, center]
        for col, val in enumerate(values):
            item = QTableWidgetItem(str(val))
            item.setTextAlignment(col_aligns[col] if col < len(col_aligns) else left)
            if col == 6:
                if result.is_passed():
                    item.setForeground(QColor(COLORS["success"]))
                else:
                    item.setForeground(QColor(COLORS["error"]))
            table.setItem(row, col, item)
        table.scrollToBottom()

    def log_message(self, message: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        self.log_text.append(line)
        try:
            if level == "ERROR":
                logger.error(message)
            elif level == "WARNING":
                logger.warning(message)
            else:
                logger.info(message)
        except Exception:
            pass

    def reset(self):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self._set_state_badge("就绪")
        if hasattr(self, "stat_label"):
            self.stat_label.setText("通过: 0  失败: 0")
        self.progress_label.setText("状态=就绪 | 进度: 0/0 | —")
        for row in range(self.pid_table_widget.rowCount()):
            item = self.pid_table_widget.item(row, 9)
            if item:
                item.setText("待测试")
                item.setForeground(QColor(COLORS["text"]))
        self.log_message("面板已重置")
        self._resize_pid_columns()

    def cleanup(self):
        if self.threshold_engine:
            try:
                self.threshold_engine.stop_test()
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        if self.pid_table and self.pid_table.is_loaded() and self.pid_table_widget.rowCount() == 0:
            self.refresh_pid_list()
        self._resize_pid_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_pid_columns()
