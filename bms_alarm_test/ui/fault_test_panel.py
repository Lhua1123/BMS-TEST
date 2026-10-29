"""
故障码测试面板 (PyQt5)
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QSpinBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QTextEdit, QLineEdit, QSplitter, QCheckBox,
    QAbstractItemView, QInputDialog, QMessageBox)
from typing import Optional
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QColor
import threading
import time

from shared.style import COLORS, FONTS, themed_qss, on_theme_changed
from bms_alarm_test.ui.panel_style import (
    table_qss,
    compact_qss,
    LeftAlignDelegate,
    RowButton,
    btn_primary,
    btn_warning,
    btn_danger,
    btn_neutral,
    button_fixed_size_qss,
)
from bms_alarm_test.config.fault_mapping import FaultMapping, FaultDomain, Fault
from bms_alarm_test.engine.fault_engine import FaultTestEngine
from bms_alarm_test.models.test_result import TestResult, CheckStatus

# 引擎 TestState → 界面中文
TEST_STATE_CN = {
    "idle": "就绪",
    "preparing": "准备中",
    "injecting": "注入故障",
    "verifying": "验证中",
    "clearing": "清除故障",
    "completed": "已完成",
    "failed": "失败",
    "stopped": "已停止",
    "cleaning_progress": "清除所有故障中",
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


class FaultTestPanel(QWidget):
    """故障码测试面板"""

    # 信号定义
    test_started = pyqtSignal()
    test_stopped = pyqtSignal()
    test_result_received = pyqtSignal(object)
    test_completed = pyqtSignal(list)
    # 内部线程安全信号
    _sig_result = pyqtSignal(object)
    _sig_progress = pyqtSignal(object)
    _sig_complete = pyqtSignal(list)
    # 单步后台线程 → GUI 线程：执行完成 / 线程安全日志
    _sig_step_done = pyqtSignal(object)
    _sig_log = pyqtSignal(str, str)

    def __init__(self, fault_mapping: FaultMapping, parent=None):
        super().__init__(parent)
        themed_qss(self, compact_qss)
        on_theme_changed(self._on_theme_changed)
        self.fault_mapping = fault_mapping
        self.fault_engine: FaultTestEngine = None
        self._step_fault_codes = []
        self._step_index = -1
        # 后台线程 → GUI：日志与单步收尾（log_message 操作 QTextEdit，非线程安全）
        self._sig_log.connect(self.log_message)
        self._sig_step_done.connect(self._on_step_done)
        self._test_logger = None
        self._report_batch_start_time = None
        self._last_project_name = ""
        self._current_project_name = ""

        # 测试结果存储
        self.test_results: list[TestResult] = []

        # 初始化UI
        self.setup_ui()
        self.setup_connections()

        # 自动加载故障列表，避免进入面板后空白
        if self.fault_mapping:
            self.refresh_fault_list()

    def setup_ui(self):
        """设置UI界面"""
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # 左侧：配置 + 故障列表（保证故障列表有足够横向空间）
        left = QVBoxLayout()
        left.setSpacing(6)
        config_group = self.create_config_group()
        left.addWidget(config_group, 0)
        fault_group = self.create_fault_list_group()
        left.addWidget(fault_group, 1)

        left_container = QWidget()
        left_container.setLayout(left)
        left_container.setMinimumWidth(420)
        root.addWidget(left_container, 2)

        # 右侧：控制 + 测试详情（控制区不再横向堆叠进度条，避免挤占左侧）
        right = QVBoxLayout()
        right.setSpacing(6)
        control_group = self.create_control_group()
        right.addWidget(control_group, 0)
        detail_group = self.create_detail_group()
        right.addWidget(detail_group, 1)

        right_container = QWidget()
        right_container.setLayout(right)
        root.addWidget(right_container, 3)

    def create_config_group(self) -> QGroupBox:
        """创建测试配置区域（两行紧凑排布）"""
        from PyQt5.QtWidgets import QSizePolicy

        group = QGroupBox("测试配置")
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

        # 第一行：地址 + 测试范围
        layout.addWidget(QLabel("NBCMU地址:"), 0, 0)
        self.nbcmu_spin = QSpinBox()
        self.nbcmu_spin.setRange(1, 255)
        self.nbcmu_spin.setValue(161)
        layout.addWidget(_fill(self.nbcmu_spin, 90), 0, 1)

        layout.addWidget(QLabel("SBCMU地址:"), 0, 2)
        self.sbcmu_spin = QSpinBox()
        self.sbcmu_spin.setRange(1, 255)
        self.sbcmu_spin.setValue(177)
        layout.addWidget(_fill(self.sbcmu_spin, 90), 0, 3)

        layout.addWidget(QLabel("测试范围:"), 0, 4)
        self.fault_range_combo = QComboBox()
        self.fault_range_combo.addItems(["所有故障", "NBCMU故障", "SBCMU故障", "共有故障", "自定义选择"])
        layout.addWidget(_fill(self.fault_range_combo, 120), 0, 5)

        # 第二行：故障等级 + 失败处理 + 是否读取对外报文
        layout.addWidget(QLabel("故障等级:"), 1, 0)
        self.fault_level_combo = QComboBox()
        self.fault_level_combo.addItems(["所有等级", "等级1", "等级2", "等级3"])
        layout.addWidget(_fill(self.fault_level_combo, 120), 1, 1)

        layout.addWidget(QLabel("失败处理:"), 1, 2)
        self.fail_handling_combo = QComboBox()
        self.fail_handling_combo.addItems(["跳过继续", "中断测试"])
        layout.addWidget(_fill(self.fail_handling_combo, 120), 1, 3)

        # 是否读取对外报文（对外无报文时可取消勾选，跳过对外回读验证）
        self.read_outer_check = QCheckBox("读取对外报文（对外验证）")
        self.read_outer_check.setChecked(True)
        self.read_outer_check.setToolTip(
            "勾选时读取对外CAN报文做对外验证（SysFailSta/对外specific/Warning汇总）。\n"
            "若测试时对外无报文，可不勾选，跳过对外回读。"
        )
        layout.addWidget(self.read_outer_check, 1, 4, 1, 2)

        group.setLayout(layout)
        return group

    def create_fault_list_group(self) -> QGroupBox:
        """创建故障列表区域"""
        group = QGroupBox("故障列表")
        layout = QVBoxLayout()

        # 列表控制按钮
        control_layout = QHBoxLayout()

        self.select_all_btn = QPushButton("全选")
        themed_qss(self.select_all_btn, btn_primary)
        control_layout.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("全不选")
        themed_qss(self.select_none_btn, btn_primary)
        control_layout.addWidget(self.select_none_btn)

        self.invert_selection_btn = QPushButton("反选")
        themed_qss(self.invert_selection_btn, btn_primary)
        control_layout.addWidget(self.invert_selection_btn)

        self.refresh_list_btn = QPushButton("重置列表")
        themed_qss(self.refresh_list_btn, btn_warning)
        control_layout.addWidget(self.refresh_list_btn)

        # 搜索框
        control_layout.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索故障码或名称...")
        self.search_edit.setFixedHeight(34)  # 与同排按钮等高
        control_layout.addWidget(self.search_edit, 1)

        layout.addLayout(control_layout)

        # 故障表格
        self.fault_table = QTableWidget()
        self.fault_table.setColumnCount(7)
        self.fault_table.setHorizontalHeaderLabels([
            "选择", "故障码", "故障名称", "故障等级", "域类型",
            "设置", "清除"
        ])
        self.fault_table.verticalHeader().setVisible(False)
        header = self.fault_table.horizontalHeader()
        header.setMinimumSectionSize(0)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        # 先保证故障列表在常见宽度下能完整显示，不出现横向滚动
        self._fault_column_weights = [0.7, 0.85, 2.2, 1.0, 1.05, 0.8, 0.8]
        self._fault_column_min_widths = [48, 56, 140, 64, 78, 84, 84]
        themed_qss(self.fault_table, lambda: (
            table_qss()
            + "\nQTableWidget { font-size: 12px; }"
            # item 内边距会一起压缩单元格控件区域，把行内按钮裁掉，故设为 0
            + "\nQTableWidget::item { padding: 0px; }"
            + "\nQHeaderView::section { font-size: 12px; padding: 7px 8px; }"
        ))
        self.fault_table.setSelectionBehavior(QTableWidget.SelectRows)
        # 纯展示/选择列表，禁止双击或按键进入编辑
        self.fault_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fault_table.verticalHeader().setDefaultSectionSize(38)
        # 故障名称等文本列强制左对齐
        LeftAlignDelegate.attach(self.fault_table, [2], self.fault_table)

        layout.addWidget(self.fault_table)

        group.setLayout(layout)
        return group

    def create_control_group(self) -> QGroupBox:
        """测试控制：按钮一行 + 通栏进度条 + 状态文字（对齐阈值测试，不挤占左侧列表）"""
        from PyQt5.QtWidgets import QSizePolicy

        # 记录上次徽章样式，避免重复 setStyleSheet 触发重绘/抖动
        self._badge_style_cache = None

        group = QGroupBox("测试控制")
        outer = QVBoxLayout()
        outer.setSpacing(6)

        # —— 按钮行（仅按钮，不放进度控件）——
        # 与阈值测试一致：按文字自适应宽度，不锁死尺寸，间距紧凑
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.start_test_btn = QPushButton("开始")
        self.start_test_btn.setEnabled(False)
        themed_qss(self.start_test_btn, btn_primary)
        btn_row.addWidget(self.start_test_btn)

        self.stop_test_btn = QPushButton("停止")
        self.stop_test_btn.setEnabled(False)
        themed_qss(self.stop_test_btn, btn_danger)
        btn_row.addWidget(self.stop_test_btn)

        self.step_test_btn = QPushButton("单步测试")
        self.step_test_btn.setEnabled(False)
        themed_qss(self.step_test_btn, btn_warning)
        btn_row.addWidget(self.step_test_btn)

        self.verify_cfg_btn = QPushButton("配置验证")
        self.verify_cfg_btn.setToolTip(
            "合并配置：①CAN 信号回读协议（ID/位定义/DBC） ②故障期望值与额外回读"
        )
        themed_qss(self.verify_cfg_btn, btn_primary)
        self.verify_cfg_btn.clicked.connect(self._open_verify_config)
        btn_row.addWidget(self.verify_cfg_btn)

        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        # —— 进度条：与阈值测试一致，通栏、可横向扩展 ——
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(True)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
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

        # —— 状态信息横向排布：徽章 + 进度说明 + 统计，占满进度条下方一行 ——
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        self.state_badge = QLabel("就绪")
        self.state_badge.setFixedSize(88, 24)  # 基准尺寸；长状态（如“清除所有故障中”）在 _set_state_badge 里按文字加宽防截断
        self.state_badge.setAlignment(Qt.AlignCenter)
        self._badge_args = None  # (状态名, 失败数)，首次 _set_state_badge 前为 None
        self.state_badge.setStyleSheet(self._badge_qss())
        info_row.addWidget(self.state_badge)

        # 状态信息：单行 + 超宽省略号（ElideRight）。此前用 WrapLabel 换行显示全文，
        # 一旦行宽不足（窗口/面板偏窄、或文字变长）就折成两行，让"测试控制"整块在
        # 测试中途变高、上下跳动。改为固定单行，超宽时末尾显示"…"，不再撑高布局。
        # 注：QLabel 没有 setTextElideMode，用 _ElidedLabel 手动 elide。
        self.progress_label = _ElidedLabel("状态=就绪 | 进度: 0/0 | —")
        self.progress_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        themed_qss(self.progress_label, lambda: f"color: {COLORS['text_dim']}; font-size: 12px;")
        self.progress_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_row.addWidget(self.progress_label, 1)

        self.stat_label = QLabel("通过: 0  失败: 0  跳过: 0")
        themed_qss(self.stat_label, lambda: f"color: {COLORS['text_dim']}; font-size: 12px;")
        self.stat_label.setWordWrap(False)
        # 固定宽度：统计数字增长/缩短时不再改变布局
        self.stat_label.setMinimumWidth(self.stat_label.fontMetrics().horizontalAdvance("通过: 000  失败: 000  跳过: 000") + 8)
        self.stat_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_row.addWidget(self.stat_label)

        outer.addLayout(info_row)

        group.setLayout(outer)
        # 控制区不设定过大的最小宽度，避免挤占左侧故障列表
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return group

    def create_detail_group(self) -> QGroupBox:
        """创建测试详情区域"""
        group = QGroupBox("测试详情")
        layout = QVBoxLayout()

        # 使用分割器
        splitter = QSplitter(Qt.Vertical)
        # 上下两块之间要留缝隙：默认 handle 只有 2px，看着像贴死
        splitter.setHandleWidth(8)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")

        # 实时日志（与阈值测试一致：不套分组框，用占位文字标示）
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont(*FONTS['mono_large']))
        self.log_text.setPlaceholderText("实时日志")
        splitter.addWidget(self.log_text)

        # 验证详情
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(7)
        self.detail_table.setHorizontalHeaderLabels([
            "故障名", "检查类型", "检查域", "期望值", "实际值", "状态", "备注"
        ])
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detail_table.verticalHeader().setVisible(False)
        themed_qss(self.detail_table, lambda: (
            table_qss()
            + "\nQTableWidget { font-size: 12px; }"
            + "\nQTableWidget::item { padding: 6px 8px; }"
        ))
        LeftAlignDelegate.attach(self.detail_table, [0, 1, 6], self.detail_table)
        splitter.addWidget(self.detail_table)

        # 设置分割器比例（等分）
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])

        layout.addWidget(splitter)
        group.setLayout(layout)
        return group

    def setup_connections(self):
        """设置信号连接"""
        # 列表控制按钮
        self.select_all_btn.clicked.connect(self.select_all_faults)
        self.select_none_btn.clicked.connect(self.select_none_faults)
        self.invert_selection_btn.clicked.connect(self.invert_selection)
        self.refresh_list_btn.clicked.connect(self.refresh_fault_list)

        # 测试控制按钮
        self.start_test_btn.clicked.connect(self.start_test)
        self.stop_test_btn.clicked.connect(self.stop_test)
        self.step_test_btn.clicked.connect(self.step_test)

        # 搜索框
        self.search_edit.textChanged.connect(self.filter_fault_list)

        # 测试范围选择
        self.fault_range_combo.currentTextChanged.connect(self.on_test_range_changed)

    def show_clearing_state(self, clearing: bool):
        """一键清除所有故障时显示/恢复清除进度状态（由顶部栏调用）"""
        if clearing:
            self.progress_bar.setVisible(True)
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0%  (0/96)")
            self._set_state_badge("清除所有故障中")
            self.progress_label.setText("状态=清除所有故障中 | 进度: 0/96 | —")
            self.log_message("一键清除所有故障：开始发送清除指令...", "INFO")
        else:
            self._set_state_badge("就绪")
            self.progress_label.setText(
                f"状态=就绪 | 进度: {self.progress_bar.value()}/{self.progress_bar.maximum()} | —"
            )

    def _open_verify_config(self):
        """打开合并的验证配置窗口（回读协议 + 故障期望值）"""
        from bms_alarm_test.ui.verify_config_dialog import VerifyConfigDialog
        dlg = VerifyConfigDialog(self, fault_mapping=self.fault_mapping)
        dlg.exec_()
        try:
            self.refresh_fault_list()
        except Exception:
            pass
        self.log_message("验证配置已更新（回读协议/故障期望值）", "INFO")

    def _open_readback_config(self):
        """兼容旧入口：仅打开信号回读协议页"""
        from bms_alarm_test.ui.verify_config_dialog import VerifyConfigDialog
        dlg = VerifyConfigDialog(self, fault_mapping=self.fault_mapping)
        dlg.tabs.setCurrentIndex(0)
        dlg.exec_()
        self.log_message("回读协议配置已更新", "INFO")

    def _open_fault_expect_config(self):
        """兼容旧入口：仅打开故障期望值页"""
        from bms_alarm_test.ui.verify_config_dialog import VerifyConfigDialog
        dlg = VerifyConfigDialog(self, fault_mapping=self.fault_mapping)
        dlg.tabs.setCurrentIndex(1)
        dlg.exec_()
        try:
            self.refresh_fault_list()
        except Exception:
            pass
        self.log_message("故障期望值/回读配置已更新", "INFO")

    def set_test_logger(self, test_logger):
        """设置测试结果记录器（用于落库）"""
        self._test_logger = test_logger

    def set_fault_engine(self, fault_engine: FaultTestEngine):
        """设置故障测试引擎"""
        self.fault_engine = fault_engine

        if fault_engine:
            # 用信号把后台线程回调调度到主线程，避免QTextCursor警告
            self._sig_result.connect(self._do_test_result)
            self._sig_progress.connect(self._do_progress_update)
            self._sig_complete.connect(self._do_test_complete)

            self.fault_engine.set_callbacks(
                on_progress_update=lambda p: self._sig_progress.emit(p),
                on_test_result=lambda r: self._sig_result.emit(r),
                on_test_complete=lambda r: self._sig_complete.emit(r),
            )

            # 启用测试按钮
            self.start_test_btn.setEnabled(True)
            self.step_test_btn.setEnabled(True)

    def showEvent(self, event):
        super().showEvent(event)
        self._resize_fault_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_fault_columns()

    def _resize_fault_columns(self):
        if not hasattr(self, "fault_table"):
            return
        viewport_width = self.fault_table.viewport().width()
        if viewport_width <= 0:
            return
        # 预留竖向滚动条宽度：滚动条出现时视口变窄，否则又会多出横向滚动
        viewport_width = max(240, viewport_width - 14)
        minimums = self._fault_column_min_widths
        weights = self._fault_column_weights
        minimum_total = sum(minimums)
        if viewport_width <= minimum_total:
            widths = minimums[:]
        else:
            extra = viewport_width - minimum_total
            weight_total = sum(weights)
            widths = [
                minimum + int(extra * weight / weight_total)
                for minimum, weight in zip(minimums, weights)
            ]
            widths[-1] += viewport_width - sum(widths)
        header = self.fault_table.horizontalHeader()
        for column, width in enumerate(widths):
            header.resizeSection(column, max(1, width))

    def refresh_fault_list(self):
        """刷新故障列表"""
        if not self.fault_mapping:
            self.log_message("错误: 故障映射未加载", "ERROR")
            return

        # 获取故障列表
        faults = self.fault_mapping.get_all_faults()

        # 清空表格
        self.fault_table.setRowCount(0)

        # 填充表格
        for i, fault in enumerate(faults):
            self.fault_table.insertRow(i)

            # 选择复选框（原生控件居中，点击/绘制均可靠）
            self.fault_table.setCellWidget(i, 0, self._make_checkbox())

            # 故障码
            item = QTableWidgetItem(str(fault.code))
            item.setTextAlignment(Qt.AlignCenter)
            self.fault_table.setItem(i, 1, item)

            # 故障名称（文本列左对齐）
            item = QTableWidgetItem(fault.name)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.fault_table.setItem(i, 2, item)

            # 故障等级
            item = QTableWidgetItem(str(fault.fault_level))
            item.setTextAlignment(Qt.AlignCenter)
            self.fault_table.setItem(i, 3, item)

            # 域类型
            domain = "NBCMU" if fault.domain == FaultDomain.NBCMU else "SBCMU"
            item = QTableWidgetItem(domain)
            item.setTextAlignment(Qt.AlignCenter)
            self.fault_table.setItem(i, 4, item)

            # 设置按钮
            self.fault_table.setCellWidget(
                i, 5,
                self._make_row_button(
                    "设置", btn_primary,
                    lambda _, f=fault: self._on_inject_single(f),
                ),
            )

            # 清除按钮
            self.fault_table.setCellWidget(
                i, 6,
                self._make_row_button(
                    "清除", btn_warning,
                    lambda _, f=fault: self._on_clear_single(f),
                ),
            )

        self._resize_fault_columns()

        self.log_message(f"已加载 {len(faults)} 个故障", "INFO")

    @staticmethod
    def _make_checkbox() -> QWidget:
        """创建居中的选择复选框控件"""
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        cb = QCheckBox()
        cb.setChecked(False)  # 默认全不选
        lay.addWidget(cb, 0, Qt.AlignCenter)
        return container

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
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(btn)
        container.button = btn
        return container

    @staticmethod
    def _get_checkbox(table, row: int) -> Optional[QCheckBox]:
        """取第 row 行选择列的原生复选框（无则 None）"""
        w = table.cellWidget(row, 0)
        if w is None:
            return None
        return w.findChild(QCheckBox)

    def select_all_faults(self):
        """全选故障"""
        for row in range(self.fault_table.rowCount()):
            cb = self._get_checkbox(self.fault_table, row)
            if cb:
                cb.setChecked(True)

    def select_none_faults(self):
        """全不选故障"""
        for row in range(self.fault_table.rowCount()):
            cb = self._get_checkbox(self.fault_table, row)
            if cb:
                cb.setChecked(False)

    def invert_selection(self):
        """反选故障"""
        for row in range(self.fault_table.rowCount()):
            cb = self._get_checkbox(self.fault_table, row)
            if cb:
                cb.setChecked(not cb.isChecked())

    def filter_fault_list(self):
        """过滤故障列表"""
        search_text = self.search_edit.text().strip().lower()

        if not search_text:
            # 显示所有行
            for row in range(self.fault_table.rowCount()):
                self.fault_table.setRowHidden(row, False)
            return

        # 根据搜索文本过滤
        for row in range(self.fault_table.rowCount()):
            fault_code = self.fault_table.item(row, 1).text().lower()
            fault_name = self.fault_table.item(row, 2).text().lower()

            if search_text in fault_code or search_text in fault_name:
                self.fault_table.setRowHidden(row, False)
            else:
                self.fault_table.setRowHidden(row, True)

    def on_test_range_changed(self, range_text: str):
        """测试范围改变"""
        if range_text == "自定义选择":
            # 启用表格选择
            self.fault_table.setEnabled(True)
        else:
            # 根据范围自动选择
            self.fault_table.setEnabled(False)
            self.select_faults_by_range(range_text)

    def select_faults_by_range(self, range_text: str):
        """根据范围选择故障"""
        if not self.fault_mapping:
            return

        # 获取对应范围的故障
        if range_text == "NBCMU故障":
            faults = self.fault_mapping.get_nbcmu_faults()
        elif range_text == "SBCMU故障":
            faults = self.fault_mapping.get_sbcmu_faults()
        elif range_text == "共有故障":
            faults = self.fault_mapping.get_common_faults()
        else:  # 所有故障
            faults = self.fault_mapping.get_all_faults()

        # 获取故障码集合
        fault_codes = {str(fault.code) for fault in faults}

        # 更新选择状态
        for row in range(self.fault_table.rowCount()):
            cb = self._get_checkbox(self.fault_table, row)
            fault_code = self.fault_table.item(row, 1).text()

            if cb is not None:
                cb.setChecked(fault_code in fault_codes)

    def get_selected_fault_codes(self) -> list[str]:
        """获取选中的故障码（同码多版本用 code:domain 区分）"""
        selected_codes = []

        for row in range(self.fault_table.rowCount()):
            cb = self._get_checkbox(self.fault_table, row)
            if cb and cb.isChecked():
                fault_code = self.fault_table.item(row, 1).text()
                domain_item = self.fault_table.item(row, 4)  # 域类型列
                domain = domain_item.text() if domain_item else ""
                selected_codes.append(f"{fault_code}:{domain}")

        return selected_codes

    def start_test(self):
        """开始测试"""
        if not self.fault_engine:
            self.log_message("错误: 故障测试引擎未设置", "ERROR")
            return

        # 前置检查：CAN 必须已连接
        can_manager = getattr(self.fault_engine, "can_manager", None)
        if can_manager is None or not can_manager.is_connected():
            self.log_message("错误: CAN 未连接，请先连接 CAN 后再开始测试", "ERROR")
            return

        # 获取选中的故障码
        selected_codes = self.get_selected_fault_codes()

        if not selected_codes:
            self.log_message("警告: 请选择要测试的故障", "WARNING")
            return

        # 开始前填写项目名称（写入测试报告）
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

        # 获取测试参数
        nbcmu_addr = self.nbcmu_spin.value()
        sbcmu_addr = self.sbcmu_spin.value()
        target_addresses = {
            FaultDomain.NBCMU: nbcmu_addr,
            FaultDomain.SBCMU: sbcmu_addr,
        }
        fail_on_first_error = self.fail_handling_combo.currentText() == "中断测试"

        # 同步是否读取对外报文选项
        self.fault_engine.read_outer_messages = self.read_outer_check.isChecked()

        # 开始测试
        if self.fault_engine.start_test(
            fault_codes=selected_codes,
            target_addresses=target_addresses,
            fail_on_first_error=fail_on_first_error
        ):
            # 更新UI状态
            self._report_batch_start_time = time.time()
            self.start_test_btn.setEnabled(False)
            self.stop_test_btn.setEnabled(True)
            self.step_test_btn.setEnabled(False)
            n = len(selected_codes)
            self.progress_bar.setVisible(True)
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(max(1, n))
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(f"0%  (0/{n})")
            self._set_state_badge("准备中")
            self.stat_label.setText("通过: 0  失败: 0  跳过: 0")
            self.progress_label.setText(f"状态=准备中 | 进度: 0/{n} | —")

            # 清空日志和详情
            self.log_text.clear()
            self.detail_table.setRowCount(0)

            # 发送信号
            self.test_started.emit()

            self.log_message(f"开始测试 {len(selected_codes)} 个故障 | 项目: {project_name}", "INFO")
        else:
            self.log_message("错误: 启动测试失败", "ERROR")

    def stop_test(self):
        """停止测试"""
        if self.fault_engine:
            self.fault_engine.stop_test()
            self.stop_test_btn.setEnabled(False)
            self._report_batch_start_time = None
            self.start_test_btn.setEnabled(True)
            self.step_test_btn.setEnabled(True)
            self.progress_bar.setVisible(True)
            self._set_state_badge("已停止")
            self.progress_label.setText(
                f"状态=已停止 | 进度: {self.progress_bar.value()}/{self.progress_bar.maximum()} | —"
            )

            self.log_message("测试已停止", "INFO")
            self.test_stopped.emit()

    def _on_inject_single(self, fault: Fault):
        """单个设置故障"""
        if not self.fault_engine:
            self.log_message("错误: 故障测试引擎未设置", "ERROR")
            return
        can_manager = getattr(self.fault_engine, "can_manager", None)
        if can_manager is None or not can_manager.is_connected():
            self.log_message("错误: CAN 未连接，请先连接 CAN", "ERROR")
            return
        nbcmu_addr = self.nbcmu_spin.value()
        sbcmu_addr = self.sbcmu_spin.value()
        target_addresses = {
            FaultDomain.NBCMU: nbcmu_addr,
            FaultDomain.SBCMU: sbcmu_addr,
        }
        self.fault_engine.target_addresses = target_addresses
        success = self.fault_engine._inject_fault(fault)
        if success:
            self.log_message(f"故障{fault.code} 设置成功", "INFO")
        else:
            self.log_message(f"故障{fault.code} 设置失败", "ERROR")

    def _on_clear_single(self, fault: Fault):
        """单个清除故障"""
        if not self.fault_engine:
            self.log_message("错误: 故障测试引擎未设置", "ERROR")
            return
        can_manager = getattr(self.fault_engine, "can_manager", None)
        if can_manager is None or not can_manager.is_connected():
            self.log_message("错误: CAN 未连接，请先连接 CAN", "ERROR")
            return
        nbcmu_addr = self.nbcmu_spin.value()
        sbcmu_addr = self.sbcmu_spin.value()
        target_addresses = {
            FaultDomain.NBCMU: nbcmu_addr,
            FaultDomain.SBCMU: sbcmu_addr,
        }
        self.fault_engine.target_addresses = target_addresses
        success = self.fault_engine._clear_fault(fault)
        if success:
            self.log_message(f"故障{fault.code} 清除成功", "INFO")
        else:
            self.log_message(f"故障{fault.code} 清除失败", "ERROR")

    def step_test(self):
        """单步测试（状态机模式）"""
        if not self.fault_engine:
            self.log_message("错误: 故障测试引擎未设置", "ERROR")
            return

        # 前置检查：CAN 必须已连接
        can_manager = getattr(self.fault_engine, "can_manager", None)
        if can_manager is None or not can_manager.is_connected():
            self.log_message("错误: CAN 未连接，请先连接 CAN", "ERROR")
            return

        # 获取当前选中的故障码
        selected_codes = self.get_selected_fault_codes()
        if not selected_codes:
            self.log_message("警告: 请选择一个故障进行单步测试", "WARNING")
            return

        # 如果选择列表变了，重置步进状态（全清统一由下方 _step_index == -1 分支执行一次，
        # 避免新列表首次点击时连续全清两遍）
        if selected_codes != self._step_fault_codes:
            self._step_fault_codes = selected_codes
            self._step_index = -1

        # 获取测试参数
        nbcmu_addr = self.nbcmu_spin.value()
        sbcmu_addr = self.sbcmu_spin.value()
        target_addresses = {
            FaultDomain.NBCMU: nbcmu_addr,
            FaultDomain.SBCMU: sbcmu_addr,
        }

        # 必须在 _spawn_step_worker（→ _clear_all_for_step）之前把地址下发到引擎：
        # 单步的前置全清按 fault_engine.target_addresses 发清码帧，而地址原本只在
        # 之后的 step_test_single() 里才被赋值，于是全清用的是引擎默认值 0x01
        # （有效节点地址是 0xA1..0xA5 / 0xB1..0xB5），帧发给了不存在的节点，
        # 旧故障清不掉，每次单步都从脏状态开始。
        self.fault_engine.target_addresses = {
            FaultDomain.NBCMU: nbcmu_addr,
            FaultDomain.SBCMU: sbcmu_addr,
        }

        total = len(self._step_fault_codes)

        # 同步是否读取对外报文选项
        self.fault_engine.read_outer_messages = self.read_outer_check.isChecked()

        # —— 以下簿记瞬时完成；清除/注入/验证等慢操作全部移交后台线程 ——
        clear_op = None          # "all" | ("fault", code)
        fault_code = None
        step_domain = None
        final_phase = False

        if self._step_index == -1:
            # 第一次：全清所有故障，然后注入第1个
            clear_op = "all"
            self._step_index = 0
            fault_code, step_domain = self._parse_step_fault(self._step_fault_codes[0])
        elif self._step_index < total - 1:
            # 中间：清除上一步的故障，然后注入下一个
            prev_code, _ = self._parse_step_fault(self._step_fault_codes[self._step_index])
            clear_op = ("fault", prev_code)
            self._step_index += 1
            fault_code, step_domain = self._parse_step_fault(self._step_fault_codes[self._step_index])
        else:
            # 最后一步之后：后台清除最后一个故障并结束序列
            final_phase = True
            last_code, _ = self._parse_step_fault(self._step_fault_codes[self._step_index])
            clear_op = ("fault", last_code)
            self._step_fault_codes = []
            self._step_index = -1
            self.step_test_btn.setText("单步测试")
        step_no = total if final_phase else self._step_index + 1

        # 更新按钮文字 / 禁用（防止慢操作期间重复点击或并发开批量测试）
        if not final_phase:
            self.step_test_btn.setText(f"单步测试 ({step_no}/{total})")
        self.step_test_btn.setEnabled(False)
        self.start_test_btn.setEnabled(False)

        # 全清 / 清上一个故障 / 注入→等待→验证→清除（每步走完整流程）——
        # 这些慢操作（几十秒）必须放后台线程：原先同步跑在 GUI 主线程，
        # 会把界面卡死（进度条冻结、鼠标沙漏），已由 stall 诊断栈证实。
        self._spawn_step_worker(clear_op, fault_code, step_domain, target_addresses,
                                total, step_no, final_phase)

    @staticmethod
    def _parse_step_fault(fault_str):
        """解析 "code" 或 "code:domain" → (fault_code, FaultDomain | None)"""
        if ":" in fault_str:
            code_part, domain_str = fault_str.split(":", 1)
            domain = None
            try:
                domain = FaultDomain(domain_str.upper())
            except ValueError:
                domain = None
            return int(code_part), domain
        return int(fault_str), None

    def _spawn_step_worker(self, clear_op, fault_code, step_domain, target_addresses,
                           total, step_no, final_phase):
        """后台执行单步的慢操作；完成后经 _sig_step_done 回到 GUI 线程收尾"""

        def _run():
            payload = {
                "fault_code": fault_code, "result": None, "error": None,
                "total": total, "step_no": step_no, "final": final_phase,
                "clear_code": clear_op[1] if isinstance(clear_op, tuple) else None,
            }
            try:
                if clear_op == "all":
                    self._clear_all_for_step()
                    if fault_code is not None:
                        self._sig_log.emit(
                            f"[单步] 全清完成，开始测试故障 {fault_code} ({step_no}/{total})", "INFO")
                elif isinstance(clear_op, tuple):
                    self._clear_step_fault(clear_op[0])
                    if fault_code is not None:
                        self._sig_log.emit(
                            f"[单步] 清除故障{clear_op[0]}完成，开始测试故障 {fault_code} ({step_no}/{total})", "INFO")
                if fault_code is not None:
                    payload["result"] = self.fault_engine.step_test_single(
                        fault_code=fault_code,
                        target_addresses=target_addresses,
                        domain=step_domain,
                        clear_previous=False,
                        auto_clear_after=True  # 验证后清除故障，单步也走完整流程
                    )
            except Exception as e:
                payload["error"] = str(e)
            self._sig_step_done.emit(payload)

        threading.Thread(target=_run, name="FaultStepWorker", daemon=True).start()

    @pyqtSlot(object)
    def _on_step_done(self, payload):
        """单步后台执行完成：回 GUI 线程记录日志、更新状态徽章/统计/按钮"""
        total = payload.get("total") or 0
        step_no = payload.get("step_no") or 0

        if payload.get("final"):
            # 序列结束：复位状态徽章/统计/状态行（进度回调停在“验证中”，不会自动复位）
            # 注意此时 _step_index 已重置为 -1，进度位置直接传 total
            self.log_message(
                f"[单步] 清除故障{payload.get('clear_code')}完成，单步序列结束", "INFO")
            self._update_step_status("已完成", total, total)
        elif payload.get("error"):
            self.log_message(f"错误: 单步测试异常: {payload['error']}", "ERROR")
            self._update_step_status("失败", step_no, total)
        elif payload.get("result"):
            result = payload["result"]
            self._do_test_result(result)
            self.log_message(
                f"故障{payload.get('fault_code')}单步测试完成: {result.overall_status.value}", "INFO")
            self._update_step_status("已完成", step_no, total)
        else:
            self.log_message(f"错误: 单步测试故障{payload.get('fault_code')}失败", "ERROR")
            self._update_step_status("失败", step_no, total)

        self.step_test_btn.setEnabled(True)
        self.start_test_btn.setEnabled(True)

    def _update_step_status(self, state_name: str, step_no: int, total: int):
        """单步测试结束时同步状态徽章/统计/状态行/进度条

        单步是同步流程，不走批量的 _do_test_complete，进度回调最后停在“验证中”；
        统计从会话累积的 test_results 计算（与批量口径一致）。
        """
        results = self.test_results
        passed = sum(1 for r in results if getattr(r, "is_passed", None) and r.is_passed())
        failed = len(results) - passed
        self._set_state_badge(state_name, failed=failed)
        self.stat_label.setText(f"通过: {passed}  失败: {failed}  跳过: 0")
        if total > 0 and step_no > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(min(step_no, total))
            pct = int(round(100.0 * min(step_no, total) / total))
            self.progress_bar.setFormat(f"{pct}%  ({min(step_no, total)}/{total})")
            progress_txt = f"{step_no}/{total}"
        else:
            progress_txt = "0/0"
        self.progress_label.setText(
            f"状态={state_name} | 进度: {progress_txt} | 通过={passed} 失败={failed}"
        )

    def _clear_all_for_step(self):
        """单步模式前：全清所有故障"""
        # 遗留的停止标志（上次点过「停止」）会让全清立即中断，必须先复位
        self.fault_engine.clear_stop_request()
        self.fault_engine.verifier.clear_signal_cache()
        for domain in self.fault_engine.target_addresses:
            self.fault_engine.clear_all_faults(domain)

    def _clear_step_fault(self, fault_code: int):
        """清除单个故障"""
        fault = self.fault_mapping.get_fault(fault_code)
        if fault:
            self.fault_engine._clear_fault(fault)
            time.sleep(0.5)

    @pyqtSlot(object)
    def _do_progress_update(self, progress):
        """进度更新（对齐阈值测试：进度条 + 中文阶段状态）"""
        state = getattr(progress, "current_state", None)
        state_name = _state_cn(state)

        # 清除所有故障中：进度条显示清除码进度（当前码/总码）
        if state_name == "清除所有故障中":
            clear_cur = int(getattr(progress, "clear_current", 0) or 0)
            clear_total = max(1, int(getattr(progress, "clear_total", 0) or 0))
            pct = int(round(100.0 * clear_cur / clear_total))
            self.progress_bar.setVisible(True)
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(clear_total)
            self.progress_bar.setValue(clear_cur)
            self.progress_bar.setFormat(f"{pct}%  ({clear_cur}/{clear_total})")
            self._set_state_badge(state_name)
            self.progress_label.setText(f"状态=清除所有故障中 | 进度: {clear_cur}/{clear_total} | —")
            return

        total = max(0, int(getattr(progress, "total_faults", 0) or 0))
        current = int(getattr(progress, "current_fault_index", 0) or 0)
        if total <= 0:
            total = 1
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(min(current, total))
        if total > 0:
            pct = int(round(100.0 * min(current, total) / total))
            self.progress_bar.setFormat(f"{pct}%  ({current}/{total})")
        else:
            self.progress_bar.setFormat("0%")

        state = getattr(progress, "current_state", None)
        state_name = _state_cn(state)
        passed = getattr(progress, "passed_count", 0) or 0
        failed = getattr(progress, "failed_count", 0) or 0
        skipped = getattr(progress, "skipped_count", 0) or 0

        # 收尾状态（COMPLETED/FAILED）且引擎记录了中止原因 → 已在 _do_test_complete
        # 之前到达终态的最后一帧：先按「中断/已停止」渲染，绝不出现「已完成 / 通过 0 失败 0」
        unrun_kind, unrun_reason = self._unrun_reason()
        if unrun_kind and state_name in ("已完成", "失败"):
            self._render_unrun_state(unrun_kind, unrun_reason, min(current, total), total)
            return

        self._set_state_badge(state_name, failed=failed)

        fault = getattr(progress, "current_fault", None)
        if fault is not None:
            fname = getattr(fault, "name", "") or ""
            fcode = getattr(fault, "code", "")
            fdom = getattr(getattr(fault, "domain", None), "value", "")
            fault_txt = f"故障{fcode} {fname} ({fdom})".strip()
        else:
            fault_txt = "—"

        self.stat_label.setText(f"通过: {passed}  失败: {failed}  跳过: {skipped}")
        self.progress_label.setText(
            f"状态={state_name} | 进度: {current}/{total} | {fault_txt} "
            f"| 通过={passed} 失败={failed}"
        )

    def _unrun_reason(self):
        """
        取取引擎记录的「本次运行未测任何故障码」的中止说明。
        返回 (kind, reason)：kind = "stop"（用户停止）/ "abort"（失败中断）/ ""（无）
        引擎只在准备阶段失败或收到停止请求时填充这两个字段，
        空结果列表本身无法区分「全部通过」和「一条都没测」。
        """
        eng = getattr(self, "fault_engine", None)
        if eng is None:
            return "", ""
        stop_reason = (getattr(eng, "stop_reason", "") or "").strip()
        if stop_reason:
            return "stop", stop_reason
        abort_reason = (getattr(eng, "abort_reason", "") or "").strip()
        if abort_reason:
            return "abort", abort_reason
        return "", ""

    def _render_unrun_state(self, kind: str, reason: str, current: int, total: int,
                            stat_text: Optional[str] = None):
        """
        「一个故障码都没测/未跑完」的展示：徽章为「中断」或「已停止」，
        绝不显示成「已完成」；进度条保持真实进度，不补 100%。
        """
        state_name = "已停止" if kind == "stop" else "中断"
        if stat_text is None:
            stat_text = "已停止（未完成）" if kind == "stop" else "未测试任何故障码"
        self._set_state_badge(state_name)
        self.stat_label.setText(stat_text)
        self.progress_label.setText(f"状态={state_name} | 进度: {current}/{total} | {reason}")

    def _badge_qss(self) -> str:
        """阶段徽章样式：运行中蓝、失败红、完成绿、停止橙、就绪灰（颜色随主题变化）"""
        if self._badge_args is None:
            return (
                f"background-color: {COLORS['border']}; color: {COLORS['text']}; "
                f"border-radius: 3px; padding: 2px 6px; font-weight: bold; font-size: 12px;"
            )
        state_name, failed = self._badge_args
        if state_name in ("失败", "中断") or (failed > 0 and state_name == "已完成"):
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
            f"padding: 4px 6px; font-weight: bold; font-size: 12px;"
        )

    def _set_state_badge(self, state_name: str, failed: int = 0):
        """阶段徽章：文字 + 配色（配色见 _badge_qss）"""
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
        """切换主题：徽章、以及需要重画的表格/日志颜色"""
        style = self._badge_qss()
        self.state_badge.setStyleSheet(style)
        self._badge_style_cache = style

    @pyqtSlot(object)
    def _do_test_result(self, result: TestResult):
        """测试结果回调"""
        # 添加到结果列表
        self.test_results.append(result)

        # 落库（持久化到 SQLite，供测试报告页展示）
        # Single-step results are intentionally not persisted.

        status_color = COLORS['success'] if result.overall_status == CheckStatus.PASS else COLORS['error']
        time_str = result.start_time.strftime("%H:%M:%S") if result.start_time else ""
        fault_code = result.metadata.get("fault_code", "")
        log_msg = f"[{time_str}] {fault_code} - {result.fault_name}: {result.overall_status.value}"
        self.log_text.append(f'<font color="{status_color}">{log_msg}</font>')

        # 更新详情表格
        self.update_detail_table(result)

        # 发送信号
        self.test_result_received.emit(result)

    @pyqtSlot(list)
    def _do_test_complete(self, results: list[TestResult]):
        """测试完成回调"""
        # 更新UI状态
        self.start_test_btn.setEnabled(True)
        self.stop_test_btn.setEnabled(False)
        self.step_test_btn.setEnabled(True)
        # 进度条保留显示，便于查看最终进度（与阈值测试一致）
        self.progress_bar.setVisible(True)

        # 计算统计（失败只算 FAIL，跳过单列，不再把「跳过」误计成失败）
        passed = sum(1 for r in results if r.overall_status == CheckStatus.PASS)
        failed = sum(1 for r in results if r.overall_status == CheckStatus.FAIL)
        skipped = len(results) - passed - failed

        total = max(1, self.progress_bar.maximum())
        current = min(self.progress_bar.value(), total)

        # CAN 发送异常中断 / 用户停止：空结果列表不代表测试成功，
        # 不补进度条、不写「已完成 / 通过 0 失败 0」，直接把原因摆到界面和日志里
        unrun_kind, unrun_reason = self._unrun_reason()
        if unrun_kind:
            if unrun_kind == "stop":
                self._render_unrun_state(
                    unrun_kind, unrun_reason, current, total,
                    stat_text=(f"通过: {passed}  失败: {failed}  跳过: {skipped}" if results else None),
                )
                self.log_message(
                    f"测试已停止（未完成）: 已测={len(results)}, 通过={passed}, 失败={failed}。"
                    f"原因: {unrun_reason}",
                    "WARNING",
                )
            else:
                self._render_unrun_state(unrun_kind, unrun_reason, current, total)
                self.log_message(f"测试中断，未测试任何故障码。原因: {unrun_reason}", "ERROR")
            self._report_batch_start_time = None
            self.test_completed.emit(results)
            return

        if self.progress_bar.value() < total:
            self.progress_bar.setValue(total)
        self.progress_bar.setFormat("100%")
        self._set_state_badge("已完成", failed=failed)
        self.stat_label.setText(f"通过: {passed}  失败: {failed}  跳过: {skipped}")
        self.progress_label.setText(
            f"状态=已完成 | 进度: {self.progress_bar.value()}/{total} "
            f"| 通过={passed} 失败={failed}"
        )

        if self._test_logger and results and self._report_batch_start_time is not None:
            try:
                self._test_logger.log_test_batch(
                    results,
                    test_type="fault",
                    start_time=self._report_batch_start_time,
                    project_name=getattr(self, "_current_project_name", "") or "",
                )
                self.log_message(
                    f"测试报告已保存 | 项目: {getattr(self, '_current_project_name', '') or '(未填)'}",
                    "INFO",
                )
            except Exception as e:
                self.log_message(f"\u4fdd\u5b58\u6545\u969c\u7801\u6d4b\u8bd5\u62a5\u544a\u5931\u8d25: {e}", "ERROR")
        self._report_batch_start_time = None

        # 更新日志
        self.log_message(f"测试完成: 总数={len(results)}, 通过={passed}, 失败={failed}", "INFO")

        # 发送信号
        self.test_completed.emit(results)

    def _append_check_row(self, result: TestResult, check):
        """追加单个检查项到详情表格"""
        row = self.detail_table.rowCount()
        self.detail_table.insertRow(row)

        left = Qt.AlignLeft | Qt.AlignVCenter
        center = Qt.AlignCenter

        def _set(col, text, align=left, color=None):
            item = QTableWidgetItem(str(text))
            item.setTextAlignment(align)
            if color is not None:
                item.setForeground(QColor(color))
            self.detail_table.setItem(row, col, item)

        _set(0, result.fault_name or "")
        _set(1, check.check_type.value)
        label = "对内" if check.check_type.name.startswith("INNER") else ("对外" if check.check_type.name.startswith("OUTER") else "其他")
        _set(2, label)
        _set(3, str(check.expected_value) if check.expected_value is not None else "", center)
        _set(4, str(check.actual_value) if check.actual_value is not None else "", center)
        status_text = "通过" if check.is_passed() else "失败"
        _set(
            5,
            status_text,
            center,
            COLORS['success'] if check.is_passed() else COLORS['error'],
        )
        _set(6, check.message or "")
        self.detail_table.scrollToBottom()

    def update_detail_table(self, result: TestResult):
        """更新详情表格（追加所有检查项，不清空已有数据）"""
        for check in result.checks:
            self._append_check_row(result, check)

    def log_message(self, message: str, level: str = "INFO"):
        """记录日志消息"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] [{level}] {message}"
        # 多行提示（如 CAN 发送失败的排查步骤）走 HTML 追加，需显式换行，否则会被折叠成一行
        log_msg = log_msg.replace("\n", "<br/>")

        colors = {
            "INFO": COLORS['text'],
            "WARNING": COLORS['warning'],
            "ERROR": COLORS['error'],
            "DEBUG": COLORS['text_dim']
        }

        color = colors.get(level, COLORS['text'])
        # 普通信息与默认文字同色：不写死颜色，切换主题后旧日志仍看得清
        if color == COLORS['text']:
            self.log_text.append(log_msg)
        else:
            self.log_text.append(f'<font color="{color}">{log_msg}</font>')

        # 限制日志行数
        max_lines = 1000
        if self.log_text.document().lineCount() > max_lines:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, max_lines // 2)
            cursor.removeSelectedText()

    def reset(self):
        """重置面板"""
        # 停止测试
        self.stop_test()

        # 清空数据
        self.test_results.clear()
        self.log_text.clear()
        self.detail_table.setRowCount(0)

        # 重置进度
        self.progress_bar.setVisible(True)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self._set_state_badge("就绪")
        if hasattr(self, "stat_label"):
            self.stat_label.setText("通过: 0  失败: 0  跳过: 0")
        self.progress_label.setText("状态=就绪 | 进度: 0/0 | —")

        # 重置按钮状态
        self.start_test_btn.setEnabled(True)
        self.stop_test_btn.setEnabled(False)
        self.step_test_btn.setEnabled(True)
