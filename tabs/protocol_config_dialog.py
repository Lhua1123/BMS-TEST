"""
协议配置编辑弹窗
支持查看/编辑信号参数，导入Excel，保存用户配置
"""

import json
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QWidget,
    QAbstractItemView, QLineEdit, QStyledItemDelegate
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


class _CellDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setStyleSheet("QLineEdit { padding: 4px 4px; margin: 0px; border: none; }")
        return editor


def _infer_datatype(bit_length, bit_start, description):
    if bit_length <= 8 and bit_start is not None and bit_start > 0:
        return "bitfield"
    if bit_length <= 8:
        if description and ('0:' in description or '0：' in description):
            return "bitfield"
        return "uint8"
    if bit_length == 16:
        if description and ('负值' in description or '正值为充电' in description):
            return "int16"
        return "uint16"
    if bit_length < 16:
        return "bitfield"
    return "uint16"


class ProtocolConfigDialog(QDialog):
    """协议配置编辑弹窗"""

    def __init__(self, parent=None, mode='L2', register_groups=None, user_config_path=None):
        super().__init__(parent)
        self.mode = mode
        self.parent_tab = parent
        self.user_config_path = user_config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'protocol_user_config.json'
        )
        self.default_config = {}
        self.user_overrides = {}
        self._updating = False

        self.setWindowTitle(f"{mode} 协议配置")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMaximizeButtonHint
        )
        screen = self.screen().availableGeometry()
        self.resize(int(screen.width() * 0.65), int(screen.height() * 0.65))

        self._build_default_config(register_groups)
        self._load_user_overrides()
        self._init_ui()

    def _build_default_config(self, register_groups):
        for group in register_groups.values():
            for reg in group:
                addr, name, dtype, bit_start, bit_len, factor, offset, unit, desc, enum, en_name = reg
                self.default_config[name] = {
                    'addr': addr,
                    'factor': factor,
                    'offset': offset,
                    'unit': unit,
                    'bit_length': bit_len,
                    'bit_start': bit_start,
                    'description': desc,
                    'datatype': _infer_datatype(bit_len, bit_start, desc)
                }

    def _load_user_overrides(self):
        if not os.path.exists(self.user_config_path):
            return
        try:
            with open(self.user_config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.user_overrides = data.get(self.mode, {}).get('signals', {})
        except Exception:
            self.user_overrides = {}

    def _get_effective_value(self, signal_name, field):
        if signal_name in self.user_overrides and field in self.user_overrides[signal_name]:
            return self.user_overrides[signal_name][field]
        return self.default_config.get(signal_name, {}).get(field, '')

    def _is_modified(self, signal_name, field):
        if signal_name not in self.default_config:
            return False
        if field == 'bit_end':
            return False
        default_val = self.default_config[signal_name].get(field)
        user_val = self.user_overrides.get(signal_name, {}).get(field)
        if user_val is None:
            return False
        return str(user_val) != str(default_val)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        import_btn = QPushButton("导入Excel")
        import_btn.clicked.connect(self._import_excel)
        toolbar.addWidget(import_btn)

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_defaults)
        toolbar.addWidget(reset_btn)

        toolbar.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        toolbar.addWidget(cancel_btn)

        layout.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "信号名", "地址", "起始位", "结束位", "长度", "精度", "偏移", "单位", "类型"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.setItemDelegate(_CellDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self._on_item_changed)

        self._editing_row = -1
        self._editing_col = -1

        signals = sorted(self.default_config.keys(), key=lambda n: self.default_config[n]['addr'])
        self.table.setRowCount(len(signals))
        self._original_row_data = []

        self.table.blockSignals(True)
        for row_idx, sig_name in enumerate(signals):
            cfg = self.default_config[sig_name]
            self._original_row_data.append(sig_name)

            bit_start = cfg.get('bit_start', 0)
            bit_end = bit_start + cfg['bit_length'] - 1

            fields = [
                ('signal_name', sig_name.strip(), True),
                ('addr', cfg['addr'], False),
                ('bit_start', bit_start, False),
                ('bit_end', bit_end, False),
                ('bit_length', cfg['bit_length'], False),
                ('factor', cfg['factor'], False),
                ('offset', cfg['offset'], False),
                ('unit', cfg['unit'], False),
                ('datatype', cfg['datatype'], True),
            ]

            for col_idx, (field, default_val, read_only) in enumerate(fields):
                if field == 'bit_end':
                    eff_start = self._get_effective_value(sig_name, 'bit_start')
                    eff_length = self._get_effective_value(sig_name, 'bit_length')
                    eff_val = int(eff_start) + int(eff_length) - 1
                elif field == 'signal_name':
                    eff_val = sig_name
                else:
                    eff_val = self._get_effective_value(sig_name, field)
                item = QTableWidgetItem(str(eff_val).strip())
                if read_only:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(QColor('#64748b'))
                else:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)

                item.setTextAlignment(Qt.AlignCenter)

                if field != 'signal_name' and field != 'datatype':
                    if self._is_modified(sig_name, field):
                        item.setBackground(QColor('#dbeafe'))

                self.table.setItem(row_idx, col_idx, item)
        self.table.blockSignals(False)

        layout.addWidget(self.table)

    def keyPressEvent(self, event):
        if self.table.state() != QTableWidget.EditingState:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
                self._start_edit_selected()
                return
            if event.text() and not event.modifiers():
                self._start_edit_selected()
                return
        super().keyPressEvent(event)

    def _on_item_changed(self, item):
        if item is None or self._updating:
            return
        row = item.row()
        col = item.column()
        try:
            if col == 2:
                item_bs = self.table.item(row, 2)
                item_bl = self.table.item(row, 4)
                item_be = self.table.item(row, 3)
                if item_bs and item_bl and item_be:
                    bit_start = int(item_bs.text())
                    bit_end = bit_start + int(item_bl.text()) - 1
                    self.table.blockSignals(True)
                    self._updating = True
                    item_be.setText(str(bit_end))
                    self._updating = False
                    self.table.blockSignals(False)
            elif col == 3:
                item_be = self.table.item(row, 3)
                item_bs = self.table.item(row, 2)
                item_bl = self.table.item(row, 4)
                if item_be and item_bs and item_bl:
                    bit_end = int(item_be.text())
                    bit_start = int(item_bs.text())
                    bit_length = bit_end - bit_start + 1
                    self.table.blockSignals(True)
                    self._updating = True
                    item_bl.setText(str(bit_length))
                    self._updating = False
                    self.table.blockSignals(False)
            elif col == 4:
                item_bl = self.table.item(row, 4)
                item_bs = self.table.item(row, 2)
                item_be = self.table.item(row, 3)
                if item_bl and item_bs and item_be:
                    bit_length = int(item_bl.text())
                    bit_start = int(item_bs.text())
                    bit_end = bit_start + bit_length - 1
                    self.table.blockSignals(True)
                    self._updating = True
                    item_be.setText(str(bit_end))
                    self._updating = False
                    self.table.blockSignals(False)
        except (ValueError, TypeError):
            pass

    def _start_edit_selected(self):
        row = self.table.currentRow()
        col = self.table.currentColumn()
        if row < 0 or col < 0:
            return
        item = self.table.item(row, col)
        if item is None or (item.flags() & Qt.ItemIsEditable) == 0:
            return
        self.table.editItem(item)

    def _collect_table_data(self):
        data = {}
        for row in range(self.table.rowCount()):
            sig_name_item = self.table.item(row, 0)
            sig_name = sig_name_item.text().strip()
            if not sig_name:
                continue

            addr = int(self.table.item(row, 1).text())
            bit_start = int(self.table.item(row, 2).text())
            bit_end = int(self.table.item(row, 3).text())
            bit_length = bit_end - bit_start + 1
            factor = float(self.table.item(row, 5).text())
            offset = float(self.table.item(row, 6).text())
            unit = self.table.item(row, 7).text().strip()
            description = self.default_config.get(self._original_row_data[row], {}).get('description', '')
            datatype = _infer_datatype(bit_length, bit_start, description)

            data[sig_name] = {
                'addr': addr,
                'bit_start': bit_start,
                'bit_end': bit_end,
                'bit_length': bit_length,
                'factor': factor,
                'offset': offset,
                'unit': unit,
                'datatype': datatype
            }
        return data

    def _save(self):
        data = self._collect_table_data()

        config = {}
        if os.path.exists(self.user_config_path):
            try:
                with open(self.user_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception:
                config = {}

        if self.mode not in config:
            config[self.mode] = {'signals': {}}

        defaults = {}
        for sig_name, fields in data.items():
            defaults_sig = self.default_config.get(sig_name, {})
            overrides = {}
            for field, val in fields.items():
                if field == 'bit_end':
                    continue
                default_val = defaults_sig.get(field)
                if str(val) != str(default_val):
                    overrides[field] = val
            if overrides:
                defaults[sig_name] = overrides

        config[self.mode]['signals'] = defaults

        try:
            with open(self.user_config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return

        if self.parent_tab and hasattr(self.parent_tab, '_reload_and_refresh'):
            self.parent_tab._reload_and_refresh()

        self.accept()

    def _reset_defaults(self):
        reply = QMessageBox.question(
            self, "确认",
            f"确定要恢复 {self.mode} 的默认配置吗？\n所有手动修改将被清除。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        config = {}
        if os.path.exists(self.user_config_path):
            try:
                with open(self.user_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception:
                config = {}

        if self.mode in config:
            config[self.mode]['signals'] = {}

        try:
            with open(self.user_config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return

        if self.parent_tab and hasattr(self.parent_tab, '_reload_and_refresh'):
            self.parent_tab._reload_and_refresh()

        self.accept()

    def _import_excel(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入Excel协议文件",
            "", "Excel文件 (*.xlsx *.xls)"
        )
        if not file_path:
            return

        try:
            from shared.excel_parser import parse_excel
        except ImportError:
            QMessageBox.critical(self, "错误", "无法导入 excel_parser 模块")
            return

        result = parse_excel(file_path)
        if result is None:
            QMessageBox.critical(self, "导入失败", "Excel 文件解析失败，请检查格式")
            return

        if self.parent_tab and hasattr(self.parent_tab, '_apply_excel_import'):
            self.parent_tab._apply_excel_import(result)
            self.accept()
        else:
            QMessageBox.critical(self, "错误", "父窗口不支持 Excel 导入")
