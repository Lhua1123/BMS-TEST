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
    QAbstractItemView, QDoubleSpinBox, QInputDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor

from shared.style import COLORS, FONTS, themed_qss, on_theme_changed
from bms_alarm_test.ui.panel_style import (
    compact_qss, table_qss, LeftAlignDelegate, RowButton,
    btn_primary, btn_warning, btn_success, btn_danger, btn_neutral,
    button_fixed_size_qss,
)
from bms_alarm_test.config.pid_table import PIDTable, PIDConfig
from bms_alarm_test.models.test_result import TestResult, CheckStatus, CheckType

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


class _ElidedLabel(QLabel):
    """单行省略 QLabel：QLabel 没有 setTextElideMode，超宽时用 fontMetrics 手动 elide。"""
    def __init__(self, text: str = "", parent=None):
        self._full_text = text or ""
        super().__init__(text, parent)
        self.setWordWrap(False)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._update_elided()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided()

    def _update_elided(self) -> None:
        full = getattr(self, "_full_text", "")
        width = self.width() - 4
        if width <= 0:
            super().setText(full)
            return
        elided = self.fontMetrics().elidedText(full, Qt.ElideRight, max(0, width))
        super().setText(elided)
        self.setToolTip(full)


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
        themed_qss(self, compact_qss)
        on_theme_changed(self._on_theme_changed)
        self.pid_table = pid_table
        self.threshold_engine = None
        self._test_logger = None
        self._last_project_name = ""
        self._current_project_name = ""
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
        root.addWidget(left_c, 2)

        # 右：控制 + 详情（控制区竖向：按钮→进度条→状态横排）
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(self.create_control_group(), 0)
        right.addWidget(self.create_detail_group(), 1)
        right_c = QWidget()
        right_c.setLayout(right)
        root.addWidget(right_c, 3)

    def create_config_group(self) -> QGroupBox:
        from PyQt5.QtWidgets import QSizePolicy

        group = QGroupBox("阈值测试配置")
        layout = QGridLayout()
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        # 输入列均分整行宽度，避免控件挤在左侧
        for col in (1, 3, 5):
            layout.setColumnStretch(col, 1)

        def _fill(widget, min_w: int):
            widget.setMinimumWidth(min_w)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return widget

        # 第一行：地址 + 域类型 + 测试类型
        layout.addWidget(QLabel("BMS地址:"), 0, 0)
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(1, 255)
        self.addr_spin.setValue(161)
        layout.addWidget(_fill(self.addr_spin, 90), 0, 1)

        layout.addWidget(QLabel("域类型:"), 0, 2)
        self.domain_combo = QComboBox()
        self.domain_combo.addItems(["NBCMU", "SBCMU"])
        layout.addWidget(_fill(self.domain_combo, 120), 0, 3)

        layout.addWidget(QLabel("测试类型:"), 0, 4)
        self.test_type_combo = QComboBox()
        self.test_type_combo.addItems(["上限测试", "下限测试", "上下限测试"])
        self.test_type_combo.setCurrentText("上下限测试")
        layout.addWidget(_fill(self.test_type_combo, 120), 0, 5)

        # 第二行：阈值偏移 + 报警等待
        layout.addWidget(QLabel("阈值偏移:"), 1, 0)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setDecimals(2)
        self.offset_spin.setRange(0.01, 10000.0)
        self.offset_spin.setValue(1.0)
        layout.addWidget(_fill(self.offset_spin, 90), 1, 1)

        layout.addWidget(QLabel("报警等待(s):"), 1, 2)
        self.wait_spin = QSpinBox()
        self.wait_spin.setRange(1, 60)
        self.wait_spin.setValue(5)
        layout.addWidget(_fill(self.wait_spin, 90), 1, 3)

        group.setLayout(layout)
        return group

    def create_pid_list_group(self) -> QGroupBox:
        group = QGroupBox("PID列表")
        layout = QVBoxLayout()

        bar = QHBoxLayout()
        for text, slot, style in (
            ("全选", self.select_all_pids, btn_primary),
            ("全不选", self.select_none_pids, btn_primary),
            ("反选", self.invert_selection, btn_primary),
            ("重置列表", self.refresh_pid_list, btn_warning),
        ):
            btn = QPushButton(text)
            themed_qss(btn, style)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("PID / 名称")
        self.search_edit.setFixedHeight(34)  # 与同排按钮等高
        self.search_edit.textChanged.connect(self.filter_pid_list)
        bar.addWidget(self.search_edit, 1)
        layout.addLayout(bar)

        self.pid_table_widget = QTableWidget()
        self.pid_table_widget.setColumnCount(8)
        self.pid_table_widget.setHorizontalHeaderLabels([
            "选择", "PID", "名称", "告警使能", "确认时间", "状态", "设置", "清除",
        ])
        self.pid_table_widget.verticalHeader().setVisible(False)
        self.pid_table_widget.verticalHeader().setDefaultSectionSize(38)  # 与故障码列表一致
        # 与故障码列表同一套字号/内边距，保证两边观感一致
        # item 内边距会一起压缩单元格控件区域，把行内按钮裁掉，故设为 0
        themed_qss(self.pid_table_widget, lambda: (
            table_qss()
            + "\nQTableWidget { font-size: 12px; }"
            + "\nQTableWidget::item { padding: 0px; }"
            + "\nQHeaderView::section { font-size: 12px; padding: 7px 8px; }"
        ))
        self.pid_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pid_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.pid_table_widget.horizontalHeader()
        header.setMinimumSectionSize(0)
        # 自适应列宽：按内容/权重分配，避免 PID 列表被挤得显示不全
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self._pid_column_weights = [0.6, 0.95, 2.1, 0.9, 0.9, 0.85, 0.85, 0.85]
        self._pid_column_min_widths = [44, 56, 110, 56, 56, 56, 84, 84]
        layout.addWidget(self.pid_table_widget, 1)
        LeftAlignDelegate.attach(self.pid_table_widget, [2], self.pid_table_widget)
        group.setLayout(layout)
        return group

    def create_control_group(self) -> QGroupBox:
        """阈值测试控制：按钮行 + 通栏进度条 + 状态横排（与故障码测试一致）"""
        from PyQt5.QtWidgets import QSizePolicy

        # 记录上次徽章样式，避免重复 setStyleSheet 触发重绘/抖动
        self._badge_style_cache = None

        group = QGroupBox("阈值测试控制")
        outer = QVBoxLayout()
        outer.setSpacing(6)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_start = QPushButton("开始")
        themed_qss(self.btn_start, btn_primary)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_test)
        self.btn_stop = QPushButton("停止")
        themed_qss(self.btn_stop, btn_danger)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_test)
        self.btn_step = QPushButton("单步测试")
        themed_qss(self.btn_step, btn_warning)
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
        themed_qss(self.progress_bar, lambda: (
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
        ))
        outer.addWidget(self.progress_bar)

        # 状态横排：徽章 + 进度说明 + 统计（占满进度条下一行，少占竖向空间）
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self.state_badge = QLabel("就绪")
        self.state_badge.setFixedSize(88, 24)  # 基准尺寸；长状态在 _set_state_badge 里按文字加宽防截断
        self.state_badge.setAlignment(Qt.AlignCenter)
        self._badge_args = None  # (状态名, 失败数)；None 时即「就绪」样式
        self.state_badge.setStyleSheet(self._badge_qss())
        info_row.addWidget(self.state_badge)

        # 状态信息单行 + 超宽省略号（ElideRight），与故障码测试一致。
        # 此前用 WrapLabel 换行显示全文，行宽不足时折成两行，让"阈值测试控制"整块
        # 在测试中途变高、上下跳动。
        # 注：QLabel 没有 setTextElideMode，用 _ElidedLabel 手动 elide。
        self.progress_label = _ElidedLabel("状态=就绪 | 进度: 0/0 | —")
        self.progress_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        themed_qss(self.progress_label, lambda: f"color: {COLORS['text_dim']}; font-size: 12px;")
        info_row.addWidget(self.progress_label, 1)

        self.stat_label = QLabel("通过: 0  失败: 0")
        themed_qss(self.stat_label, lambda: f"color: {COLORS['text_dim']}; font-size: 12px;")
        # 固定宽度：统计数字增长/缩短时不再改变布局
        self.stat_label.setMinimumWidth(self.stat_label.fontMetrics().horizontalAdvance("通过: 000  失败: 000") + 8)
        self.stat_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_row.addWidget(self.stat_label)
        outer.addLayout(info_row)

        group.setLayout(outer)
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return group

    def _badge_qss(self) -> str:
        """阶段徽章样式（颜色随主题变化）；_badge_args 为 None 时按「就绪」显示"""
        state_name, failed = self._badge_args or ("就绪", 0)
        if state_name in ("失败",) or (failed > 0 and state_name == "已完成"):
            bg, fg = COLORS["error"], "#ffffff"
        elif state_name == "已完成":
            bg, fg = COLORS["success"], "#ffffff"
        elif state_name == "已停止":
            bg, fg = COLORS["warning"], "#ffffff"
        elif state_name == "就绪":
            bg, fg = COLORS["border"], COLORS["text"]
        else:
            bg, fg = COLORS["accent"], "#ffffff"
        return (
            f"background-color: {bg}; color: {fg}; border-radius: 3px; "
            f"padding: 2px 6px; font-weight: bold; font-size: 12px;"
        )

    def _set_state_badge(self, state_name: str, failed: int = 0):
        self._badge_args = (state_name, failed)
        self.state_badge.setText(state_name)
        # 长状态超出 88px 会被截断（吞字）：按文字实际宽度加宽；仅状态切换时变化一次，进度刷新不抖动
        badge_w = max(88, self.state_badge.fontMetrics().horizontalAdvance(state_name) + 20)  # 文字 + 左右 padding 12 + 余量
        if self.state_badge.width() != badge_w:
            self.state_badge.setFixedWidth(badge_w)
        style = self._badge_qss()
        # 样式未变化时不重复 setStyleSheet，避免每次进度刷新都触发布局/重绘（抖动）
        if style != self._badge_style_cache:
            self.state_badge.setStyleSheet(style)
            self._badge_style_cache = style

    def _on_theme_changed(self):
        """切换主题：徽章、以及复位后写死文字色的待测试行"""
        style = self._badge_qss()
        self.state_badge.setStyleSheet(style)
        self._badge_style_cache = style
        if hasattr(self, "pid_table_widget"):
            for row in range(self.pid_table_widget.rowCount()):
                item = self.pid_table_widget.item(row, 5)
                if item and item.text() == "待测试":
                    item.setForeground(QColor(COLORS["text"]))

    def create_detail_group(self) -> QGroupBox:
        group = QGroupBox("测试详情")
        layout = QVBoxLayout()
        splitter = QSplitter(Qt.Vertical)
        # 上下两块之间要留缝隙：默认 handle 只有 2px，看着像贴死
        splitter.setHandleWidth(8)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")

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
        themed_qss(self.param_table, lambda: (
            table_qss()
            + "\nQTableWidget { font-size: 12px; }"
            + "\nQTableWidget::item { padding: 6px 8px; }"
        ))
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
    def _format_mature_time(value) -> str:
        if value is None:
            return "—"
        return f"{value:g}"

    def _make_checkbox(self) -> QCheckBox:
        cb = QCheckBox()
        cb.setChecked(False)  # 默认全不选
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(cb)
        wrapper.checkbox = cb
        return wrapper

    @staticmethod
    def _make_row_button(text: str, style, slot) -> QWidget:
        """单元格内的操作按钮：统一尺寸、文字居中"""
        from PyQt5.QtWidgets import QSizePolicy

        btn = RowButton(text)
        themed_qss(btn, lambda: style() + button_fixed_size_qss(72, 32))
        btn.setFixedSize(72, 32)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(btn)
        wrapper.button = btn
        return wrapper

    @staticmethod
    def _get_checkbox(table: QTableWidget, row: int) -> Optional[QCheckBox]:
        w = table.cellWidget(row, 0)
        return getattr(w, "checkbox", None) if w else None

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
        for i, (pid, level, _) in enumerate(rows):
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

            status = QTableWidgetItem("待测试")
            status.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 5, status)

            key = (pid.pid, level)
            cell_set = self._make_row_button(
                "设置", btn_primary,
                lambda _, r=i, k=key: self._operate_fault(r, "set", k[1]),
            )
            cell_clr = self._make_row_button(
                "清除", btn_warning,
                lambda _, r=i, k=key: self._operate_fault(r, "clear", k[1]),
            )
            table.setCellWidget(i, 6, cell_set)
            table.setCellWidget(i, 7, cell_clr)
            self._oper_buttons[key] = [cell_set.button, cell_clr.button]
            self._row_index[key] = i

        self.filter_pid_list()
        self.log_message(f"已加载 PID 等级行: {len(rows)}（默认全不选）")
        self._resize_pid_columns()

    def _resize_pid_columns(self):
        """PID 列表列宽自适应：优先保证名称/阈值等列完整显示"""
        table = getattr(self, "pid_table_widget", None)
        if table is None:
            return
        viewport_width = table.viewport().width()
        if viewport_width <= 0:
            viewport_width = max(520, table.width())
        # 预留竖向滚动条宽度：滚动条出现时视口变窄，否则又会多出横向滚动
        viewport_width = max(240, viewport_width - 14)
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

        # 开始前填写项目名称（写入测试报告，与故障码测试一致）
        project_name, ok = QInputDialog.getText(
            self,
            "项目名称",
            "请输入本次测试的项目名称（将写入测试报告）:",
            QLineEdit.Normal,
            self._last_project_name or "",
        )
        if not ok:
            self.log_message("已取消：未填写项目名称", "WARNING")
            return
        project_name = (project_name or "").strip()
        if not project_name:
            QMessageBox.warning(self, "提示", "项目名称不能为空。")
            return
        self._last_project_name = project_name
        self._current_project_name = project_name

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
        self.log_message(
            f"开始阈值测试：共 {len(codes)} 个 PID，测试对象为 "
            f"{self.domain_combo.currentText()} 地址 {self.addr_spin.value()}，"
            f"测试类型 {self.test_type_combo.currentText()}，"
            f"阈值偏移 {float(self.offset_spin.value()):g}，"
            f"报警等待 {float(self.wait_spin.value()):g} 秒"
        )

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
                # 结果由引擎逐级经 on_test_result 实时上报，这里只负责收尾
                results = self.threshold_engine.run_single_pid(codes[0], **cfg) or []
                self._sig_complete.emit(results)
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
            item = self.pid_table_widget.item(row, 5)
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
        meta = getattr(result, "metadata", {}) or {}
        level = str(meta.get("level") or "")
        name = str(getattr(result, "fault_name", "") or "")
        # fault_name 形如「单体电压过高 L1」，尾部的 Ln 改写成「1 级」更易读
        if level and name.endswith(f" L{level}"):
            name = f"{name[:-(len(level) + 2)]} {level} 级"
        pid_hex = str(meta.get("pid") or "")
        suffix = f"（PID {pid_hex}）" if pid_hex else ""
        self.log_message(f"[结果] {name}{suffix}：{status_text}")
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
        self.log_message(f"阈值测试完成，共 {len(results or [])} 条等级结果")
        self._save_results(results or [])
        self.test_completed.emit(results or [])

    def _save_results(self, results: list):
        if not self._test_logger or not results:
            return
        try:
            self._test_logger.log_test_batch(
                results,
                test_type="threshold",
                project_name=self._current_project_name or "",
            )
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
                    item = self.pid_table_widget.item(row, 5)
                    if item:
                        item.setText(status_text)
                        item.setForeground(color)
            return
        for lv in levels:
            row = self._row_index.get((pid_val, lv))
            if row is None:
                continue
            item = self.pid_table_widget.item(row, 5)
            if item:
                item.setText(status_text)
                item.setForeground(color)

    def update_param_table(self, result: TestResult):
        table = self.param_table
        pid_name = getattr(result, "pid_name", "") or ""
        # 同一参数重复上报（如解除失败后回填结论）时更新原行，避免刷出重复行
        row = -1
        for r in range(table.rowCount()):
            item = table.item(r, 0)
            if item and item.text() == pid_name:
                row = r
                break
        if row < 0:
            row = table.rowCount()
            table.insertRow(row)
        checks = getattr(result, "checks", []) or []

        def fmt(v):
            if v is None:
                return ""
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            return str(v)

        verify_types = (
            CheckType.INNER_SYS_FAIL_STA, CheckType.INNER_ERR_TAB, CheckType.INNER_SPECIFIC,
            CheckType.OUTER_SYS_FAIL_STA, CheckType.OUTER_SPECIFIC, CheckType.OUTER_WARNING,
            CheckType.INTERNAL_VERIFICATION, CheckType.EXTERNAL_VERIFICATION,
        )
        specific_types = (CheckType.INNER_SPECIFIC, CheckType.OUTER_SPECIFIC)

        env_val = ""
        set_val = ""
        alarm_val = ""
        alarm_st = ""
        release_val = ""
        verify_checks = []
        for c in checks:
            n = c.name or ""
            ctype = getattr(c, "check_type", None)
            if "环境" in n:
                env_val = fmt(c.actual_value)
            elif "阈值设置" in n:
                set_val = fmt(c.actual_value)
            elif "阈值恢复" in n or "解除" in n:
                release_val = fmt(c.actual_value)
            elif ctype in verify_types:
                verify_checks.append(c)

        # 实际报警值优先取 specific 信号（如 CellVolt_HighWarning 的告警等级）
        for c in verify_checks:
            if getattr(c, "check_type", None) in specific_types and c.actual_value is not None:
                alarm_val = fmt(c.actual_value)
                break
        if not alarm_val:
            for c in verify_checks:
                if c.actual_value is not None:
                    alarm_val = fmt(c.actual_value)
                    break
        if verify_checks:
            alarm_st = "通过" if all(c.status == CheckStatus.PASSED for c in verify_checks) else "失败"

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
            item = self.pid_table_widget.item(row, 5)
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
