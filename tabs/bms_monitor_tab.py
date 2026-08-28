"""
BMS监控Tab - PyQt5重写
支持L2和L3两种模式
"""

import sys
import os
import json
import threading
import time
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QRadioButton, QButtonGroup, QMessageBox, QFrame,
    QTabWidget, QSizePolicy, QLayout, QStyledItemDelegate, QStyleOptionViewItem,
    QStyle
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QModelIndex
from PyQt5.QtGui import QFont, QColor

from tabs.protocol_config_dialog import ProtocolConfigDialog
from shared.style import COLORS, FONTS
from shared.modbus_comm import ModbusComm
from shared.modbus_parser import parse_read_response, parse_batch_response
from shared.constants import (
    MODBUS_HOLDING_REGISTER_BASE,
    REGISTERS_PER_ROW,
    BMS_REGISTER_START_ADDR,
    REFRESH_INTERVAL_MS
)


class SignalEmitter(QObject):
    """跨线程信号发射器"""
    data_updated = pyqtSignal()
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)


class SignalNameDelegate(QStyledItemDelegate):
    """信号名列左对齐，其余列居中"""
    def paint(self, painter, option, index):
        if index.column() == 0:
            painter.save()
            # 只画背景（含选中高亮），不画文字
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(COLORS['accent']))
                painter.setPen(QColor('#ffffff'))
            else:
                painter.setPen(QColor(COLORS['text']))
            painter.setFont(option.font)
            text_rect = option.rect.adjusted(8, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, index.data(Qt.DisplayRole) or "")
            painter.restore()
        else:
            super().paint(painter, option, index)


