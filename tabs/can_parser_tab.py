"""
CAN报文解析Tab - 基于 Convert_ASCII_V1.1 BmsTab
支持CAN ID解析、CAN数据帧解析、DBC文件导入解码
"""

import os
from typing import List, Tuple

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QTextEdit, QComboBox, QSplitter,
    QFileDialog, QListWidget, QListWidgetItem, QCompleter
)
from PyQt5.QtCore import Qt, pyqtSignal, QStringListModel, QTimer
from PyQt5.QtGui import QFont

from convert_ascii.core.converter import ASCIIConverter
from convert_ascii.bms.bms_formatter import BMSFormatter
from shared.style import COLORS, FONTS


class CanParserTab(QWidget):
    """CAN报文解析标签页"""
    dbc_imported = pyqtSignal(list)   # 成功导入的 DBC 文件路径列表
    dbc_removed = pyqtSignal(str)     # 删除的 DBC 文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bms_formatter = BMSFormatter()
        self._id_completer = None
        self._message_id_map = {}
        self._init_ui()
        if self._id_completer:
            self._id_completer.activated.connect(self._on_id_completer_activated)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # DBC 管理区
        grp_dbc = QGroupBox("DBC 文件管理")
        gd = QVBoxLayout(grp_dbc)

        dbc_row = QHBoxLayout()
        self.btn_import_dbc = QPushButton("📥 导入 DBC")
        self.btn_import_dbc.setCursor(Qt.PointingHandCursor)
        self.btn_import_dbc.setMinimumHeight(38)
        dbc_row.addWidget(self.btn_import_dbc)

        self.lst_dbc_files = QListWidget()
        self.lst_dbc_files.setStyleSheet(f"font-size: {FONTS['body'][1]}pt; min-height: 36px;")
        self.lst_dbc_files.setMaximumHeight(80)
        dbc_row.addWidget(self.lst_dbc_files, 1)

        self.btn_remove_dbc = QPushButton("删除选中")
        self.btn_remove_dbc.setCursor(Qt.PointingHandCursor)
        self.btn_remove_dbc.setMaximumWidth(100)
        self.btn_remove_dbc.setEnabled(False)
        dbc_row.addWidget(self.btn_remove_dbc)

        gd.addLayout(dbc_row)
        layout.addWidget(grp_dbc)

        # CAN 解析（合并 ID + 数据）
        grp_parse = QGroupBox("CAN 解析 — 输入 CAN ID 和数据进行解码")
        gp = QVBoxLayout(grp_parse)

        # 第一行：CAN ID
        row_id = QHBoxLayout()
        row_id.addWidget(QLabel("CAN ID:"))
        self.txt_can_id = QLineEdit()
        self.txt_can_id.setStyleSheet(f"font-size: {FONTS['body'][1]}pt; min-height: 38px;")
        self.txt_can_id.setPlaceholderText("如: 0x18A1FFF4  或 18A1FFF4")
        self._id_completer = QCompleter([], self)
        self._id_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._id_completer.setFilterMode(Qt.MatchContains)
        self._id_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.txt_can_id.setCompleter(self._id_completer)
        row_id.addWidget(self.txt_can_id, 1)

        row_id.addWidget(QLabel("十六进制数据:"))
        self.txt_can_data = QLineEdit()
        self.txt_can_data.setStyleSheet(f"font-size: {FONTS['body'][1]}pt; min-height: 38px;")
        self.txt_can_data.setPlaceholderText("如: 00 01 02 03 04 05 06 07")
        row_id.addWidget(self.txt_can_data, 1)

        self.btn_parse = QPushButton("🔍 解析")
        self.btn_parse.setCursor(Qt.PointingHandCursor)
        self.btn_parse.setMinimumHeight(42)
        self.btn_parse.setEnabled(False)
        row_id.addWidget(self.btn_parse)

        self.btn_copy_parse = QPushButton("复制结果")
        self.btn_copy_parse.setMaximumWidth(120)
        row_id.addWidget(self.btn_copy_parse)

        gp.addLayout(row_id)

        self.txt_parse_result = QTextEdit()
        self.txt_parse_result.setReadOnly(True)
        self.txt_parse_result.setStyleSheet(f"font-family: {FONTS['mono'][0]}, Consolas; font-size: {FONTS['mono'][1]}pt; padding: 6px;")
        gp.addWidget(self.txt_parse_result, 1)

        layout.addWidget(grp_parse, 1)

        # 输入变化时更新按钮状态
        self.txt_can_id.textChanged.connect(self._update_parse_button)
        self.txt_can_data.textChanged.connect(self._update_parse_button)

        # 按钮信号
        self.btn_parse.clicked.connect(self._on_parse)
        self.btn_import_dbc.clicked.connect(self._on_import_dbc)
        self.btn_remove_dbc.clicked.connect(self._on_remove_dbc)
        self.btn_copy_parse.clicked.connect(self._on_copy_parse)

    def _update_parse_button(self):
        """只有 CAN ID 和数据都有内容时才启用解析按钮"""
        has_id = bool(self.txt_can_id.text().strip())
        has_data = bool(self.txt_can_data.text().strip())
        self.btn_parse.setEnabled(has_id and has_data)

    # ============================================================
    # 解析逻辑
    # ============================================================

    def _on_parse(self):
        can_id = self.txt_can_id.text().strip()
        can_data = self.txt_can_data.text().strip()

        if not can_id and not can_data:
            return

        try:
            # 如果只有 ID，执行 ID 解析
            if can_id and not can_data:
                # 先尝试 DBC 解码（仅查消息定义，不解码数据）
                if self.bms_formatter.db_list:
                    dbc_result = self.bms_formatter.decode_with_dbc(can_id, "00" * 8)
                    if '错误' not in dbc_result and dbc_result.get('消息名') != 'Unknown Message':
                        html = f"<h3>📌 消息名: {dbc_result.get('消息名', '')}</h3>"
                        html += f"<p>🔢 CAN ID: {dbc_result.get('CAN ID', can_id)}</p>"
                        if dbc_result.get('信号列表'):
                            html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">'
                            html += '<tr style="background-color: #f0f0f0;"><th>信号名</th><th>值</th><th>注释</th></tr>'
                            for sig in dbc_result['信号列表']:
                                unit = f" ({sig['单位']})" if sig['单位'] else ""
                                comment = sig['注释'] if sig['注释'] else ""
                                html += f"<tr><td>{sig['信号名']}</td><td>{sig['值']}{unit}</td><td>{comment}</td></tr>"
                            html += '</table>'
                        else:
                            html += "<p>（该消息无信号定义）</p>"

                        self.txt_parse_result.setHtml(html)
                        return
                    else:
                        dbc_tip = dbc_result.get('提示', 'DBC 中未找到该 ID')

                # 回退到原有解析
                result = self.bms_formatter.parse_can_id(can_id)
                if '错误' in result:
                    self.txt_parse_result.setHtml(f"<p>❌ {result['错误']}</p>")
                    return

                html = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">'
                html += '<tr style="background-color: #f0f0f0;"><th>项目</th><th>值</th></tr>'
                for key in ['原始值', '十六进制', '十进制', '二进制', '八进制',
                             'ID前缀', 'SA地址', 'PF(PDU格式)', 'PS(PDU特定)',
                             'PGN(参数组)', '优先级', 'DP']:
                    if key in result:
                        html += f"<tr><td>{key}</td><td>{result[key]}</td></tr>"
                html += '</table>'
                html += f"<p>功能: {result.get('功能说明', '')}</p>"
                html += f"<p>标识: {result.get('信息标识', '')}</p>"
                if self.bms_formatter.db_list:
                    html += f"<p>⚠️ DBC 已加载 {len(self.bms_formatter.db_list)} 个文件，但该 ID 未在 DBC 中定义</p>"
                    if 'dbc_tip' in locals():
                        html += f"<p>提示: {dbc_tip}</p>"

                self.txt_parse_result.setHtml(html)
                return

            # 有数据时执行数据解析（ID 可选）
            if can_data:
                # 优先使用 DBC 解码
                if can_id and self.bms_formatter.db_list:
                    dbc_result = self.bms_formatter.parse_can_data_with_dbc(can_id, can_data)
                    if '错误' not in dbc_result and dbc_result.get('消息名') != 'Unknown Message':
                        html = f"<h3>📌 消息名: {dbc_result.get('消息名', '')}</h3>"
                        html += f"<p>🔢 CAN ID: {dbc_result.get('CAN ID', can_id)} | 📐 字节数: {dbc_result.get('字节数', '')}</p>"
                        if dbc_result.get('信号列表'):
                            html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">'
                            html += '<tr style="background-color: #f0f0f0;"><th>信号名</th><th>值</th><th>注释</th></tr>'
                            for sig in dbc_result['信号列表']:
                                unit = f" ({sig['单位']})" if sig['单位'] else ""
                                comment = sig['注释'] if sig['注释'] else ""
                                html += f"<tr><td>{sig['信号名']}</td><td>{sig['值']}{unit}</td><td>{comment}</td></tr>"
                            html += '</table>'
                        else:
                            html += "<p>（该消息无信号定义）</p>"

                        if dbc_result.get('DBC 提示'):
                            html += f"<p>⚠️ {dbc_result['DBC 提示']}</p>"

                        self.txt_parse_result.setHtml(html)
                        return

                # 回退到原有字节解析
                result = self.bms_formatter.parse_can_data(can_data)
                if '错误' in result:
                    self.txt_parse_result.setHtml(f"<p>❌ {result['错误']}</p>")
                    return

                html = f"<h3>📦 原始数据: {result.get('格式化十六进制', result['原始数据'])}</h3>"
                html += f"<p>📐 字节数: {result['字节数']}</p>"

                rows = ""
                for b in result.get('字节详情', []):
                    rows += f"<tr><td>{b['索引']}</td><td>{b['十六进制']}</td><td>{b['十进制']}</td><td>{b['二进制']}</td><td>{b['ASCII']}</td></tr>"

                html += '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">'
                html += '<tr style="background-color: #f0f0f0;"><th>索引</th><th>十六进制</th><th>十进制</th><th>二进制</th><th>ASCII</th></tr>'
                html += rows
                html += '</table>'

                combo = []
                if 'uint16_LE' in result:
                    combo.append(f"uint16 LE: {result['uint16_LE']}  BE: {result['uint16_BE']}")
                if 'uint32_LE' in result:
                    combo.append(f"uint32 LE: {result['uint32_LE']}  BE: {result['uint32_BE']}")
                if 'float32_LE' in result:
                    combo.append(f"float32 LE: {result['float32_LE']}  BE: {result['float32_BE']}")

                if combo:
                    html += "<p><strong>🔢 组合值:</strong></p>"
                    for line in combo:
                        html += f"<p>{line}</p>"

                self.txt_parse_result.setHtml(html)

        except Exception as e:
            self.txt_parse_result.setHtml(f"<p>❌ 解析异常: {str(e)}</p>")

    def _on_copy_parse(self):
        text = self.txt_parse_result.toPlainText()
        if text:
            btn = self.sender()
            if btn:
                btn.setText("✓")
                QTimer.singleShot(800, lambda: btn.setText("复制结果") if btn else None)
            import pyperclip
            pyperclip.copy(text)

    # ============================================================
    # DBC 管理
    # ============================================================

    def _on_import_dbc(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 DBC 文件", "", "DBC 文件 (*.dbc);;所有文件 (*.*)"
        )
        if not file_paths:
            return

        try:
            success = self.bms_formatter.load_dbc_files(file_paths)
            if success:
                self.set_dbc_files(self.bms_formatter.get_loaded_dbc_files())
                self.update_can_id_completer(self.bms_formatter.get_dbc_message_list())
                self.dbc_imported.emit(success)
            else:
                pass  # 未成功导入任何文件
        except Exception as e:
            self.txt_parse_result.setHtml(f"<p>❌ 导入DBC失败: {str(e)}</p>")

    def _on_remove_dbc(self):
        dbc_path = self.get_selected_dbc_path()
        if not dbc_path:
            return

        self.bms_formatter.clear_dbc(dbc_path)
        self.set_dbc_files(self.bms_formatter.get_loaded_dbc_files())
        self.update_can_id_completer(self.bms_formatter.get_dbc_message_list())
        self.dbc_removed.emit(dbc_path)

    def set_dbc_files(self, dbc_files):
        """设置已加载的 DBC 文件列表，支持 [(文件名, 路径), ...] 或 [路径, ...]"""
        self.lst_dbc_files.clear()
        for item_data in dbc_files:
            if isinstance(item_data, tuple):
                display_name, file_path = item_data
            else:
                display_name = os.path.basename(item_data)
                file_path = item_data
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, file_path)
            self.lst_dbc_files.addItem(item)
        self.btn_remove_dbc.setEnabled(self.lst_dbc_files.count() > 0)

    def update_can_id_completer(self, message_list: List[Tuple[str, str]]):
        """更新 CAN ID 自动补全列表，显示 ID + 消息名"""
        display_list = [f"{msg_id}  {name}" for msg_id, name in message_list]
        model = QStringListModel(display_list)
        self._id_completer.setModel(model)
        self._message_id_map = {f"{msg_id}  {name}": msg_id for msg_id, name in message_list}

    def _on_id_completer_activated(self, text):
        """补全选择后，只保留 ID 部分"""
        import re
        match = re.match(r'(0x[0-9A-Fa-f]+)', str(text))
        if match:
            # 延迟一帧执行，避免与 QCompleter 自身的插入冲突
            QTimer.singleShot(0, lambda: self.txt_can_id.setText(match.group(1)))

    def get_selected_dbc_path(self) -> str:
        """获取当前选中的 DBC 文件完整路径"""
        item = self.lst_dbc_files.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return ""

