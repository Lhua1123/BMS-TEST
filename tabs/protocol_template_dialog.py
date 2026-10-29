"""协议核对：编辑接收模板弹窗

主界面只留一个入口，报文/信号的增删改全部收在这里。
编辑的是模板的深拷贝，点「应用」才交回主界面，「取消」放弃修改。
"""

import copy
import logging
import os
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bms_alarm_test.ui.panel_style import btn_neutral, btn_primary, btn_success
from protocol_check.dbc_import import parse_dbc_file
from protocol_check.excel_template import load_template_excel, save_template_excel
from protocol_check.models import CanFrame, MessageTemplate, SignalTemplate, TemplateBook
from shared.style import themed_qss
from tabs.protocol_check_ui import (
    FONT_BODY,
    FONT_MONO,
    FONT_MONO_BOLD,
    btn,
    common_qss,
    hex_col_width,
    layout_msg_table,
    layout_sig_table,
    make_item,
    section_title,
    style_table,
)

logger = logging.getLogger(__name__)

MSG_COL = ["总线ID", "DBC原ID", "名称", "期望DLC", "必须出现", "信号数", "备注"]
SIG_COL = ["信号名", "起始位", "长度", "字节序", "类型", "因子", "偏移", "单位", "备注"]


class ProtocolTemplateDialog(QDialog):
    """接收模板编辑器：导入 DBC/Excel、改报文与信号、保存、应用到核对"""

    def __init__(
        self,
        book: TemplateBook,
        book_path: str = "",
        offline_frames: Optional[List[CanFrame]] = None,
        ref_dir: str = "",
        sample_path: str = "",
        parent=None,
    ):
        super().__init__(parent)
        themed_qss(self, common_qss)
        self.setFont(FONT_BODY)
        self.setWindowTitle("编辑核对模板")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)
        self.resize(1280, 760)

        # 编辑深拷贝：取消时主界面的模板不受影响
        self._book: TemplateBook = copy.deepcopy(book) if book else TemplateBook()
        self._book_path: str = book_path or ""
        self._log_frames: List[CanFrame] = list(offline_frames or [])
        self._ref_dir = ref_dir
        self._sample_path = sample_path
        self._selected_msg_id: Optional[int] = None

        self._init_ui()
        self._fill_message_table()

    # ───────── 对外交接 ─────────
    @property
    def book(self) -> TemplateBook:
        return self._book

    @property
    def book_path(self) -> str:
        return self._book_path

    def accept(self):
        self._commit_tables_into_book()
        super().accept()

    # ───────── UI ─────────
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        hint = QLabel("改完点右下「应用」才生效；「取消」放弃本次修改。导入 DBC/Excel 会替换当前模板。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addLayout(self._build_file_row())

        v_split = QSplitter(Qt.Vertical)
        v_split.setHandleWidth(4)
        v_split.setChildrenCollapsible(False)
        v_split.addWidget(self._build_msg_panel())
        v_split.addWidget(self._build_sig_panel())
        v_split.setStretchFactor(0, 3)
        v_split.setStretchFactor(1, 2)
        v_split.setSizes([380, 280])
        root.addWidget(v_split, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addStretch(1)
        b_cancel = btn("取消", btn_neutral)
        b_cancel.setToolTip("放弃本次修改，关闭窗口")
        b_cancel.clicked.connect(self.reject)
        b_apply = btn("应用", btn_primary)
        b_apply.setToolTip("把编辑结果写回主界面，用于后续核对")
        b_apply.clicked.connect(self.accept)
        bottom.addWidget(b_cancel)
        bottom.addWidget(b_apply)
        root.addLayout(bottom)

    def _build_file_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        b_dbc = btn("导入 DBC", btn_neutral)
        b_dbc.clicked.connect(self._on_import_dbc)
        b_xlsx = btn("导入 Excel", btn_neutral)
        b_xlsx.clicked.connect(self._on_import_template_excel)
        b_save = btn("保存 Excel", btn_success)
        b_save.setToolTip("把当前模板另存为 .xlsx，下次可直接导入")
        b_save.clicked.connect(self._on_save_excel)
        row.addWidget(b_dbc)
        row.addWidget(b_xlsx)
        row.addWidget(b_save)

        self.chk_map_id = QCheckBox("DBC ID → 总线ID（&0x1FFFFFFF）")
        self.chk_map_id.setChecked(True)
        self.chk_map_id.setToolTip(
            "DBC 文档 ID 常见 0x98xxxxxx，总线实报多为 0x18xxxxxx；默认自动映射，表中可改"
        )
        row.addWidget(self.chk_map_id)

        self.lbl_book_path = QLabel("当前模板：-")
        self.lbl_book_path.setObjectName("hint")
        self.lbl_book_path.setWordWrap(True)
        row.addWidget(self.lbl_book_path, 1)
        return row

    def _build_msg_panel(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(section_title("报文表（可编辑）"))
        head.addStretch(1)
        btn_add_msg = btn("添加报文", btn_neutral)
        btn_add_msg.clicked.connect(self._on_add_message)
        btn_del_msg = btn("删除报文", btn_neutral)
        btn_del_msg.clicked.connect(self._on_del_message)
        self.btn_from_log = btn("按实报补齐ID", btn_neutral)
        self.btn_from_log.setToolTip("把离线日志里出现、但模板没有的 ID 加进来（默认必须出现=否）")
        self.btn_from_log.clicked.connect(self._on_add_ids_from_log)
        self.btn_from_log.setEnabled(bool(self._log_frames))
        head.addWidget(btn_add_msg)
        head.addWidget(btn_del_msg)
        head.addWidget(self.btn_from_log)
        lay.addLayout(head)

        self.tbl_template = QTableWidget(0, len(MSG_COL))
        self.tbl_template.setHorizontalHeaderLabels(MSG_COL)
        style_table(self.tbl_template, min_h=160)
        self.tbl_template.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.tbl_template.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_template.itemSelectionChanged.connect(self._on_msg_row_selected)
        self.tbl_template.itemChanged.connect(self._on_msg_item_changed)
        layout_msg_table(self.tbl_template)
        lay.addWidget(self.tbl_template, 1)
        return wrap

    def _build_sig_panel(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(section_title("选中报文的信号"))
        head.addStretch(1)
        btn_sig_add = btn("添加信号", btn_success)
        btn_sig_add.clicked.connect(self._on_add_signal)
        btn_del_sig = btn("删除信号", btn_neutral)
        btn_del_sig.clicked.connect(self._on_del_signal)
        head.addWidget(btn_sig_add)
        head.addWidget(btn_del_sig)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

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

        grid.addWidget(QLabel("信号名"), 0, 0)
        grid.addWidget(self.edt_sig_name, 0, 1)
        grid.addWidget(QLabel("起始位"), 0, 2)
        grid.addWidget(self.spn_sig_start, 0, 3)
        grid.addWidget(QLabel("长度"), 0, 4)
        grid.addWidget(self.spn_sig_len, 0, 5)
        grid.addWidget(QLabel("字节序"), 0, 6)
        grid.addWidget(self.cmb_sig_order, 0, 7)
        grid.addWidget(QLabel("类型"), 1, 0)
        grid.addWidget(self.cmb_sig_type, 1, 1)
        grid.addWidget(QLabel("因子"), 1, 2)
        grid.addWidget(self.spn_sig_factor, 1, 3)
        grid.addWidget(QLabel("偏移"), 1, 4)
        grid.addWidget(self.spn_sig_offset, 1, 5)
        grid.addWidget(QLabel("单位"), 1, 6)
        grid.addWidget(self.edt_sig_unit, 1, 7)
        grid.addWidget(QLabel("备注"), 2, 0)
        grid.addWidget(self.edt_sig_note, 2, 1, 1, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)
        grid.setColumnStretch(7, 1)
        lay.addLayout(grid)

        self.tbl_signals = QTableWidget(0, len(SIG_COL))
        self.tbl_signals.setHorizontalHeaderLabels(SIG_COL)
        style_table(self.tbl_signals, min_h=100)
        self.tbl_signals.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.tbl_signals.itemChanged.connect(self._on_sig_item_changed)
        layout_sig_table(self.tbl_signals)
        lay.addWidget(self.tbl_signals, 1)

        self.lbl_sig_status = QLabel("未选中报文")
        self.lbl_sig_status.setObjectName("status")
        lay.addWidget(self.lbl_sig_status)
        return wrap

    # ───────── 模板读写 ─────────
    def _short_path(self, path: str, keep: int = 42) -> str:
        if not path:
            return "-"
        if len(path) <= keep:
            return path
        return "…" + path[-keep:]

    def _refresh_path_label(self):
        path_txt = self._book_path or "-"
        self.lbl_book_path.setText(f"当前模板：{self._short_path(path_txt, 50)}")
        self.lbl_book_path.setToolTip(path_txt)

    def _fill_message_table(self):
        self._refresh_path_label()
        self.tbl_template.blockSignals(True)
        self.tbl_template.setRowCount(0)
        book = self._book
        if book:
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
                    make_item(f"{m.msg_id:X}", Qt.AlignCenter, mono=True, bold=True),
                    make_item(dbc_orig, Qt.AlignCenter, mono=True),
                    make_item(m.name, Qt.AlignLeft | Qt.AlignVCenter),
                    make_item(str(m.expected_dlc), Qt.AlignCenter, mono=True),
                    make_item("是" if m.required else "否", Qt.AlignCenter),
                    make_item(str(len(m.signals)), Qt.AlignCenter, mono=True),
                    make_item(note, Qt.AlignLeft | Qt.AlignVCenter),
                ]
                for c, item in enumerate(items):
                    self.tbl_template.setItem(r, c, item)
        # 按实际文字度量 ID 列宽，避免 Consolas 下被省略号截断
        bus_ids = [
            self.tbl_template.item(r, 0).text()
            for r in range(self.tbl_template.rowCount()) if self.tbl_template.item(r, 0)
        ]
        dbc_ids = [
            self.tbl_template.item(r, 1).text()
            for r in range(self.tbl_template.rowCount()) if self.tbl_template.item(r, 1)
        ]
        self.tbl_template.setColumnWidth(0, hex_col_width(bus_ids, FONT_MONO_BOLD, 104))
        self.tbl_template.setColumnWidth(1, hex_col_width(dbc_ids, FONT_MONO, 92))
        self.tbl_template.blockSignals(False)

    def _commit_tables_into_book(self):
        """把可编辑表格的文本写回模板（报文表的 ID/DLC/必须出现/备注只存在于表格里）"""
        if not self._book:
            self._book = TemplateBook()
        old = self._book.messages
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
        self._book.messages = new_map
        self._fill_signal_table()

    def _fill_signal_table(self):
        self.tbl_signals.blockSignals(True)
        self.tbl_signals.setRowCount(0)
        msg = None
        if self._book and self._selected_msg_id is not None:
            msg = self._book.messages.get(self._selected_msg_id)
        if not msg:
            self.lbl_sig_status.setText("未选中报文 — 请在上方报文表中选择一行")
            self.tbl_signals.blockSignals(False)
            return
        sigs = msg.signals
        self.tbl_signals.setRowCount(len(sigs))
        for r, s in enumerate(sigs):
            items = [
                make_item(s.name, Qt.AlignLeft | Qt.AlignVCenter),
                make_item(str(s.start_bit), Qt.AlignCenter, mono=True),
                make_item(str(s.length), Qt.AlignCenter, mono=True),
                make_item(s.byte_order, Qt.AlignCenter),
                make_item("int" if s.signed else "uint", Qt.AlignCenter),
                make_item(str(s.factor), Qt.AlignCenter, mono=True),
                make_item(str(s.offset), Qt.AlignCenter, mono=True),
                make_item(s.unit, Qt.AlignCenter),
                make_item(s.note, Qt.AlignLeft | Qt.AlignVCenter),
            ]
            for c, item in enumerate(items):
                self.tbl_signals.setItem(r, c, item)
        self.lbl_sig_status.setText(
            f"0x{msg.msg_id:X}  {msg.name}  |  信号 {len(sigs)} 条  |  DLC={msg.expected_dlc}"
            f"  |  必须出现={'是' if msg.required else '否'}"
        )
        self.tbl_signals.blockSignals(False)

    # ───────── 编辑事件 ─────────
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

    def _on_sig_item_changed(self, item: QTableWidgetItem):
        if not self._book or self._selected_msg_id is None:
            return
        msg = self._book.messages.get(self._selected_msg_id)
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
        self._commit_tables_into_book()
        if not self._book:
            self._book = TemplateBook()
        new_id = 0x18FFFF00
        while new_id in self._book.messages:
            new_id += 1
        self._book.messages[new_id] = MessageTemplate(
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
        self._commit_tables_into_book()
        r = rows[0].row()
        item = self.tbl_template.item(r, 0)
        if not item:
            return
        try:
            msg_id = int(item.text().replace("0x", ""), 16)
        except Exception:
            return
        self._book.messages.pop(msg_id, None)
        self._selected_msg_id = None
        self._fill_message_table()
        self._fill_signal_table()

    def _on_add_signal(self):
        if not self._book or self._selected_msg_id is None:
            QMessageBox.information(self, "添加信号", "请先在报文表中选中一条报文")
            return
        self._commit_tables_into_book()
        msg = self._book.messages.get(self._selected_msg_id)
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
        if not self._book or self._selected_msg_id is None:
            return
        msg = self._book.messages.get(self._selected_msg_id)
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
        frames = self._log_frames
        if not frames:
            QMessageBox.warning(self, "补齐 ID", "请先在主界面导入离线 asc/blf 日志")
            return
        self._commit_tables_into_book()
        if not self._book:
            self._book = TemplateBook()
        added = 0
        for fr in frames:
            if fr.arbitration_id not in self._book.messages:
                self._book.messages[fr.arbitration_id] = MessageTemplate(
                    msg_id=fr.arbitration_id,
                    name=f"CAN_{fr.arbitration_id:X}",
                    expected_dlc=fr.dlc or 8,
                    required=False,
                    note="按实报补齐",
                )
                added += 1
        self._fill_message_table()
        QMessageBox.information(self, "补齐 ID", f"新增 {added} 个实报 ID（默认必须出现=否）")

    # ───────── 导入/保存 ─────────
    def _on_import_dbc(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入标准 DBC",
            self._ref_dir if os.path.isdir(self._ref_dir) else "",
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
        self._book = book
        self._book_path = f"DBC:{os.path.basename(path)}"
        self._selected_msg_id = None
        self._fill_message_table()
        self._fill_signal_table()
        note_txt = "\n".join(notes[:8])
        QMessageBox.information(
            self,
            "DBC 已导入",
            f"{os.path.basename(path)}\n\n{note_txt}\n\n"
            "已在上方生成可编辑列表：\n"
            "· 默认 ID 已映射为总线 ID（可改）\n"
            "· 「必须出现」默认=否，请按测试范围改成「是」\n"
            "· 选中报文后可在下方增删信号\n"
            "· 完成后点「应用」写回主界面",
        )

    def _on_import_template_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入接收 Excel 模板",
            self._ref_dir if os.path.isdir(self._ref_dir) else "",
            "Excel (*.xlsx *.xlsm)",
        )
        if not path:
            return
        try:
            self._book = load_template_excel(path)
            self._book_path = path
            self._selected_msg_id = None
            self._fill_message_table()
            self._fill_signal_table()
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _on_save_excel(self):
        self._commit_tables_into_book()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存接收 Excel 模板",
            self._sample_path or "接收CAN协议核对模板.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            save_template_excel(self._book, path)
            self._book_path = path
            self._book = load_template_excel(path)
            self._fill_message_table()
            self._fill_signal_table()
            QMessageBox.information(self, "已保存", f"接收模板已保存：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
