"""
BMS监控Tab - PyQt5重写
支持L2和L3两种模式
"""

import sys
import os
import threading
import time
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QRadioButton, QButtonGroup, QStatusBar, QMessageBox, QFrame,
    QTabWidget, QSizePolicy, QLayout
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor

from shared.style import COLORS, FONTS
from shared.modbus_comm import ModbusComm
from shared.modbus_parser import parse_read_response, parse_batch_response


class SignalEmitter(QObject):
    """跨线程信号发射器"""
    data_updated = pyqtSignal()
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)


class BmsMonitorTab(QWidget):
    """BMS监控Tab - 支持L2/L3"""

    def __init__(self, mode='L2', parent=None):
        super().__init__(parent)
        self.mode = mode

        if mode == 'L2':
            from l2_protocol.protocol_config import REGISTER_GROUPS, POLL_GROUPS, STATUS_TABS, PROTOCOL_SOURCE, CONTROL_SIGNALS
        else:
            from l3_protocol.protocol_config import REGISTER_GROUPS, POLL_GROUPS, STATUS_TABS, PROTOCOL_SOURCE
            CONTROL_SIGNALS = []

        self.register_groups = REGISTER_GROUPS
        self.poll_groups = POLL_GROUPS
        self.status_tabs = STATUS_TABS
        self.protocol_source = PROTOCOL_SOURCE
        self.control_signals = CONTROL_SIGNALS

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
        self.refresh_timer.start(500)

    def _build_signal_info(self):
        for group in self.register_groups.values():
            for reg in group:
                addr, name, dtype, bit_start, bit_len, factor, offset, unit, desc, enum, en_name = reg
                if name not in self.signal_info:
                    self.signal_info[name] = (addr, factor, offset, unit, dtype, bit_len)

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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        conn_group = QGroupBox("连接设置")
        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setSpacing(4)
        conn_layout.setContentsMargins(8, 12, 8, 8)

        conn_layout.addWidget(QLabel("COM口:"))
        self.port_combo = QComboBox()
        self.port_combo.addItems(ModbusComm.list_available_ports())
        self.port_combo.setCurrentText("COM4")
        conn_layout.addWidget(self.port_combo)

        conn_layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        conn_layout.addWidget(self.baud_combo)

        conn_layout.addWidget(QLabel("从机地址:"))
        self.slave_spin = QSpinBox()
        self.slave_spin.setRange(1, 247)
        self.slave_spin.setValue(1)
        conn_layout.addWidget(self.slave_spin)

        conn_layout.addWidget(QLabel("轮询间隔(秒):"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 10.0)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setValue(1.0)
        conn_layout.addWidget(self.interval_spin)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setMinimumHeight(32)
        self.connect_btn.clicked.connect(self._connect)
        conn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setMinimumHeight(32)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self._disconnect)
        conn_layout.addWidget(self.disconnect_btn)

        self.poll_btn = QPushButton("开始监控")
        self.poll_btn.setMinimumHeight(32)
        self.poll_btn.setEnabled(False)
        self.poll_btn.clicked.connect(self._toggle_polling)
        conn_layout.addWidget(self.poll_btn)

        layout.addWidget(conn_group)

        if self.mode in ('L2', 'L3'):
            ctrl_group = QGroupBox("控制指令(06H)")
            ctrl_layout = QVBoxLayout(ctrl_group)

            ctrl_layout.addWidget(QLabel("上下电指令:"))
            self.pwr_group = QButtonGroup()
            self.pwr_btns = {}
            pwr_layout = QHBoxLayout()
            for text in ["高压下电", "放电上电", "充电上电"]:
                btn = QRadioButton(text)
                if text == "高压下电":
                    btn.setChecked(True)
                self.pwr_btns[text] = btn
                self.pwr_group.addButton(btn)
                pwr_layout.addWidget(btn)
            ctrl_layout.addLayout(pwr_layout)

            ctrl_layout.addWidget(QLabel("复位/关机/消音:"))
            self.rst_group = QButtonGroup()
            self.rst_btns = {}
            rst_layout = QHBoxLayout()
            for text in ["无效", "复位", "关机", "消音"]:
                btn = QRadioButton(text)
                if text == "无效":
                    btn.setChecked(True)
                self.rst_btns[text] = btn
                self.rst_group.addButton(btn)
                rst_layout.addWidget(btn)
            ctrl_layout.addLayout(rst_layout)

            ctrl_layout.addWidget(QLabel("急停报警:"))
            self.estop_group = QButtonGroup()
            self.estop_btns = {}
            estop_layout = QHBoxLayout()
            for text in ["正常", "急停"]:
                btn = QRadioButton(text)
                if text == "正常":
                    btn.setChecked(True)
                self.estop_btns[text] = btn
                self.estop_group.addButton(btn)
                estop_layout.addWidget(btn)
            ctrl_layout.addLayout(estop_layout)

            self.send_ctrl_btn = QPushButton("发送控制指令")
            self.send_ctrl_btn.setEnabled(False)
            self.send_ctrl_btn.clicked.connect(self._send_control)
            ctrl_layout.addWidget(self.send_ctrl_btn)

            layout.addWidget(ctrl_group)

        stats_group = QGroupBox("通信统计")
        stats_layout = QVBoxLayout(stats_group)

        self.tx_label = QLabel("TX: 0")
        self.rx_label = QLabel("RX: 0")
        self.error_label = QLabel("错误: 0")
        stats_layout.addWidget(self.tx_label)
        stats_layout.addWidget(self.rx_label)
        stats_layout.addWidget(self.error_label)

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.status_indicator.setStyleSheet(
            f"background-color: gray; border-radius: 10px;"
        )
        stats_layout.addWidget(self.status_indicator)

        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self._clear_log)
        stats_layout.addWidget(clear_btn)

        layout.addWidget(stats_group)
        layout.addStretch()

        return panel

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

            header = table.horizontalHeader()
            for i in range(len(columns)):
                header.setSectionResizeMode(i, QHeaderView.Stretch)

            table.setRowCount(len(signals))
            table.verticalHeader().setDefaultSectionSize(30)
            table.verticalHeader().setMinimumSectionSize(28)
            table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

            for idx, signal_name in enumerate(signals):
                info = self.signal_info.get(signal_name, (0, 1, 0, "", "uint16", 16))
                addr, factor, offset, unit, dtype, bit_len = info

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
                    if col == 0:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    else:
                        item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(idx, col, item)

            tab_layout.addWidget(table)
            self.notebook.addTab(tab, tab_name)
            self.tab_tables[tab_name] = table

        # 用 QVBoxLayout 分隔表格和寄存器视图，表格自动扩展
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        right_layout.addWidget(self.notebook, 1)

        reg_group = QGroupBox("寄存器视图")
        reg_layout = QVBoxLayout(reg_group)
        reg_layout.setContentsMargins(4, 4, 4, 4)
        reg_layout.setSpacing(0)

        self.reg_text = QTextEdit()
        self.reg_text.setReadOnly(True)
        self.reg_text.setFont(QFont('Consolas', 11))
        self.reg_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
            }}
        """)
        self.reg_text.setLineWrapMode(QTextEdit.NoWrap)
        self.reg_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.reg_text.setMaximumHeight(250)
        self.reg_text.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed
        )
        reg_layout.addWidget(self.reg_text)

        # register_addrs 已在 _calc_register_range 中动态计算
        self._init_reg_display()

        right_layout.addWidget(reg_group, 0)

        layout.addLayout(right_layout)

        return panel

    def _init_reg_display(self):
        self.reg_text.clear()
        html = ""
        cols_per_row = 7
        addr_list = self.register_addrs
        for i in range(0, len(addr_list), cols_per_row):
            row_html = ""
            for j in range(cols_per_row):
                if i + j < len(addr_list):
                    addr = addr_list[i + j]
                    reg_4xxxx = addr + 40001
                    row_html += f'<span style="color:#666666;">{reg_4xxxx:05d}: </span>'
                    row_html += f'<span style="color:#999999;">&lt;----&gt;</span>'
                    if j < cols_per_row - 1 and i + j + 1 < len(addr_list):
                        row_html += "&nbsp;&nbsp;"
            html += row_html + "<br>"
        self.reg_text.setHtml(html)

    def _update_reg_display(self):
        html = ""
        cols_per_row = 7
        addr_list = self.register_addrs
        for i in range(0, len(addr_list), cols_per_row):
            row_html = ""
            for j in range(cols_per_row):
                if i + j < len(addr_list):
                    addr = addr_list[i + j]
                    reg_4xxxx = addr + 40001
                    raw_val = self.register_values.get(addr)
                    row_html += f'<span style="color:#666666;">{reg_4xxxx:05d}: </span>'
                    if raw_val is not None:
                        hex_str = f"{raw_val:04X}"
                        row_html += f'<span style="color:#000000;">&lt;{hex_str}H&gt;</span>'
                    else:
                        row_html += f'<span style="color:#999999;">&lt;----&gt;</span>'
                    if j < cols_per_row - 1 and i + j + 1 < len(addr_list):
                        row_html += "&nbsp;&nbsp;"
            html += row_html + "<br>"
        self.reg_text.setHtml(html)

    def _update_display(self):
        for tab_name, table in self.tab_tables.items():
            for idx in range(table.rowCount()):
                signal_name = table.item(idx, 0).text()
                info = self.signal_info.get(signal_name, (0, 1, 0, "", "uint16", 16))
                addr, factor, offset, unit, dtype, bit_len = info

                raw_val = self.register_values.get(addr)
                if raw_val is not None:
                    raw_hex = f"0x{raw_val:04X}" if raw_val > 255 else f"0x{raw_val:02X}"
                    raw_dec = str(raw_val)
                else:
                    raw_hex = "--"
                    raw_dec = "--"

                physical = self.parsed_data.get(signal_name, "--")

                table.item(idx, 2).setText(raw_hex)
                table.item(idx, 3).setText(raw_dec)
                table.item(idx, 6).setText(str(physical))

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

        except Exception as e:
            QMessageBox.critical(self, "错误", f"发送控制指令时出错: {str(e)}")

    def _clear_log(self):
        self.register_values.clear()
        self._init_reg_display()
        self.comm.clear_log()
