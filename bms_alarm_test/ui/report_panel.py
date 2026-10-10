"""批量测试报告页：列表 + 筛选 + 统计 + 详情。"""

from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bms_alarm_test.logger.report_exporter import ReportExporter
from bms_alarm_test.logger.test_logger import TestLogger, is_passed_status
from bms_alarm_test.ui.panel_style import (
    btn_danger,
    btn_neutral,
    btn_primary,
    btn_success,
    LeftAlignDelegate,
    button_fixed_size_qss,
    compact_qss,
    table_qss,
)
from shared.style import COLORS, themed_qss

PASS_LABELS = {"PASS", "PASSED", "通过", "成功", "OK"}
# 「查看详情」按钮 + 行高：行高必须大于按钮高度，否则底部会被裁切
DETAIL_BTN_W = 88
DETAIL_BTN_H = 26
DETAIL_COL_MIN_W = 120
REPORT_ROW_H = 48


def _label_color_qss(label, base: str):
    """标签文字色随主题变化。颜色名（COLORS 的 key，如 'success'）放在 holder 里，
    切换主题时按当前色表重画；闭包里不放控件本身，避免注册表长期持有控件。"""
    holder = {"key": None}

    def factory() -> str:
        key = holder["key"]
        return f"color: {COLORS[key] if key else COLORS['text']}; {base}"

    themed_qss(label, factory)
    label._color_holder = (holder, factory)


def _set_label_color(label, key):
    """设置标签颜色：key 为 COLORS 的颜色名，None 表示普通文字色"""
    holder, factory = label._color_holder
    holder["key"] = key
    label.setStyleSheet(factory())


