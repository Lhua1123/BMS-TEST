"""
故障期望值 / 回读信号配置对话框
可编辑每个故障码的验证期望值，并增删额外回读项。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bms_alarm_test.config.fault_mapping import FaultMapping
from bms_alarm_test.config.fault_verify_config import (
    FaultVerifyConfig,
    fault_key,
    fault_to_dict,
    get_fault_verify_config,
    reload_fault_mapping_with_overrides,
)

COLS = [
    "故障码",
    "域",
    "名称",
    "等级",
    "SysFail期望",
    "ErrTab期望",
    "对内信号",
    "对内期望",
    "对外信号",
    "对外期望",
    "对外Warning",
    "额外回读",
    "启用",
]

UI_FONT_PT = 13
TABLE_FONT_PT = 12
CELL_PAD_X = 16


class _LeftDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#3b82f6"))
            painter.setPen(QColor("#ffffff"))
        else:
            painter.setPen(QColor("#1f2937"))
        painter.setFont(option.font)
        text = index.data(Qt.DisplayRole)
        text = "" if text is None else str(text)
        painter.drawText(option.rect.adjusted(6, 0, -4, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        text = index.data(Qt.DisplayRole)
        text = "" if text is None else str(text)
        try:
            fm = QFontMetrics(option.font) if option.font is not None else QFontMetrics()
            w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
            h = fm.height()
        except Exception:
            w, h = len(text) * 14, 24
        return QSize(int(w) + CELL_PAD_X, max(h + 10, 28))


class FaultVerifyConfigDialog(QWidget):
    """故障期望值/回读配置面板（可嵌入选项卡）"""

    def __init__(self, parent: Optional[QWidget] = None,
                 fault_mapping: Optional[FaultMapping] = None,
                 embedded: bool = False):
        super().__init__(parent)
        self.embedded = embedded
        self.fault_mapping = fault_mapping
        self.config: FaultVerifyConfig = get_fault_verify_config()
        self._init_ui()
        self.reload_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.setFont(QFont("Microsoft YaHei", UI_FONT_PT))

        tip = QLabel(
            "说明：这里配置每个故障码验证时的期望值与回读信号（覆盖内置表）。\n"
            "「额外回读」JSON 形如: "
            '[{"name":"自定义","channel_role":"inner","signal_name":"XXX","message_name":"","expected":1}]。'
            " 启用=否 时测试列表会跳过该故障。改完点「保存并应用」。"
        )
        tip.setWordWrap(True)
        tip.setFont(QFont("Microsoft YaHei", UI_FONT_PT))
        layout.addWidget(tip)

        btn_row = QHBoxLayout()
        self.btn_extra = QPushButton("编辑额外回读…")
        self.btn_export = QPushButton("导出当前为默认")
        self.btn_reload_builtin = QPushButton("重载内置+覆盖")
        self.btn_save = QPushButton("保存并应用")
        self.btn_close = QPushButton("关闭")
        for b in (self.btn_extra, self.btn_export, self.btn_reload_builtin, self.btn_save, self.btn_close):
            b.setFont(QFont("Microsoft YaHei", UI_FONT_PT))
            b.setMinimumHeight(36)
            btn_row.addWidget(b)
        self.btn_close.setVisible(not self.embedded)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont("Microsoft YaHei", TABLE_FONT_PT))
        self.table.horizontalHeader().setFont(QFont("Microsoft YaHei", TABLE_FONT_PT, QFont.Bold))
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self._delegate = _LeftDelegate(self.table)
        for c in range(len(COLS)):
            self.table.setItemDelegateForColumn(c, self._delegate)
        self.table.viewport().installEventFilter(self)
        layout.addWidget(self.table, 1)

        self.btn_extra.clicked.connect(self._on_edit_extra)
        self.btn_export.clicked.connect(self._on_export_default)
        self.btn_reload_builtin.clicked.connect(self._on_reload_builtin)
        self.btn_save.clicked.connect(self._on_save_apply)
        if not self.embedded:
            self.btn_close.clicked.connect(self._on_close_clicked)

    def _on_close_clicked(self):
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QDialog):
                parent.accept()
                return
            parent = parent.parentWidget() if hasattr(parent, "parentWidget") else None
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ShiftModifier:
                bar = self.table.horizontalScrollBar()
                delta = event.angleDelta().y() or event.angleDelta().x()
                bar.setValue(bar.value() - delta)
                return True
        return super().eventFilter(obj, event)

    def _rows_from_mapping(self) -> List[Dict[str, Any]]:
        if not self.fault_mapping:
            return []
        items = [fault_to_dict(f) for f in self.fault_mapping.all_faults_raw()]
        items.sort(key=lambda x: (x.get("code", 0), x.get("domain", "")))
        return items

    def reload_table(self):
        items = self._rows_from_mapping()
        self.table.setRowCount(len(items))
        for row, it in enumerate(items):
            extra = it.get("extra_checks") or []
            extra_txt = json.dumps(extra, ensure_ascii=False) if extra else ""
            vals = [
                str(it.get("code", "")),
                str(it.get("domain", "")),
                str(it.get("name", "")),
                "" if it.get("level") is None else str(it.get("level")),
                "" if it.get("sys_fail_sta_expected") is None else str(it.get("sys_fail_sta_expected")),
                "" if it.get("err_tab_expected") is None else str(it.get("err_tab_expected")),
                "" if it.get("inner_signal") is None else str(it.get("inner_signal")),
                "" if it.get("inner_expected") is None else str(it.get("inner_expected")),
                "" if it.get("outer_signal") is None else str(it.get("outer_signal")),
                "" if it.get("outer_expected") is None else str(it.get("outer_expected")),
                "" if it.get("outer_warning_expected") is None else str(it.get("outer_warning_expected")),
                extra_txt,
                "是" if it.get("enabled", True) else "否",
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setFont(QFont("Microsoft YaHei", TABLE_FONT_PT))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if col in (0, 1, 2, 12):
                    # 故障码/域/名称/启用 允许改；0/1 标识用，改名/启用即可
                    pass
                self.table.setItem(row, col, item)
        self._autofit_columns()
        QTimer.singleShot(0, self._autofit_columns)

    def _autofit_columns(self):
        h_fm = QFontMetrics(self.table.horizontalHeader().font())
        c_fm = QFontMetrics(self.table.font())

        def tw(fm, t):
            t = "" if t is None else str(t)
            try:
                w = fm.horizontalAdvance(t) if hasattr(fm, "horizontalAdvance") else fm.width(t)
            except Exception:
                w = len(t) * 12
            return int(w) + CELL_PAD_X

        for col in range(len(COLS)):
            w = tw(h_fm, COLS[col])
            for row in range(self.table.rowCount()):
                it = self.table.item(row, col)
                if it:
                    # 额外回读 JSON 可能很长，限最大宽
                    ww = tw(c_fm, it.text())
                    if col == 11:
                        ww = min(ww, 480)
                    w = max(w, ww)
            self.table.setColumnWidth(col, max(w, 80))

    def _parse_int(self, text: str) -> Optional[int]:
        text = (text or "").strip()
        if text == "" or text.lower() in ("none", "null", "-"):
            return None
        try:
            return int(text, 0)
        except ValueError:
            return None

    def _parse_optional_signal(self, text: str) -> Optional[str]:
        text = (text or "").strip()
        if text == "" or text.lower() in ("none", "null", "-"):
            return None
        return text

    def _collect_items(self) -> List[Dict[str, Any]]:
        items = []
        for row in range(self.table.rowCount()):
            def t(c):
                it = self.table.item(row, c)
                return it.text().strip() if it else ""

            code = self._parse_int(t(0))
            domain = t(1) or "NBCMU"
            if code is None:
                continue
            extra_txt = t(11)
            extra = []
            if extra_txt:
                try:
                    extra = json.loads(extra_txt)
                    if not isinstance(extra, list):
                        extra = []
                except json.JSONDecodeError:
                    extra = []
            items.append({
                "code": code,
                "domain": domain,
                "name": t(2),
                "level": self._parse_int(t(3)),
                "sys_fail_sta_expected": self._parse_int(t(4)),
                "err_tab_expected": self._parse_int(t(5)),
                "inner_signal": self._parse_optional_signal(t(6)),
                "inner_expected": self._parse_int(t(7)),
                "outer_signal": self._parse_optional_signal(t(8)),
                "outer_expected": self._parse_int(t(9)),
                "outer_warning_expected": self._parse_int(t(10)),
                "extra_checks": extra,
                "enabled": t(12) not in ("否", "0", "false", "False"),
                "category": "",
            })
        return items

    def _current_row_fault(self):
        rows = {i.row() for i in self.table.selectedItems()}
        if not rows:
            return None, None
        row = sorted(rows)[0]
        code = self._parse_int(self.table.item(row, 0).text() if self.table.item(row, 0) else "")
        domain = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        return code, domain

    def _on_edit_extra(self):
        code, domain = self._current_row_fault()
        if code is None:
            QMessageBox.information(self, "提示", "请先在表格中选中一行故障")
            return
        row = self.table.currentRow()
        item = self.table.item(row, 11)
        old = item.text() if item else ""
        text, ok = QInputDialog.getMultiLineText(
            self,
            f"额外回读 故障{code} {domain}",
            'JSON 数组，每项: name / channel_role(inner|outer) / signal_name / message_name / expected / readback_key\n'
            '清空表示不使用额外回读。',
            old,
        )
        if not ok:
            return
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row, 11, item)
        item.setText(text.strip())

    def _on_export_default(self):
        if not self.fault_mapping:
            return
        if self.config.export_from_mapping(self.fault_mapping):
            QMessageBox.information(self, "已导出", f"已写入:\n{self.config.path}\n（当前内存中的内置值）")
        else:
            QMessageBox.critical(self, "失败", "导出失败")

    def _on_reload_builtin(self):
        reply = QMessageBox.question(
            self, "确认",
            "将丢弃表格中未保存的修改，按覆盖文件重载故障映射。继续？"
        )
        if reply != QMessageBox.Yes:
            return
        if self.fault_mapping:
            reload_fault_mapping_with_overrides(self.fault_mapping)
            self.reload_table()

    def _on_save_apply(self):
        items = self._collect_items()
        self.config.data["faults"] = items
        if not self.config.save():
            QMessageBox.critical(self, "失败", "保存配置文件失败")
            return
        if self.fault_mapping:
            # 重载内置再套覆盖，保证与文件一致
            reload_fault_mapping_with_overrides(self.fault_mapping)
        QMessageBox.information(
            self, "已保存",
            f"配置已写入:\n{self.config.path}\n\n已应用到故障映射，下次开始测试即生效。"
        )