class BmsMonitorTab(QWidget):
    """BMS监控Tab - 支持L2/L3"""

    def __init__(self, mode='L2', parent=None):
        super().__init__(parent)
        self.mode = mode

        self._load_protocol_config(mode)
        self._original_register_groups = {
            k: list(v) for k, v in self.register_groups.items()
        } if self.register_groups else {}

        self.comm = ModbusComm()
        self.parsed_data = {}
        self.register_values = {}
        self.signal_info = {}
        self.is_polling = False
        self.tab_tables = {}

        self.emitter = SignalEmitter()
        self.emitter.data_updated.connect(self._update_display)
        self.emitter.connection_changed.connect(self._on_connection_changed)

        self._build_signal_info()
        self._calc_register_range()
        self.init_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._update_display)
        self.refresh_timer.start(REFRESH_INTERVAL_MS)

    def _load_protocol_config(self, mode):
        """按架构动态加载协议配置（支持运行时切换 L2/L3）"""
        if mode == 'L2':
            import l2_protocol.protocol_config as cfg
            self.control_signals = list(getattr(cfg, 'CONTROL_SIGNALS', []))
        else:
            import l3_protocol.protocol_config as cfg
            self.control_signals = []
        self.register_groups = cfg.REGISTER_GROUPS
        self.poll_groups = cfg.POLL_GROUPS
        self.status_tabs = cfg.STATUS_TABS
        self.protocol_source = cfg.PROTOCOL_SOURCE

    def _on_mode_changed(self, mode):
        """架构切换：断开连接、重载协议、重建信号表格与寄存器视图"""
        if mode == self.mode:
            return
        if self.comm.is_connected:
            self._disconnect()
        self.mode = mode
        self._load_protocol_config(mode)
        self._original_register_groups = {
            k: list(v) for k, v in self.register_groups.items()
        } if self.register_groups else {}
        self.signal_info.clear()
        self.parsed_data.clear()
        self.register_values.clear()
        self._build_signal_info()
        self._calc_register_range()
        self._build_notebook_tables()
        self._init_reg_display()

    def _build_signal_info(self):
        for group in self.register_groups.values():
            for reg in group:
                addr, name, dtype, bit_start, bit_len, factor, offset, unit, desc, enum, en_name = reg
                if name not in self.signal_info:
                    self.signal_info[name] = (addr, bit_start, factor, offset, unit, dtype, bit_len)
        self._load_user_config()

    def _load_user_config(self):
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'protocol_user_config.json'
        )
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        mode_config = data.get(self.mode, {}).get('signals', {})
        for name, overrides in mode_config.items():
            if name not in self.signal_info:
                continue
            addr, bit_start, factor, offset, unit, dtype, bit_len = self.signal_info[name]
            # 支持地址与起始位覆盖（此前被遗漏）
            addr = int(overrides.get('addr', addr))
            bit_start = int(overrides.get('bit_start', bit_start))
            factor = overrides.get('factor', factor)
            offset = overrides.get('offset', offset)
            unit = overrides.get('unit', unit)
            dtype = overrides.get('datatype', dtype)
            bit_len = int(overrides.get('bit_length', bit_len))
            self.signal_info[name] = (addr, bit_start, factor, offset, unit, dtype, bit_len)
            self._sync_register_group(name, addr, bit_start, factor, offset, unit, dtype, bit_len)

    def _sync_register_group(self, name, addr, bit_start, factor, offset, unit, dtype, bit_len):
        """将用户覆盖写回 register_groups，使解码路径（poll_groups/parse_batch_response）同步生效"""
        for group_name, regs in self.register_groups.items():
            for i, reg in enumerate(regs):
                if len(reg) >= 2 and reg[1] == name:
                    new_reg = list(reg)
                    new_reg[0] = addr
                    new_reg[3] = bit_start
                    new_reg[4] = bit_len
                    new_reg[5] = factor
                    new_reg[6] = offset
                    new_reg[7] = unit
                    new_reg[2] = dtype
                    regs[i] = tuple(new_reg)
                    break

    def _reload_and_refresh(self):
        self.signal_info.clear()
        self._build_signal_info()
        self._calc_register_range()
        self._init_reg_display()
        for tab_name, table in self.tab_tables.items():
            for idx in range(table.rowCount()):
                item0 = table.item(idx, 0)
                if not item0:
                    continue
                signal_name = item0.text()
                info = self.signal_info.get(signal_name, (0, 0, 1, 0, "", "uint16", 16))
                addr, bit_start, factor, offset, unit, dtype, bit_len = info
                raw_val = self.register_values.get(addr)
                if raw_val is not None:
                    raw_hex = f"0x{raw_val:04X}" if raw_val > 255 else f"0x{raw_val:02X}"
                    raw_dec = str(raw_val)
                else:
                    raw_hex = "--"
                    raw_dec = "--"
                physical = self.parsed_data.get(signal_name, "--")
                item2 = table.item(idx, 2)
                item3 = table.item(idx, 3)
                item6 = table.item(idx, 6)
                if item2:
                    item2.setText(raw_hex)
                if item3:
                    item3.setText(raw_dec)
                if item6:
                    item6.setText(str(physical))

    def _apply_excel_import(self, result):
        from shared.excel_parser import parse_excel
        from l2_protocol.protocol_config import REGISTER_GROUPS as L2_REG
        from l3_protocol.protocol_config import REGISTER_GROUPS as L3_REG

        if self.mode == 'L2':
            import l2_protocol.protocol_config as cfg
            cfg.REGISTER_GROUPS = result['register_groups']
            cfg.POLL_GROUPS = result['poll_groups']
            cfg.STATUS_TABS = result['status_tabs']
            cfg.CONTROL_SIGNALS = result.get('control_signals', [])
            cfg.PROTOCOL_SOURCE = result['source_info']
        else:
            import l3_protocol.protocol_config as cfg
            cfg.REGISTER_GROUPS = result['register_groups']
            cfg.POLL_GROUPS = result['poll_groups']
            cfg.STATUS_TABS = result['status_tabs']
            cfg.PROTOCOL_SOURCE = result['source_info']

        self.register_groups = result['register_groups']
        self.poll_groups = result['poll_groups']
        self.status_tabs = result['status_tabs']
        self.protocol_source = result['source_info']
        if self.mode == 'L2':
            self.control_signals = result.get('control_signals', [])

        self.signal_info.clear()
        self.parsed_data.clear()
        self.register_values.clear()
        self._build_signal_info()
        self._calc_register_range()
        self._build_notebook_tables()
        self._init_reg_display()

    def _open_protocol_config(self):
        dlg = ProtocolConfigDialog(
            parent=self,
            mode=self.mode,
            register_groups=self.register_groups
        )
        dlg.exec_()

    def _calc_register_range(self):
        all_addrs = set()
        for group in self.register_groups.values():
            for reg in group:
                all_addrs.add(reg[0])
        if all_addrs:
            self.register_addrs = list(range(min(all_addrs), max(all_addrs) + 1))
        else:
            self.register_addrs = list(range(20, 134))

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)

        left_panel = self._create_left_panel()
        left_panel.setFixedWidth(380)
        splitter.addWidget(left_panel)

        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

    def _create_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ===== 连接设置 =====
        conn_group = QGroupBox("连接设置")
        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setSpacing(3)
        conn_layout.setContentsMargins(8, 14, 8, 6)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_lbl = QLabel("架构类型:")
        mode_lbl.setFixedWidth(120)
        mode_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mode_row.addWidget(mode_lbl)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["L2", "L3"])
        self.mode_combo.setCurrentText(self.mode)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        conn_layout.addLayout(mode_row)

        for label_text, widget in [
            ("COM口:", self._create_port_combo()),
            ("波特率:", self._create_baud_combo()),
            ("从机地址:", self._create_slave_spin()),
            ("轮询间隔(秒):", self._create_interval_spin()),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(120)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            conn_layout.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setMinimumHeight(30)
        self.connect_btn.clicked.connect(self._connect)
        btn_row.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setMinimumHeight(30)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self._disconnect)
        btn_row.addWidget(self.disconnect_btn)
        conn_layout.addLayout(btn_row)

        self.poll_btn = QPushButton("开始监控")
        self.poll_btn.setMinimumHeight(30)
        self.poll_btn.setEnabled(False)
        self.poll_btn.clicked.connect(self._toggle_polling)
        conn_layout.addWidget(self.poll_btn)

        layout.addWidget(conn_group)

        # ===== 控制指令 =====
        if self.mode in ('L2', 'L3'):
            ctrl_group = QGroupBox("控制指令(06H)")
            ctrl_layout = QVBoxLayout(ctrl_group)
            ctrl_layout.setSpacing(4)
            ctrl_layout.setContentsMargins(8, 14, 8, 6)

            for label_text, items in [
                ("上下电指令:", ["高压下电", "放电上电", "充电上电"]),
                ("复位/关机/消音:", ["无效", "复位", "关机", "消音"]),
            ]:
                lbl = QLabel(label_text)
                ctrl_layout.addWidget(lbl)
                row = QHBoxLayout()
                row.setSpacing(6)
                for text in items:
                    btn = QRadioButton(text)
                    if text == items[0]:
                        btn.setChecked(True)
                    if label_text.startswith("上下电"):
                        if not hasattr(self, 'pwr_group'):
                            self.pwr_group = QButtonGroup()
                            self.pwr_btns = {}
                        self.pwr_btns[text] = btn
                        self.pwr_group.addButton(btn)
                    else:
                        if not hasattr(self, 'rst_group'):
                            self.rst_group = QButtonGroup()
                            self.rst_btns = {}
                        self.rst_btns[text] = btn
                        self.rst_group.addButton(btn)
                    row.addWidget(btn)
                row.addStretch()
                ctrl_layout.addLayout(row)

            lbl = QLabel("急停报警:")
            ctrl_layout.addWidget(lbl)
            estop_row = QHBoxLayout()
            estop_row.setSpacing(6)
            self.estop_group = QButtonGroup()
            self.estop_btns = {}
            for text in ["正常", "急停"]:
                btn = QRadioButton(text)
                if text == "正常":
                    btn.setChecked(True)
                self.estop_btns[text] = btn
                self.estop_group.addButton(btn)
                estop_row.addWidget(btn)
            estop_row.addStretch()
            ctrl_layout.addLayout(estop_row)

            self.send_ctrl_btn = QPushButton("发送控制指令")
            self.send_ctrl_btn.setEnabled(False)
            self.send_ctrl_btn.clicked.connect(self._send_control)
            ctrl_layout.addWidget(self.send_ctrl_btn)

            layout.addWidget(ctrl_group)

        # ===== 通信统计 =====
        stats_group = QGroupBox("通信统计")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setSpacing(2)
        stats_layout.setContentsMargins(8, 14, 8, 6)

        self.tx_label = QLabel("TX: 0")
        self.rx_label = QLabel("RX: 0")
        self.error_label = QLabel("错误: 0")
        stats_layout.addWidget(self.tx_label)
        stats_layout.addWidget(self.rx_label)
        stats_layout.addWidget(self.error_label)

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setStyleSheet(
            f"background-color: gray; border-radius: 8px;"
        )
        stats_layout.addWidget(self.status_indicator)

        clear_btn = QPushButton("清空日志")
        clear_btn.setMinimumHeight(28)
        clear_btn.clicked.connect(self._clear_log)
        stats_layout.addWidget(clear_btn)

        config_btn = QPushButton("协议配置")
        config_btn.setMinimumHeight(28)
        config_btn.clicked.connect(self._open_protocol_config)
        stats_layout.addWidget(config_btn)

        layout.addWidget(stats_group)
        layout.addStretch()

        return panel

    def _create_port_combo(self):
        self.port_combo = QComboBox()
        self.port_combo.addItems(ModbusComm.list_available_ports())
        self.port_combo.setCurrentText("COM4")
        return self.port_combo

    def _create_baud_combo(self):
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        return self.baud_combo

    def _create_slave_spin(self):
        self.slave_spin = QSpinBox()
        self.slave_spin.setRange(1, 247)
        self.slave_spin.setValue(1)
        return self.slave_spin

    def _create_interval_spin(self):
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 10.0)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setValue(1.0)
        return self.interval_spin

    def _build_notebook_tables(self):
        """清空并重建信号表格（架构切换/协议导入后调用）"""
        while self.notebook.count() > 0:
            self.notebook.removeTab(0)
        self.tab_tables.clear()

        columns = ["信号名", "地址(DEC)", "原始值(HEX)", "原始值(DEC)", "因子", "偏移", "物理值", "单位"]

        for tab_name, signals in self.status_tabs:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(0)

            table = QTableWidget()
            table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels(columns)
            table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            table.setStyleSheet(f"""
                QTableWidget {{
                    gridline-color: {COLORS['border']};
                    padding: 0px;
                    margin: 0px;
                    font-size: 10pt;
                }}
                QTableWidget::item {{
                    padding-top: 6px;
                    padding-bottom: 6px;
                    padding-left: 8px;
                    padding-right: 8px;
                    margin: 0px;
                    font-size: 10pt;
                }}
                QTableWidget::item:selected {{
                    padding-left: 8px;
                }}
            """)

            # 信号名列左对齐，其余列居中
            table.setItemDelegateForColumn(0, SignalNameDelegate(table))

            header = table.horizontalHeader()
            for i in range(len(columns)):
                header.setSectionResizeMode(i, QHeaderView.Stretch)

            table.setRowCount(len(signals))
            table.verticalHeader().setDefaultSectionSize(36)
            table.verticalHeader().setMinimumSectionSize(32)
            table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
            self.tab_tables[tab_name] = table

            for idx, signal_name in enumerate(signals):
                info = self.signal_info.get(signal_name, (0, 0, 1, 0, "", "uint16", 16))
                addr, bit_start, factor, offset, unit, dtype, bit_len = info

                items = [
                    signal_name,
                    str(addr),
                    "--",
                    "--",
                    f"{factor}",
                    f"{offset}",
                    "--",
                    unit
                ]
                for col, text in enumerate(items):
                    item = QTableWidgetItem(text)
                    item.setFont(QFont('Microsoft YaHei', 10))
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter)
                    table.setItem(idx, col, item)

            tab_layout.addWidget(table)
            self.notebook.addTab(tab, tab_name)

    def _create_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.notebook = QTabWidget()
        self.notebook.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.notebook.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS['border']};
            }}
        """)

        self._build_notebook_tables()

        # 用垂直 QSplitter 分隔表格和寄存器视图，可拖拽调整比例
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.setHandleWidth(2)

        v_splitter.addWidget(self.notebook)

        reg_group = QGroupBox("寄存器视图")
        reg_layout = QVBoxLayout(reg_group)
        reg_layout.setContentsMargins(4, 4, 4, 4)
        reg_layout.setSpacing(0)

        self.reg_text = QTextEdit()
        self.reg_text.setReadOnly(True)
        self.reg_text.setFont(QFont('Consolas', 10))
        self.reg_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
            }}
        """)
        self.reg_text.setLineWrapMode(QTextEdit.NoWrap)
        self.reg_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        reg_layout.addWidget(self.reg_text)

        # register_addrs 已在 _calc_register_range 中动态计算
        self._init_reg_display()

        v_splitter.addWidget(reg_group)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 2)

        layout.addWidget(v_splitter)

        return panel

    def _init_reg_display(self):
        self.reg_text.clear()
        html = ""
        addr_list = self.register_addrs
        for i in range(0, len(addr_list), REGISTERS_PER_ROW):
            row_html = ""
            for j in range(REGISTERS_PER_ROW):
                if i + j < len(addr_list):
                    addr = addr_list[i + j]
                    reg_4xxxx = addr + MODBUS_HOLDING_REGISTER_BASE
                    row_html += f'<span style="color:#666666;">{reg_4xxxx:05d}: </span>'
                    row_html += f'<span style="color:#999999;">&lt;----&gt;</span>'
                    if j < REGISTERS_PER_ROW - 1 and i + j + 1 < len(addr_list):
                        row_html += "&nbsp;&nbsp;&nbsp;"
            html += row_html + "<br>"
        self.reg_text.setHtml(html)

    def _update_reg_display(self):
        html = ""
        addr_list = self.register_addrs
        for i in range(0, len(addr_list), REGISTERS_PER_ROW):
            row_html = ""
            for j in range(REGISTERS_PER_ROW):
                if i + j < len(addr_list):
                    addr = addr_list[i + j]
                    reg_4xxxx = addr + MODBUS_HOLDING_REGISTER_BASE
                    raw_val = self.register_values.get(addr)
                    row_html += f'<span style="color:#666666;">{reg_4xxxx:05d}: </span>'
                    if raw_val is not None:
                        hex_str = f"{raw_val:04X}"
                        row_html += f'<span style="color:#000000;">&lt;{hex_str}H&gt;</span>'
                    else:
                        row_html += f'<span style="color:#999999;">&lt;----&gt;</span>'
                    if j < REGISTERS_PER_ROW - 1 and i + j + 1 < len(addr_list):
                        row_html += "&nbsp;&nbsp;&nbsp;"
            html += row_html + "<br>"
        self.reg_text.setHtml(html)

    def _update_display(self):
        for tab_name, table in self.tab_tables.items():
            for idx in range(table.rowCount()):
                item0 = table.item(idx, 0)
                if not item0:
                    continue
                signal_name = item0.text()
                info = self.signal_info.get(signal_name, (0, 0, 1, 0, "", "uint16", 16))
                addr, bit_start, factor, offset, unit, dtype, bit_len = info

                raw_val = self.register_values.get(addr)
                if raw_val is not None:
                    raw_hex = f"0x{raw_val:04X}" if raw_val > 255 else f"0x{raw_val:02X}"
                    raw_dec = str(raw_val)
                else:
                    raw_hex = "--"
                    raw_dec = "--"

                physical = self.parsed_data.get(signal_name, "--")

                item2 = table.item(idx, 2)
                item3 = table.item(idx, 3)
                item6 = table.item(idx, 6)
                if item2:
                    item2.setText(raw_hex)
                if item3:
                    item3.setText(raw_dec)
                if item6:
                    item6.setText(str(physical))

                # 强制信号名列保持左对齐
                item0.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        stats = self.comm.get_stats()
        self.tx_label.setText(f"TX: {stats['frames_sent']}")
        self.rx_label.setText(f"RX: {stats['frames_received']}")
        self.error_label.setText(f"错误: {stats['crc_errors'] + stats['timeouts']}")

        if self._need_reg_refresh:
            self._update_reg_display()
            self._need_reg_refresh = False

    _need_reg_refresh = False

    def _connect(self):
        port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())
        slave = self.slave_spin.value()
        interval = self.interval_spin.value()

        self.comm.port = port
        self.comm.baudrate = baud
        self.comm.slave_id = slave
        self.comm.poll_interval = interval

        if self.comm.connect():
            self.emitter.connection_changed.emit(True)
        else:
            QMessageBox.critical(self, "连接失败",
                                 f"无法连接到 {port}\n{self.comm.stats.get('last_error', '')}")

    def _disconnect(self):
        self.comm.disconnect()
        self.emitter.connection_changed.emit(False)
        self.register_values.clear()
        self._init_reg_display()

    def _on_connection_changed(self, connected):
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.poll_btn.setEnabled(connected)
        if hasattr(self, 'send_ctrl_btn'):
            self.send_ctrl_btn.setEnabled(connected)
        self.status_indicator.setStyleSheet(
            f"background-color: {'green' if connected else 'gray'}; border-radius: 10px;"
        )
        if not connected:
            self.poll_btn.setText("开始监控")
            self.is_polling = False

    def _toggle_polling(self):
        if self.is_polling:
            self.comm.stop_polling()
            self.poll_btn.setText("开始监控")
            self.is_polling = False
        else:
            self.comm.start_polling(self.poll_groups, self._poll_callback)
            self.poll_btn.setText("停止监控")
            self.is_polling = True

    def _poll_callback(self, group_index, response, timestamp):
        if response is None:
            return

        start_addr, quantity = self.poll_groups[group_index]
        reg_defs = []
        for group in self.register_groups.values():
            for reg in group:
                if start_addr <= reg[0] < start_addr + quantity:
                    reg_defs.append(reg)

        if reg_defs:
            parsed = parse_read_response(response)
            if parsed and parsed['crc_valid']:
                for i, raw_val in enumerate(parsed['registers']):
                    addr = start_addr + i
                    self.register_values[addr] = raw_val

            decoded = parse_batch_response(response, start_addr, reg_defs)
            if decoded:
                self.parsed_data.update(decoded)

        self._need_reg_refresh = True
        self.emitter.data_updated.emit()

    def _send_control(self):
        if not self.comm.is_connected:
            QMessageBox.warning(self, "警告", "请先连接串口")
            return

        try:
            pwr_map = {"高压下电": 0, "放电上电": 1, "充电上电": 2}
            pwr_val = 0
            for text, btn in self.pwr_btns.items():
                if btn.isChecked():
                    pwr_val = pwr_map.get(text, 0)
                    break

            rst_map = {"无效": 0, "复位": 1, "关机": 2, "消音": 3}
            rst_val = 0
            for text, btn in self.rst_btns.items():
                if btn.isChecked():
                    rst_val = rst_map.get(text, 0)
                    break

            estop_val = 1 if self.estop_btns["急停"].isChecked() else 0

            addr2_val = (pwr_val << 0) | (rst_val << 2) | (estop_val << 4)

            response = self.comm.write_register(2, addr2_val)
            if response:
                log_msg = (f"控制指令: 地址2=0x{addr2_val:04X} "
                          f"(上下电={pwr_val}, 复位关机消音={rst_val}, 急停={estop_val})")
                QMessageBox.information(self, "成功",
                                        f"控制指令已发送\n地址2 = 0x{addr2_val:04X}\n{log_msg}")
            else:
                QMessageBox.critical(self, "错误", "发送控制指令失败")

        except (ValueError, RuntimeError) as e:
            QMessageBox.critical(self, "错误", f"发送控制指令时出错: {str(e)}")

    def _clear_log(self):
        self.register_values.clear()
        self._init_reg_display()
        self.comm.clear_log()