class ReportPanel(QWidget):
    """Show one report row per completed batch."""

    report_exported = pyqtSignal(str)
    report_cleared = pyqtSignal()

    def __init__(self, test_logger: TestLogger = None, parent=None):
        super().__init__(parent)
        themed_qss(self, compact_qss)
        self.test_logger = test_logger
        self.report_exporter = ReportExporter()
        self.reports = []
        self._filtered_reports = []

        self.setup_ui()
        self.setup_connections()
        if self.test_logger:
            self.refresh_report()

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        control_group = QGroupBox("报告控制")
        control_layout = QHBoxLayout(control_group)
        control_layout.setSpacing(8)

        self.refresh_btn = QPushButton("刷新报告")
        themed_qss(self.refresh_btn, lambda: btn_primary() + button_fixed_size_qss(96, 30))
        self.batch_export_btn = QPushButton("批量导出")
        themed_qss(self.batch_export_btn, lambda: btn_success() + button_fixed_size_qss(96, 30))
        self.clear_btn = QPushButton("清空报告")
        themed_qss(self.clear_btn, lambda: btn_danger() + button_fixed_size_qss(96, 30))
        control_layout.addWidget(self.refresh_btn)
        control_layout.addWidget(self.batch_export_btn)
        control_layout.addWidget(self.clear_btn)

        control_layout.addSpacing(12)
        control_layout.addWidget(self._make_filter_label("测试类型"))
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部", "故障码测试", "阈值测试"])
        self.type_filter.setMinimumWidth(110)
        control_layout.addWidget(self.type_filter)

        control_layout.addWidget(self._make_filter_label("状态"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "通过", "失败"])
        self.status_filter.setMinimumWidth(90)
        control_layout.addWidget(self.status_filter)

        control_layout.addStretch(1)

        self.summary_total = self._make_stat_label("报告", "0")
        self.summary_pass = self._make_stat_label("通过", "0")
        self.summary_fail = self._make_stat_label("失败", "0")
        self.summary_rate = self._make_stat_label("平均通过率", "0.0%")
        control_layout.addWidget(self.summary_total)
        control_layout.addWidget(self.summary_pass)
        control_layout.addWidget(self.summary_fail)
        control_layout.addWidget(self.summary_rate)

        self.status_label = QLabel("就绪")
        themed_qss(self.status_label, lambda: f"color: {COLORS['text_dim']}; padding: 0 4px;")
        control_layout.addWidget(self.status_label)
        root.addWidget(control_group, 0)

        table_group = QGroupBox("测试报告列表")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(6, 8, 6, 6)

        self.report_table = QTableWidget()
        self.report_table.setColumnCount(10)
        self.report_table.setHorizontalHeaderLabels([
            "项目名称", "测试时间", "测试类型", "耗时", "测试数量",
            "通过", "失败", "通过率", "状态", "操作",
        ])
        header = self.report_table.horizontalHeader()
        header.setMinimumSectionSize(0)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        # 项目名称：表头与内容都左对齐，避免「表头居中、内容靠左」对不齐
        try:
            header.model().setHeaderData(
                0, Qt.Horizontal, int(Qt.AlignLeft | Qt.AlignVCenter), Qt.TextAlignmentRole
            )
        except Exception:
            pass
        # 强制左对齐绘制，不依赖 setTextAlignment（部分环境 QSS/主题会冲掉）
        LeftAlignDelegate.attach(self.report_table, [0], self.report_table)
        self._report_column_weights = [1.7, 2.0, 1.15, 0.85, 0.9, 0.75, 0.75, 0.95, 0.85, 1.2]
        self._report_column_min_widths = [120, 155, 100, 70, 75, 60, 60, 80, 70, DETAIL_COL_MIN_W]
        themed_qss(self.report_table, lambda: (
            table_qss()
            + f"\nQTableWidget {{ font-size: 12px; background-color: {COLORS['bg_panel']}; }}"
            + "\nQTableWidget::item { padding: 8px 6px; }"
            + "\nQHeaderView::section { font-size: 12px; padding: 8px 6px; }"
            # 项目名称表头左对齐，与内容同一左缘
            + "\nQHeaderView::section:first { text-align: left; padding-left: 10px; }"
        ))
        self.report_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.report_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.report_table.setAlternatingRowColors(True)
        self.report_table.setWordWrap(False)
        self.report_table.setShowGrid(True)
        # 行高固定且大于按钮高度，避免「查看详情」底部被裁切
        vheader = self.report_table.verticalHeader()
        vheader.setVisible(True)
        vheader.setDefaultSectionSize(REPORT_ROW_H)
        vheader.setMinimumSectionSize(REPORT_ROW_H)
        vheader.setSectionResizeMode(QHeaderView.Fixed)
        self.report_table.setMinimumHeight(280)
        self.report_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.report_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table_layout.addWidget(self.report_table)
        root.addWidget(table_group, 1)
        QTimer.singleShot(0, self._resize_report_columns)

        hint = QLabel("提示：双击行或点击「查看详情」可打开完整报告明细")
        themed_qss(hint, lambda: f"color: {COLORS['text_dim']}; font-size: 11px; padding: 0 2px;")
        root.addWidget(hint, 0)

    @staticmethod
    def _make_filter_label(text: str) -> QLabel:
        label = QLabel(text)
        themed_qss(label, lambda: f"color: {COLORS['text_dim']}; font-size: 12px; padding: 0 2px;")
        return label

    def _make_stat_label(self, title: str, value: str):
        frame = QFrame()
        themed_qss(frame, lambda: (
            f"QFrame {{ background: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px 8px; }}"
        ))
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        title_label = QLabel(title)
        themed_qss(title_label, lambda: f"color: {COLORS['text_dim']}; font-size: 11px; border: none;")
        value_label = QLabel(value)
        value_label.setObjectName(f"stat_{title}")
        _label_color_qss(value_label, "font-size: 13px; font-weight: bold; border: none;")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        frame._value_label = value_label
        return frame

    @staticmethod
    def _set_stat(frame: QFrame, value: str, color: str = None):
        """color 为 COLORS 的颜色名（如 'success'），None 为普通文字色"""
        label = frame._value_label
        label.setText(value)
        _set_label_color(label, color)

    def setup_connections(self):
        self.refresh_btn.clicked.connect(self.refresh_report)
        self.batch_export_btn.clicked.connect(self.export_all_reports)
        self.clear_btn.clicked.connect(self.clear_report)
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        self.report_table.cellDoubleClicked.connect(self._on_report_double_clicked)

    def showEvent(self, event):
        super().showEvent(event)
        self._resize_report_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_report_columns()

    def _resize_report_columns(self):
        if not hasattr(self, "report_table"):
            return
        table = self.report_table
        # 竖向滚动条出现后 viewport 会变窄，列宽必须按滚动条扣除后的宽度算
        viewport_width = table.viewport().width()
        if viewport_width <= 0:
            return
        vbar = table.verticalScrollBar()
        if vbar.isVisible():
            viewport_width = max(0, viewport_width)  # viewport 已扣除滚动条
        minimums = list(self._report_column_min_widths)
        # 操作列必须容得下「查看详情」按钮
        minimums[-1] = max(minimums[-1], DETAIL_COL_MIN_W)
        weights = self._report_column_weights
        minimum_total = sum(minimums)
        if viewport_width <= minimum_total:
            # 宽度不够时保证操作列完整，其余列用最小宽，靠横向滚动查看
            widths = minimums[:]
        else:
            extra = viewport_width - minimum_total
            weight_total = sum(weights)
            widths = [
                minimum + int(extra * weight / weight_total)
                for minimum, weight in zip(minimums, weights)
            ]
            # 余数补给操作列，避免按钮右侧被裁切
            widths[-1] += viewport_width - sum(widths)
            if widths[-1] < DETAIL_COL_MIN_W:
                widths[-1] = DETAIL_COL_MIN_W
        header = table.horizontalHeader()
        for column, width in enumerate(widths):
            header.resizeSection(column, max(1, width))

    def _ensure_detail_buttons_visible(self):
        """延迟校正：保证每行操作列按钮未被行高裁切。"""
        table = self.report_table
        if table is None:
            return
        for row in range(table.rowCount()):
            if table.rowHeight(row) < REPORT_ROW_H:
                table.setRowHeight(row, REPORT_ROW_H)
            cell = table.cellWidget(row, 9)
            if cell is None:
                continue
            # 单元格控件撑满单元格高度，按钮在其中居中
            cell.setMinimumHeight(REPORT_ROW_H - 4)
            btn = cell.findChild(QPushButton, "reportDetailBtn")
            if btn is not None:
                btn.setFixedSize(DETAIL_BTN_W, DETAIL_BTN_H)

    def set_test_logger(self, test_logger: TestLogger):
        self.test_logger = test_logger
        self.refresh_report()

    @staticmethod
    def _format_time(timestamp):
        if not timestamp:
            return "-"
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _test_type_text(test_type):
        return {"fault": "故障码测试", "threshold": "阈值测试"}.get(
            test_type, str(test_type or "未知测试")
        )

    @staticmethod
    def _is_pass_status(status) -> bool:
        return is_passed_status(status)

    @staticmethod
    def _status_text(status):
        return "通过" if ReportPanel._is_pass_status(status) else "失败"

    @staticmethod
    def _item(value, alignment=Qt.AlignCenter):
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(alignment)
        return item

    @staticmethod
    def _make_detail_button(run_id: int, on_click) -> QWidget:
        # 完整覆盖全局 QPushButton 样式；固定尺寸 + 行高，保证底部不被裁切
        btn = QPushButton("查看详情")
        btn.setObjectName("reportDetailBtn")
        btn.setFixedSize(DETAIL_BTN_W, DETAIL_BTN_H)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn.setFocusPolicy(Qt.NoFocus)
        themed_qss(btn, lambda: (
            f"""
            QPushButton#reportDetailBtn {{
                background-color: {COLORS['tint_bg']};
                color: {COLORS['tint_fg']};
                border: 1px solid {COLORS['tint_border']};
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                font-family: 'Microsoft YaHei', 'Inter', sans-serif;
                letter-spacing: 0px;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton#reportDetailBtn:hover {{
                background-color: {COLORS['accent']};
                color: #ffffff;
                border-color: {COLORS['accent']};
            }}
            QPushButton#reportDetailBtn:pressed {{
                background-color: #1d4ed8;
                color: #ffffff;
                border-color: #1d4ed8;
            }}
            """
        ))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda checked=False, rid=run_id: on_click(rid))

        # 容器撑满单元格，按钮在容器内居中（上下左右都留空）
        wrap = QWidget()
        wrap.setObjectName("reportDetailCell")
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        wrap.setMinimumHeight(REPORT_ROW_H - 4)
        wrap.setStyleSheet("background: transparent; margin: 0px; padding: 0px;")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(0)
        layout.addWidget(btn, 0, Qt.AlignCenter)
        return wrap

    def _selected_type_key(self):
        return {
            "故障码测试": "fault",
            "阈值测试": "threshold",
        }.get(self.type_filter.currentText())

    def _selected_status_text(self):
        return self.status_filter.currentText()

    def _apply_filters(self):
        type_key = self._selected_type_key()
        status_text = self._selected_status_text()
        filtered = []
        for report in self.reports:
            if type_key and report.get("test_type") != type_key:
                continue
            if status_text in ("通过", "失败") and self._status_text(report.get("status")) != status_text:
                continue
            filtered.append(report)
        self._filtered_reports = filtered
        self._populate_table(filtered)

    def _populate_table(self, reports):
        self.report_table.setRowCount(0)
        for row, report in enumerate(reports):
            self.report_table.insertRow(row)
            # 固定行高，确保单元格内「查看详情」按钮完整显示
            self.report_table.setRowHeight(row, REPORT_ROW_H)
            project = (report.get("project_name") or "").strip() or "（未填写）"
            proj_item = self._item(project, int(Qt.AlignLeft | Qt.AlignVCenter))
            if project == "（未填写）":
                proj_item.setForeground(QColor(COLORS["text_dim"]))
            self.report_table.setItem(row, 0, proj_item)
            self.report_table.setItem(row, 1, self._item(self._format_time(report.get("start_timestamp"))))
            self.report_table.setItem(row, 2, self._item(self._test_type_text(report.get("test_type"))))
            self.report_table.setItem(
                row, 3, self._item(f"{report.get('duration_sec') or 0:.1f}s")
            )
            self.report_table.setItem(row, 4, self._item(report.get("total_count", 0)))

            pass_item = self._item(report.get("passed_count", 0))
            pass_item.setForeground(QColor(COLORS["success"]))
            self.report_table.setItem(row, 5, pass_item)

            fail_count = report.get("failed_count", 0) or 0
            fail_item = self._item(fail_count)
            fail_item.setForeground(QColor(COLORS["error"] if fail_count else COLORS["text_dim"]))
            self.report_table.setItem(row, 6, fail_item)

            total = report.get("total_count") or 0
            rate = (report.get("passed_count") or 0) / total * 100 if total else 0.0
            rate_item = self._item(f"{rate:.1f}%")
            rate_item.setForeground(
                QColor(COLORS["success"] if rate >= 100 else COLORS["warning"] if rate > 0 else COLORS["error"])
            )
            self.report_table.setItem(row, 7, rate_item)

            passed = self._is_pass_status(report.get("status"))
            status_item = self._item(self._status_text(report.get("status")))
            status_item.setForeground(QColor(COLORS["success"] if passed else COLORS["error"]))
            font = QFont()
            font.setBold(True)
            status_item.setFont(font)
            self.report_table.setItem(row, 8, status_item)

            self.report_table.setCellWidget(
                row, 9,
                self._make_detail_button(report.get("id"), self.show_report_detail),
            )
            # 再确认一次行高与单元格控件尺寸
            self.report_table.setRowHeight(row, REPORT_ROW_H)
            cell = self.report_table.cellWidget(row, 9)
            if cell is not None:
                cell.setMinimumHeight(REPORT_ROW_H - 4)

        self._resize_report_columns()
        self._update_summary(reports)
        # 行数变化后滚动条才会出现，延迟再排一次列宽，避免操作列被裁切
        QTimer.singleShot(0, self._resize_report_columns)
        QTimer.singleShot(0, self._ensure_detail_buttons_visible)

    def _update_summary(self, reports):
        total_reports = len(reports)
        pass_reports = sum(1 for r in reports if self._is_pass_status(r.get("status")))
        fail_reports = total_reports - pass_reports
        sum_total = sum(r.get("total_count") or 0 for r in reports)
        sum_passed = sum(r.get("passed_count") or 0 for r in reports)
        rate = sum_passed / sum_total * 100 if sum_total else 0.0
        self._set_stat(self.summary_total, str(total_reports))
        self._set_stat(self.summary_pass, str(pass_reports), "success")
        self._set_stat(self.summary_fail, str(fail_reports), "error" if fail_reports else "text_dim")
        self._set_stat(self.summary_rate, f"{rate:.1f}%", "success" if rate >= 100 else "warning")
        self.status_label.setText(f"共 {total_reports} 条测试报告")

    def refresh_report(self):
        if not self.test_logger:
            self.reports = []
            self._filtered_reports = []
            self.report_table.setRowCount(0)
            self._update_summary([])
            return
        try:
            self.test_logger.repair_batch_statistics()
        except Exception:
            pass
        self.reports = self.test_logger.get_test_batches(limit=1000)
        self._apply_filters()

    def _on_report_double_clicked(self, row, _column):
        if 0 <= row < len(self._filtered_reports):
            self.show_report_detail(self._filtered_reports[row]["id"])

    @staticmethod
    def _result_name(result):
        return result.get("fault_name") or result.get("pid_name") or result.get("test_id") or "-"

    @staticmethod
    def _result_code(result):
        metadata = result.get("metadata") or {}
        return metadata.get("fault_code") or metadata.get("pid") or result.get("test_id") or "-"

    @staticmethod
    def _check_summary(result):
        checks = result.get("checks") or []
        if not checks:
            return "无检查项"
        parts = []
        for check in checks:
            check_type = check.get("type") or check.get("name") or "检查"
            expected = check.get("expected_value", "-")
            actual = check.get("actual_value", "-")
            status = check.get("status", "")
            message = check.get("message") or ""
            text = f"{check_type}: 期望={expected}, 实际={actual} [{status}]"
            if message:
                text += f" {message}"
            parts.append(text)
        return "\n".join(parts)

    def show_report_detail(self, run_id):
        if not self.test_logger:
            return
        report = self.test_logger.get_test_batch(run_id)
        if not report:
            QMessageBox.warning(self, "提示", "找不到这条测试报告。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"测试报告详情 - {report.get('project_name') or self._format_time(report.get('start_timestamp'))}"
        )
        dialog.resize(1100, 680)
        dialog.setStyleSheet(compact_qss())
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        passed = self._is_pass_status(report.get("status"))
        status_text = self._status_text(report.get("status"))
        total = report.get("total_count") or 0
        passed_count = report.get("passed_count") or 0
        failed_count = report.get("failed_count") or 0
        rate = passed_count / total * 100 if total else 0.0

        summary_card = QFrame()
        summary_card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; }}"
        )
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(24)

        def add_kv(key, value, color=None):
            box = QVBoxLayout()
            box.setSpacing(2)
            key_label = QLabel(key)
            key_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; border: none;")
            value_label = QLabel(str(value))
            value_label.setStyleSheet(
                f"color: {color or COLORS['text']}; font-size: 16px; font-weight: bold; border: none;"
            )
            box.addWidget(key_label)
            box.addWidget(value_label)
            summary_layout.addLayout(box)

        add_kv("项目名称", (report.get("project_name") or "（未填写）"))
        add_kv("测试时间", self._format_time(report.get("start_timestamp")))
        add_kv("测试类型", self._test_type_text(report.get("test_type")))
        add_kv("测试数量", total)
        add_kv("通过", passed_count, COLORS["success"])
        add_kv("失败", failed_count, COLORS["error"] if failed_count else COLORS["text_dim"])
        add_kv("通过率", f"{rate:.1f}%", COLORS["success"] if rate >= 100 else COLORS["warning"])
        add_kv("状态", status_text, COLORS["success"] if passed else COLORS["error"])
        add_kv("耗时", f"{report.get('duration_sec') or 0:.1f}s")
        summary_layout.addStretch(1)
        layout.addWidget(summary_card, 0)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("明细筛选"))
        detail_status_filter = QComboBox()
        detail_status_filter.addItems(["全部", "通过", "失败"])
        detail_status_filter.setMinimumWidth(100)
        filter_row.addWidget(detail_status_filter)
        detail_count_label = QLabel("")
        detail_count_label.setStyleSheet(f"color: {COLORS['text_dim']};")
        filter_row.addWidget(detail_count_label)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        detail_table = QTableWidget()
        detail_table.setColumnCount(6)
        detail_table.setHorizontalHeaderLabels([
            "测试项", "编号", "状态", "耗时", "检查项", "错误信息",
        ])
        detail_header = detail_table.horizontalHeader()
        detail_header.setSectionResizeMode(QHeaderView.Interactive)
        detail_header.setStretchLastSection(True)
        detail_table.setColumnWidth(0, 180)
        detail_table.setColumnWidth(1, 100)
        detail_table.setColumnWidth(2, 70)
        detail_table.setColumnWidth(3, 70)
        detail_table.setColumnWidth(4, 420)
        detail_table.setWordWrap(True)
        detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        detail_table.setAlternatingRowColors(True)
        detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        detail_table.verticalHeader().setDefaultSectionSize(48)
        detail_table.setStyleSheet(
            table_qss()
            + "\nQTableWidget { font-size: 12px; background-color: #ffffff; }"
            + "\nQTableWidget::item { padding: 6px 4px; }"
        )
        LeftAlignDelegate.attach(detail_table, [0, 4, 5], detail_table)
        layout.addWidget(detail_table, 1)

        details = report.get("details") or []

        def populate_details():
            status_text_filter = detail_status_filter.currentText()
            rows = []
            for result in details:
                item_pass = self._is_pass_status(result.get("overall_status"))
                if status_text_filter == "通过" and not item_pass:
                    continue
                if status_text_filter == "失败" and item_pass:
                    continue
                rows.append((result, item_pass))
            detail_table.setRowCount(len(rows))
            for row, (result, item_pass) in enumerate(rows):
                detail_table.setItem(row, 0, self._item(self._result_name(result), Qt.AlignLeft | Qt.AlignVCenter))
                detail_table.setItem(row, 1, self._item(self._result_code(result)))
                status_item = self._item("通过" if item_pass else "失败")
                status_item.setForeground(QColor(COLORS["success"] if item_pass else COLORS["error"]))
                font = QFont()
                font.setBold(True)
                status_item.setFont(font)
                detail_table.setItem(row, 2, status_item)
                detail_table.setItem(row, 3, self._item(f"{result.get('duration', 0):.2f}s"))
                detail_table.setItem(row, 4, self._item(self._check_summary(result), Qt.AlignLeft | Qt.AlignVCenter))
                detail_table.setItem(row, 5, self._item(result.get("error_message") or "", Qt.AlignLeft | Qt.AlignVCenter))
            detail_count_label.setText(f"显示 {len(rows)} / {len(details)} 条")

        detail_status_filter.currentIndexChanged.connect(populate_details)
        populate_details()

        buttons = QHBoxLayout()
        export_btn = QPushButton("导出此报告")
        export_btn.setStyleSheet(btn_success() + button_fixed_size_qss(110, 30))
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(btn_neutral() + button_fixed_size_qss(88, 30))
        buttons.addStretch(1)
        buttons.addWidget(export_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        close_btn.clicked.connect(dialog.accept)
        export_btn.clicked.connect(lambda: self.export_single_report(report))
        dialog.exec_()

    def export_single_report(self, report):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出单个测试报告",
            f"bms_test_report_{timestamp}.xlsx",
            "Excel 文件 (*.xlsx)",
        )
        if not filename:
            return
        if self.report_exporter.export_batch_report(report, filename):
            self.status_label.setText(f"已导出：{filename}")
            self.report_exported.emit(filename)
        else:
            QMessageBox.warning(self, "导出失败", "单个测试报告导出失败。")

    def export_all_reports(self):
        if not self.test_logger or not self._filtered_reports:
            QMessageBox.information(self, "提示", "当前没有可导出的测试报告。")
            return
        full_reports = [
            self.test_logger.get_test_batch(report["id"])
            for report in self._filtered_reports
        ]
        full_reports = [report for report in full_reports if report]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "批量导出测试报告",
            f"bms_test_reports_{timestamp}.xlsx",
            "Excel 文件 (*.xlsx)",
        )
        if not filename:
            return
        if self.report_exporter.export_batch_reports(full_reports, filename):
            self.status_label.setText(f"已批量导出：{filename}")
            self.report_exported.emit(filename)
        else:
            QMessageBox.warning(self, "导出失败", "批量测试报告导出失败。")

    def clear_report(self):
        if not self.test_logger:
            return
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空所有批量测试报告吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        deleted = self.test_logger.clear_report_batches()
        self.refresh_report()
        self.report_cleared.emit()
        self.status_label.setText(f"已清空 {deleted} 条测试报告")

    def export_report(self):
        """Compatibility alias for older callers."""
        self.export_all_reports()

    def load_more_results(self):
        """Compatibility alias; the full report list is loaded at once."""
        self.refresh_report()

    def reset(self):
        self.reports = []
        self._filtered_reports = []
        self.report_table.setRowCount(0)
        self._update_summary([])
        self.status_label.setText("就绪")
