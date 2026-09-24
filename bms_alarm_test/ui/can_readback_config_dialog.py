"""
CAN 回读协议配置对话框
可编辑验证用信号：CAN ID、帧类型、起始位、长度、系数、偏移；支持从 DBC 导入。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PyQt5.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bms_alarm_test.config.can_readback_config import CanReadbackConfig, get_readback_config

COLS = [
    "配置键",
    "信号名",
    "报文名",
    "CAN ID",
    "扩展帧",
    "字节序",
    "起始位",
    "长度",
    "系数",
    "偏移",
    "通道角色",
    "来源",
    "注释",
]

# 界面字体（与故障期望值页保持一致）
UI_FONT_PT = 13
TABLE_FONT_PT = 12
BTN_HEIGHT = 36
CELL_PAD_X = 18  # 左右 padding + 余量


class LeftAlignTableDelegate(QStyledItemDelegate):
    """强制单元格文字左对齐；sizeHint 按文字实际宽度，便于列宽自适应"""

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
        text_rect = option.rect.adjusted(6, 0, -4, 0)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
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


class CanReadbackConfigDialog(QWidget):
    """CAN 回读协议配置面板（可嵌入选项卡，也可独立作为对话框内容）"""

    def __init__(self, parent: Optional[QWidget] = None,
                 config: Optional[CanReadbackConfig] = None,
                 embedded: bool = False):
        super().__init__(parent)
        self.embedded = embedded
        self.config = config or get_readback_config()
        self._init_ui()
        self.reload_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self.setFont(QFont("Microsoft YaHei", UI_FONT_PT))

        tip = QLabel(
            "说明：验证器优先按本表的 CAN ID + 位定义回读；信号名与 DBC 一致时也可走 DBC 解码。\n"
            "新增/改协议时改这里即可，不必改软件代码。{idx} 可用于簇序号占位。"
        )
        tip.setWordWrap(True)
        tip.setFont(QFont("Microsoft YaHei", UI_FONT_PT))
        layout.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_add = QPushButton("添加信号")
        self.btn_del = QPushButton("删除选中")
        self.btn_import = QPushButton("从 DBC 导入…")
        self.btn_inject = QPushButton("注入报文设置…")
        self.btn_roles = QPushButton("角色绑定…")
        self.btn_reset = QPushButton("恢复默认")
        self.btn_save = QPushButton("保存")
        self.btn_close = QPushButton("关闭")
        for b in (
            self.btn_add,
            self.btn_del,
            self.btn_import,
            self.btn_inject,
            self.btn_roles,
            self.btn_reset,
            self.btn_save,
            self.btn_close,
        ):
            b.setFont(QFont("Microsoft YaHei", UI_FONT_PT))
            b.setMinimumHeight(BTN_HEIGHT)
            btn_row.addWidget(b)
        # 嵌入选项卡时隐藏本面板的「关闭」，由外层窗口关闭
        self.btn_close.setVisible(not self.embedded)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        # 不要用 stretchLastSection：小窗口时最后一列会被裁切，横向滚不到底
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont("Microsoft YaHei", TABLE_FONT_PT))
        header_font = QFont("Microsoft YaHei", TABLE_FONT_PT, QFont.Bold)
        self.table.horizontalHeader().setFont(header_font)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        # 单行完整显示：关闭换行，列宽按最长文字自适应
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                font-size: {TABLE_FONT_PT}pt;
                gridline-color: #ccc;
            }}
            QTableWidget::item {{
                padding: 4px 6px;
                font-size: {TABLE_FONT_PT}pt;
            }}
            QHeaderView::section {{
                font-size: {TABLE_FONT_PT}pt;
                padding: 6px 4px;
            }}
            """
        )
        # 与监控页相同：用委托强制左对齐，避免样式/系统默认居中
        self._left_delegate = LeftAlignTableDelegate(self.table)
        for col in range(len(COLS)):
            self.table.setItemDelegateForColumn(col, self._left_delegate)
        # Shift+滚轮 = 横向滚动
        self.table.viewport().installEventFilter(self)
        self._apply_default_column_widths()
        layout.addWidget(self.table, 1)

        self.btn_add.clicked.connect(self._on_add)
        self.btn_del.clicked.connect(self._on_del)
        self.btn_import.clicked.connect(self._on_import_dbc)
        self.btn_inject.clicked.connect(self._on_inject)
        self.btn_roles.clicked.connect(self._on_roles)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_save.clicked.connect(self._on_save)
        # 独立使用时才接关闭；嵌入时由外层窗口负责
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
        """Shift+滚轮：横向滚动表格（列很宽时左右看）"""
        if obj is self.table.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ShiftModifier:
                bar = self.table.horizontalScrollBar()
                delta = event.angleDelta().y()
                if delta == 0:
                    delta = event.angleDelta().x()
                bar.setValue(bar.value() - delta)
                return True
        return super().eventFilter(obj, event)

    def _apply_default_column_widths(self):
        """每列按表头+单元格最长文字自适应（用字体量宽，不依赖 resizeColumnToContents）"""
        header_font = self.table.horizontalHeader().font()
        item_font = self.table.font()
        h_fm = QFontMetrics(header_font)
        c_fm = QFontMetrics(item_font)
        pad = CELL_PAD_X

        def text_w(fm, text: str) -> int:
            text = "" if text is None else str(text)
            try:
                w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
            except Exception:
                w = len(text) * 14
            return int(w) + pad

        for col in range(len(COLS)):
            width = text_w(h_fm, COLS[col] if col < len(COLS) else "")
            for row in range(self.table.rowCount()):
                item = self.table.item(row, col)
                if item is not None:
                    width = max(width, text_w(c_fm, item.text()))
            # 最小宽度，避免空列过窄
            width = max(width, 80)
            self.table.setColumnWidth(col, width)

        # 先测一次系统内容宽，取更大者
        for col in range(len(COLS)):
            self.table.resizeColumnToContents(col)
        # 上面 resize 后再按我们算的值取 max 已在一次循环完成——再补一轮 max
        # 实际 setColumn 已写入自算值，若系统更宽则覆盖回来
        header_font = self.table.horizontalHeader().font()
        item_font = self.table.font()
        h_fm = QFontMetrics(header_font)
        c_fm = QFontMetrics(item_font)
        for col in range(len(COLS)):
            sys_w = self.table.columnWidth(col)
            calc = text_w(h_fm, COLS[col] if col < len(COLS) else "")
            for row in range(self.table.rowCount()):
                item = self.table.item(row, col)
                if item is not None:
                    calc = max(calc, text_w(c_fm, item.text()))
            self.table.setColumnWidth(col, max(sys_w, calc, 80))

    def reload_table(self):
        signals = self.config.signals
        self.table.setRowCount(len(signals))
        for row, (key, spec) in enumerate(sorted(signals.items())):
            self._set_row(row, key, spec)
        self._apply_default_column_widths()
        # 显示后再量一次（字体/样式生效后更准）
        QTimer.singleShot(0, self._apply_default_column_widths)

    def _set_row(self, row: int, key: str, spec: Dict):
        vals = [
            key,
            str(spec.get("signal_name", "")),
            str(spec.get("message_name", "")),
            str(spec.get("can_id", "")),
            "是" if spec.get("is_extended", True) else "否",
            str(spec.get("byte_order", "big_endian")),
            str(spec.get("start_bit", 0)),
            str(spec.get("length", 8)),
            str(spec.get("factor", 1.0)),
            str(spec.get("offset", 0.0)),
            str(spec.get("channel_role", "inner")),
            str(spec.get("source", "manual")),
            str(spec.get("comment", "")),
        ]
        for col, text in enumerate(vals):
            item = QTableWidgetItem(text)
            item.setFont(QFont("Microsoft YaHei", TABLE_FONT_PT))
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if col == 0:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)

    def _collect(self) -> Dict[str, Dict]:
        signals: Dict[str, Dict] = {}
        for row in range(self.table.rowCount()):
            def text(c):
                it = self.table.item(row, c)
                return it.text().strip() if it else ""

            key = text(0) or f"row{row}"
            ext = text(4) in ("是", "1", "true", "True", "Y", "y")
            try:
                start = int(text(6) or 0)
            except ValueError:
                start = 0
            try:
                length = int(text(7) or 8)
            except ValueError:
                length = 8
            try:
                factor = float(text(8) or 1)
            except ValueError:
                factor = 1.0
            try:
                offset = float(text(9) or 0)
            except ValueError:
                offset = 0.0
            order = text(5) or "big_endian"
            if order not in ("big_endian", "little_endian"):
                order = "big_endian"
            role = text(10) or "inner"
            if role not in ("inner", "outer"):
                role = "inner"
            signals[key] = {
                "signal_name": text(1),
                "message_name": text(2),
                "can_id": text(3) or "0x0",
                "is_extended": ext,
                "byte_order": order,
                "start_bit": start,
                "length": length,
                "factor": factor,
                "offset": offset,
                "channel_role": role,
                "source": text(11) or "manual",
                "comment": text(12),
            }
        return signals

    def _on_add(self):
        key, ok = QInputDialog.getText(self, "添加信号", "配置键（显示名）:")
        if not ok or not key.strip():
            return
        key = key.strip()
        self.config.data["signals"][key] = {
            "signal_name": key,
            "message_name": "",
            "can_id": "0x00000000",
            "is_extended": True,
            "byte_order": "big_endian",
            "start_bit": 7,
            "length": 8,
            "factor": 1.0,
            "offset": 0.0,
            "channel_role": "inner",
            "source": "manual",
            "comment": "",
        }
        self.reload_table()

    def _on_del(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not rows:
            return
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                self.config.data["signals"].pop(item.text(), None)
        self.reload_table()

    def _on_import_dbc(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 DBC", "", "DBC (*.dbc);;所有 (*.*)")
        if not path:
            return
        role = "inner"
        items = ["对内 inner", "对外 outer"]
        choice, ok = QInputDialog.getItem(self, "通道角色", "导入信号归入:", items, 0, False)
        if not ok:
            return
        role = "outer" if "outer" in choice else "inner"
        try:
            count = self.config.import_from_dbc(path, selected=None, channel_role=role)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        # 保存表格当前手改内容前先合并
        self.config.data["signals"].update(self._collect())
        # 再导入的结果已在 config.signals 中；重新读表
        self.reload_table()
        QMessageBox.information(self, "导入完成", f"已从 DBC 导入/更新 {count} 个信号定义。\n请检查 CAN ID 与位定义后点「保存」。")

    def _on_inject(self):
        inj = self.config.data.get("inject", {})
        fields = [
            ("报文名", str(inj.get("message_name", "DAPP_FaultSet"))),
            ("CAN ID", str(inj.get("can_id", "0x18D1FFDF"))),
            ("扩展帧(是/否)", "是" if inj.get("is_extended", True) else "否"),
            ("地址字节", str(inj.get("addr_byte", 0))),
            ("故障码字节", str(inj.get("code_byte", 1))),
            ("标志字节", str(inj.get("flag_byte", 7))),
            ("注入标志值", str(inj.get("inject_flag", 3))),
            ("清除标志值", str(inj.get("clear_flag", 2))),
        ]
        text_lines = "\n".join(f"{n}={v}" for n, v in fields)
        new_text, ok = QInputDialog.getMultiLineText(
            self, "注入报文设置", "每行 key=value，改完点 OK", text_lines
        )
        if not ok:
            return
        out = dict(inj)
        for line in new_text.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "报文名":
                out["message_name"] = v
            elif k == "CAN ID":
                out["can_id"] = v
            elif k == "扩展帧(是/否)":
                out["is_extended"] = v in ("是", "1", "true", "True", "Y", "y")
            elif k == "地址字节":
                out["addr_byte"] = int(v)
            elif k == "故障码字节":
                out["code_byte"] = int(v)
            elif k == "标志字节":
                out["flag_byte"] = int(v)
            elif k == "注入标志值":
                out["inject_flag"] = int(v)
            elif k == "清除标志值":
                out["clear_flag"] = int(v)
        self.config.data["inject"] = out

    def _on_roles(self):
        roles = self.config.data.get("roles", {})
        keys = [""] + list(self.config.signals.keys())
        pairs = []
        for role, key in roles.items():
            pairs.append(f"{role}={key}")
        text, ok = QInputDialog.getMultiLineText(
            self,
            "角色绑定",
            "每行 角色=配置键\n"
            "常用角色: inner_sys_fail_sta / inner_err_tab / outer_sys_fail_sta / outer_warning\n"
            f"可选配置键: {', '.join(keys[1:])}",
            "\n".join(pairs),
        )
        if not ok:
            return
        new_roles = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            r, k = line.split("=", 1)
            new_roles[r.strip()] = k.strip()
        self.config.data["roles"] = new_roles

    def _on_reset(self):
        reply = QMessageBox.question(self, "确认", "恢复为内置默认回读协议？当前修改将丢失。")
        if reply != QMessageBox.Yes:
            return
        self.config.reset_default()
        self.reload_table()

    def _on_save(self):
        self.config.data["signals"] = self._collect()
        if self.config.save():
            QMessageBox.information(self, "已保存", f"配置已写入:\n{self.config.path}")
        else:
            QMessageBox.critical(self, "失败", "保存配置失败，请查看日志")

    def get_config(self) -> CanReadbackConfig:
        # 关闭前尽量把表格写回
        try:
            self.config.data["signals"] = self._collect()
        except Exception:
            pass
        return self.config
