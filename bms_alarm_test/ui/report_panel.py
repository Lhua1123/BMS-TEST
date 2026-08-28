"""Simplified batch test report page."""

from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
)
from PyQt5.QtWidgets import QWidget

from bms_alarm_test.logger.report_exporter import ReportExporter
from bms_alarm_test.logger.test_logger import TestLogger
from bms_alarm_test.ui.panel_style import BTN_DANGER, BTN_PRIMARY, BTN_SUCCESS, COMPACT_QSS
from shared.style import COLORS


class ReportPanel(QWidget):
    """Show one report row per completed batch."""

    report_exported = pyqtSignal(str)
    report_cleared = pyqtSignal()

    def __init__(self, test_logger: TestLogger = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMPACT_QSS)
        self.test_logger = test_logger
        self.report_exporter = ReportExporter()
        self.reports = []

        self.setup_ui()
        self.setup_connections()
        if self.test_logger:
            self.refresh_report()

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        control_group = QGroupBox("\u62a5\u544a\u63a7\u5236")
        control_layout = QHBoxLayout(control_group)
        self.refresh_btn = QPushButton("\u5237\u65b0\u62a5\u544a")
        self.refresh_btn.setStyleSheet(BTN_PRIMARY)
        self.batch_export_btn = QPushButton("\u6279\u91cf\u5bfc\u51fa")
        self.batch_export_btn.setStyleSheet(BTN_SUCCESS)
        self.clear_btn = QPushButton("\u6e05\u7a7a\u62a5\u544a")
        self.clear_btn.setStyleSheet(BTN_DANGER)
        self.status_label = QLabel("\u5c31\u7eea")
        control_layout.addWidget(self.refresh_btn)
        control_layout.addWidget(self.batch_export_btn)
        control_layout.addWidget(self.clear_btn)
        control_layout.addStretch(1)
        control_layout.addWidget(self.status_label)
        root.addWidget(control_group, 0)

        self.report_table = QTableWidget()
        self.report_table.setColumnCount(8)
        self.report_table.setHorizontalHeaderLabels([
            "\u6d4b\u8bd5\u65f6\u95f4", "\u6d4b\u8bd5\u7c7b\u578b", "\u6d4b\u8bd5\u6570\u91cf", "\u901a\u8fc7", "\u5931\u8d25", "\u901a\u8fc7\u7387", "\u72b6\u6001", "\u64cd\u4f5c"
        ])
        header = self.report_table.horizontalHeader()
        header.setMinimumSectionSize(0)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self._report_column_weights = [2.2, 1.45, 1.0, 0.9, 0.9, 1.05, 0.95, 1.25]
        self._report_column_min_widths = [170, 125, 90, 75, 75, 90, 90, 120]
        self.report_table.setStyleSheet(
            COMPACT_QSS
            + "\nQTableWidget { font-size: 12px; }"
            + "\nQTableWidget::item { padding: 6px 8px; }"
            + "\nQHeaderView::section { font-size: 12px; padding: 7px 8px; }"
        )
        self.report_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.report_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.report_table.setAlternatingRowColors(True)
        self.report_table.setWordWrap(False)
        self.report_table.setMinimumHeight(220)
        root.addWidget(self.report_table, 1)

    def setup_connections(self):
        self.refresh_btn.clicked.connect(self.refresh_report)
        self.batch_export_btn.clicked.connect(self.export_all_reports)
        self.clear_btn.clicked.connect(self.clear_report)
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
        viewport_width = self.report_table.viewport().width()
        if viewport_width <= 0:
            return
        minimums = self._report_column_min_widths
        weights = self._report_column_weights
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
        header = self.report_table.horizontalHeader()
        for column, width in enumerate(widths):
            header.resizeSection(column, max(1, width))

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
        return {"fault": "\u6545\u969c\u7801\u6d4b\u8bd5", "threshold": "\u9608\u503c\u6d4b\u8bd5"}.get(test_type, str(test_type or "\u672a\u77e5\u6d4b\u8bd5"))

    @staticmethod
    def _status_text(status):
        return "\u901a\u8fc7" if status == "PASS" else "\u5931\u8d25"

    @staticmethod
    def _item(value, alignment=Qt.AlignLeft | Qt.AlignVCenter):
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(alignment)
        return item

    def refresh_report(self):
        if not self.test_logger:
            self.reports = []
            self.report_table.setRowCount(0)
            return

        self.reports = self.test_logger.get_test_batches(limit=1000)
        self.report_table.setRowCount(0)
        for row, report in enumerate(self.reports):
            self.report_table.insertRow(row)
            self.report_table.setItem(row, 0, self._item(self._format_time(report["start_timestamp"])))
            self.report_table.setItem(row, 1, self._item(self._test_type_text(report["test_type"])))
            self.report_table.setItem(row, 2, self._item(report["total_count"], Qt.AlignCenter))
            self.report_table.setItem(row, 3, self._item(report["passed_count"], Qt.AlignCenter))
            self.report_table.setItem(row, 4, self._item(report["failed_count"], Qt.AlignCenter))
            total = report["total_count"] or 0
            rate = report["passed_count"] / total * 100 if total else 0.0
            self.report_table.setItem(row, 5, self._item(f"{rate:.1f}%", Qt.AlignCenter))
            status_item = self._item(self._status_text(report["status"]), Qt.AlignCenter)
            status_item.setForeground(QColor(COLORS["success"] if report["status"] == "PASS" else COLORS["error"]))
            self.report_table.setItem(row, 6, status_item)

            detail_btn = QPushButton("\u67e5\u770b\u8be6\u60c5")
            detail_btn.clicked.connect(lambda checked=False, run_id=report["id"]: self.show_report_detail(run_id))
            self.report_table.setCellWidget(row, 7, detail_btn)

        self._resize_report_columns()
        self.status_label.setText(f"\u5171 {len(self.reports)} \u6761\u6d4b\u8bd5\u62a5\u544a")

    def _on_report_double_clicked(self, row, _column):
        if 0 <= row < len(self.reports):
            self.show_report_detail(self.reports[row]["id"])

    @staticmethod
    def _result_name(result):
        return result.get("fault_name") or result.get("pid_name") or "-"

    @staticmethod
    def _result_code(result):
        metadata = result.get("metadata") or {}
        return metadata.get("fault_code") or metadata.get("pid") or result.get("test_id") or "-"

    @staticmethod
    def _check_summary(result):
        checks = result.get("checks") or []
        if not checks:
            return "\u65e0\u68c0\u67e5\u9879"
        parts = []
        for check in checks:
            check_type = check.get("type") or check.get("name") or "\u68c0\u67e5"
            expected = check.get("expected_value", "-")
            actual = check.get("actual_value", "-")
            status = check.get("status", "")
            message = check.get("message") or ""
            text = f"{check_type}: \u671f\u671b={expected}, \u5b9e\u9645={actual} [{status}]"
            if message:
                text += f" {message}"
            parts.append(text)
        return "\n".join(parts)

    def show_report_detail(self, run_id):
        if not self.test_logger:
            return
        report = self.test_logger.get_test_batch(run_id)
        if not report:
            QMessageBox.warning(self, "\u63d0\u793a", "\u627e\u4e0d\u5230\u8fd9\u6761\u6d4b\u8bd5\u62a5\u544a\u3002")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"\u6d4b\u8bd5\u62a5\u544a\u8be6\u60c5 - {self._format_time(report['start_timestamp'])}")
        dialog.resize(1050, 620)
        layout = QVBoxLayout(dialog)

        summary = QLabel(
            f"\u6d4b\u8bd5\u65f6\u95f4\uff1a{self._format_time(report['start_timestamp'])}    "
            f"\u6d4b\u8bd5\u7c7b\u578b\uff1a{self._test_type_text(report['test_type'])}    "
            f"\u603b\u6570\uff1a{report['total_count']}    \u901a\u8fc7\uff1a{report['passed_count']}    "
            f"\u5931\u8d25\uff1a{report['failed_count']}    \u72b6\u6001\uff1a{self._status_text(report['status'])}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        detail_table = QTableWidget()
        detail_table.setColumnCount(6)
        detail_table.setHorizontalHeaderLabels([
            "\u6d4b\u8bd5\u9879\u76ee", "\u7f16\u53f7", "\u72b6\u6001", "\u8017\u65f6", "\u68c0\u67e5\u9879", "\u9519\u8bef\u4fe1\u606f"
        ])
        detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        detail_table.horizontalHeader().setStretchLastSection(True)
        detail_table.setWordWrap(True)
        detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        detail_table.setAlternatingRowColors(True)
        details = report.get("details") or []
        detail_table.setRowCount(len(details))
        for row, result in enumerate(details):
            detail_table.setItem(row, 0, self._item(self._result_name(result)))
            detail_table.setItem(row, 1, self._item(self._result_code(result)))
            status = result.get("overall_status", "")
            status_text = "\u901a\u8fc7" if status in ("\u901a\u8fc7", "PASSED", "PASS") else "\u5931\u8d25"
            status_item = self._item(status_text, Qt.AlignCenter)
            status_item.setForeground(QColor(COLORS["success"] if status_text == "\u901a\u8fc7" else COLORS["error"]))
            detail_table.setItem(row, 2, status_item)
            detail_table.setItem(row, 3, self._item(f"{result.get('duration', 0):.2f}s", Qt.AlignCenter))
            detail_table.setItem(row, 4, self._item(self._check_summary(result)))
            detail_table.setItem(row, 5, self._item(result.get("error_message") or ""))
        detail_table.resizeColumnsToContents()
        layout.addWidget(detail_table, 1)

        buttons = QHBoxLayout()
        export_btn = QPushButton("\u5bfc\u51fa\u6b64\u62a5\u544a")
        export_btn.setStyleSheet(BTN_SUCCESS)
        close_btn = QPushButton("\u5173\u95ed")
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
            "\u5bfc\u51fa\u5355\u4e2a\u6d4b\u8bd5\u62a5\u544a",
            f"bms_test_report_{timestamp}.xlsx",
            "Excel \u6587\u4ef6 (*.xlsx)",
        )
        if not filename:
            return
        if self.report_exporter.export_batch_report(report, filename):
            self.status_label.setText(f"\u5df2\u5bfc\u51fa\uff1a{filename}")
            self.report_exported.emit(filename)
        else:
            QMessageBox.warning(self, "\u5bfc\u51fa\u5931\u8d25", "\u5355\u4e2a\u6d4b\u8bd5\u62a5\u544a\u5bfc\u51fa\u5931\u8d25\u3002")

    def export_all_reports(self):
        if not self.test_logger or not self.reports:
            QMessageBox.information(self, "\u63d0\u793a", "\u5f53\u524d\u6ca1\u6709\u53ef\u5bfc\u51fa\u7684\u6d4b\u8bd5\u62a5\u544a\u3002")
            return
        full_reports = [
            self.test_logger.get_test_batch(report["id"])
            for report in self.reports
        ]
        full_reports = [report for report in full_reports if report]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "\u6279\u91cf\u5bfc\u51fa\u6d4b\u8bd5\u62a5\u544a",
            f"bms_test_reports_{timestamp}.xlsx",
            "Excel \u6587\u4ef6 (*.xlsx)",
        )
        if not filename:
            return
        if self.report_exporter.export_batch_reports(full_reports, filename):
            self.status_label.setText(f"\u5df2\u6279\u91cf\u5bfc\u51fa\uff1a{filename}")
            self.report_exported.emit(filename)
        else:
            QMessageBox.warning(self, "\u5bfc\u51fa\u5931\u8d25", "\u6279\u91cf\u6d4b\u8bd5\u62a5\u544a\u5bfc\u51fa\u5931\u8d25\u3002")

    def clear_report(self):
        if not self.test_logger:
            return
        reply = QMessageBox.question(
            self,
            "\u786e\u8ba4\u6e05\u7a7a",
            "\u786e\u5b9a\u8981\u6e05\u7a7a\u6240\u6709\u6279\u91cf\u6d4b\u8bd5\u62a5\u544a\u5417\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\u3002",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        deleted = self.test_logger.clear_report_batches()
        self.refresh_report()
        self.report_cleared.emit()
        self.status_label.setText(f"\u5df2\u6e05\u7a7a {deleted} \u6761\u6d4b\u8bd5\u62a5\u544a")

    def export_report(self):
        """Compatibility alias for older callers."""
        self.export_all_reports()

    def load_more_results(self):
        """Compatibility alias; the full report list is loaded at once."""
        self.refresh_report()

    def reset(self):
        self.reports = []
        self.report_table.setRowCount(0)
        self.status_label.setText("\u5c31\u7eea")
