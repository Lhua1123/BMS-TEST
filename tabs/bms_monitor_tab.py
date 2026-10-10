"""
BMS监控Tab - PyQt5重写
支持L2和L3两种模式
"""

import sys
import os
import json
import logging
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
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QModelIndex, QEvent
from PyQt5.QtGui import QFont, QColor, QFontMetrics

from tabs.protocol_config_dialog import ProtocolConfigDialog
from shared.style import COLORS, FONTS, themed_qss, on_theme_changed
from shared.modbus_comm import ModbusComm
from shared.modbus_parser import parse_read_response, parse_batch_response
from shared.constants import (
    MODBUS_HOLDING_REGISTER_BASE,
    REGISTERS_PER_ROW,
    BMS_REGISTER_START_ADDR,
    REFRESH_INTERVAL_MS
)
from shared.utils import get_protocol_config_path

logger = logging.getLogger(__name__)

try:  # sip 用于判断 C++ 对象是否已销毁，导入失败时降级为 try/except 守卫
    from PyQt5 import sip
except Exception:  # pragma: no cover
    sip = None


def _qobj_is_deleted(obj) -> bool:
    """判断 Qt 对象的底层 C++ 对象是否已销毁（无法判断时返回 False，由调用方 try/except 兜底）"""
    if obj is None:
        return True
    if sip is None:
        return False
    try:
        return bool(sip.isdeleted(obj))
    except Exception:
        return False


class _SignalTableColumnFilter(QObject):
    """监视表格 viewport 尺寸变化，触发列宽按权重重分配"""

    def __init__(self, table: QTableWidget, reflow_fn, parent=None):
        super().__init__(parent if parent is not None else table)
        self._table = table
        self._reflow = reflow_fn
        self._pending = False
        table.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        # 事件回调中绝不允许异常逃逸（逃逸会导致 PyQt qFatal abort 整个进程）
        try:
            # 表格/过滤器自身 C++ 对象可能已销毁（removeTab 清理或退出析构顺序）
            if _qobj_is_deleted(self) or _qobj_is_deleted(self._table):
                return False
            if _qobj_is_deleted(watched):
                return False
            if watched is self._table.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
                if not self._pending:
                    self._pending = True
                    # 合并同帧多次 resize，避免抖动
                    QTimer.singleShot(0, self._do_reflow)
            return super().eventFilter(watched, event)
        except Exception:
            return False

    def _do_reflow(self):
        self._pending = False
        try:
            self._reflow()
        except Exception:
            pass


class SignalEmitter(QObject):
    """跨线程信号发射器"""
    data_updated = pyqtSignal()
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)


def _signal_table_qss() -> str:
    """信号表格样式（网格线颜色随主题变化）"""
    return f"""
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
            """


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


class AlarmColorDelegate(QStyledItemDelegate):
    """物理值列(第6列)专用：选中态仍保留报警等级色，只覆盖文字色。

    背景保持默认选中蓝底，未选中/非报警文本走父类默认绘制
    （未选中时的颜色靠 _update_display() 的 setForeground 兜底）。
    高频 paint，只做 _normalize_alarm_text + _alarm_color 两次轻量判断。
    """

    def paint(self, painter, option, index):
        try:
            raw = index.data(Qt.DisplayRole)
            # 信号名未知：传空串，不依赖信号名，第6列凡是匹配到等级/故障文本就染色
            norm = _normalize_alarm_text(raw, "", False)
            fg = _alarm_color(norm)
        except Exception:
            fg = None
        if fg is None:
            super().paint(painter, option, index)
            return
        if not (option.state & QStyle.State_Selected):
            # 未选中：沿用 model 的 Foreground（_update_display 已设置），走默认绘制
            super().paint(painter, option, index)
            return
        # 选中 + 报警文本：蓝底上用等级色写字，绕开 QSS 的 color:#fff
        painter.save()
        painter.fillRect(option.rect, QColor(COLORS['accent']))
        painter.setPen(fg)
        painter.setFont(option.font)
        text = index.data(Qt.DisplayRole)
        if text is None:
            text = ""
        else:
            text = str(text)
        painter.drawText(option.rect, Qt.AlignCenter, text)
        painter.restore()


# ── 报警状态统一显示：正常 / 一级报警(琥珀黄) / 二级报警(橙) / 三级报警·故障(红) ──
# 兼容老 protocol_config（内含旧枚举文本"无报警"/"报警"），显示时归一化并按等级染色。
# 报警颜色取自 COLORS（alarm_l1/l2/l3），随浅色/深色主题变化

# 仅报警/故障类信号名才做数字归一化，避免误伤电压/温度等数值信号
# 注：“与PMS/EMS通讯丢失”这类名不含报警/故障关键字，靠告警分组兜底（见 _ALARM_TAB_NAMES）
_ALARM_NUMERIC_NAME_KEYS = ('告警', '报警', '过放', '过充', '过温', '故障', '继电器', '接触器',
                            '丢失', '失败', '异常', '保护', '急停', '一致性', '通讯')
_ALARM_TAB_NAMES = ('告警', '告警状态', '故障状态', '故障信息')


def _normalize_alarm_text(text, signal_name="", is_alarm_tab=False):
    """归一化报警显示文本（兼容老配置里的旧枚举文本）。

    - "无报警" -> "正常"；单个"报警"(exact) -> "故障"
    - 数字 0（int 0 或 "0"）且在告警分组或信号名像报警/故障位 -> "正常"；
      数字非 0 且在告警分组或信号名像报警/故障位 -> "故障"
    - 非报警类信号的数字原样返回（不动电压/温度等数值）
    """
    name = signal_name or ""
    is_alarm = is_alarm_tab or any(k in name for k in _ALARM_NUMERIC_NAME_KEYS)
    if isinstance(text, bool):
        return text
    if isinstance(text, int):
        if is_alarm:
            return "正常" if text == 0 else "故障"
        return text
    if isinstance(text, str):
        s = text.strip()
        if s == "无报警":
            return "正常"
        if s == "报警":
            return "故障"
        if s.lstrip("+-").isdigit():
            if is_alarm:
                try:
                    num = int(s)
                except ValueError:
                    return s
                return "正常" if num == 0 else "故障"
        return s
    return text


def _alarm_color(display_text):
    """报警文本 -> 前景色；正常/其他 -> None（调用方需显式恢复默认色）"""
    s = display_text.strip() if isinstance(display_text, str) else str(display_text)
    if s == "一级报警":
        return QColor(COLORS['alarm_l1'])
    if s == "二级报警":
        return QColor(COLORS['alarm_l2'])
    if s in ("三级报警", "故障", "开路", "粘连", "报警"):
        return QColor(COLORS['alarm_l3'])
    return None


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
        # 本页面（切换后）已真正读到的信号名 / 寄存器地址；未读到的一律显示 "--"
        self._fresh_names = set()
        self._fresh_addrs = set()
        self.signal_info = {}
        self.is_polling = False
        self.tab_tables = {}
        self.active_poll_groups = []

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
        self.protocol_version = getattr(cfg, 'PROTOCOL_VERSION', '')

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
        config_path = get_protocol_config_path()
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        mode_config = data.get(self.mode, {}).get('signals', {})
        saved_version = data.get(self.mode, {}).get('protocol_version', '')
        if saved_version and self.protocol_version and saved_version != self.protocol_version:
            logger.warning(
                f"[{self.mode}] 协议版本不匹配：用户配置={saved_version}，当前协议={self.protocol_version}，"
                f"建议点击「恢复默认」或重新导入协议"
            )

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

        # 用更新后的 register_groups 重新解码已有 raw 值，使 factor/offset 等参数立即生效
        if self.register_values:
            try:
                from shared.modbus_parser import decode_registers
                all_reg_defs = []
                for regs in self.register_groups.values():
                    all_reg_defs.extend(regs)
                if all_reg_defs:
                    min_addr = min(self.register_values.keys())
                    max_addr = max(self.register_values.keys())
                    registers = [self.register_values.get(addr, 0) for addr in range(min_addr, max_addr + 1)]
                    new_decoded = decode_registers(registers, all_reg_defs, min_addr)
                    if new_decoded:
                        self.parsed_data.clear()
                        self.parsed_data.update(new_decoded)
            except Exception:
                pass

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
                item1 = table.item(idx, 1)
                item2 = table.item(idx, 2)
                item3 = table.item(idx, 3)
                item4 = table.item(idx, 4)
                item5 = table.item(idx, 5)
                item6 = table.item(idx, 6)
                item7 = table.item(idx, 7)
                if item1:
                    item1.setText(str(addr))
                if item2:
                    item2.setText(raw_hex)
                if item3:
                    item3.setText(raw_dec)
                if item4:
                    item4.setText(f"{factor}")
                if item5:
                    item5.setText(f"{offset}")
                if item6:
                    item6.setText(str(physical))
                if item7:
                    item7.setText(unit)

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

        # 切换浅色/深色时，重画报警色、寄存器视图等不走样式表的颜色
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self):
        if hasattr(self, 'reg_text'):
            self._update_reg_display()
        if hasattr(self, 'tab_tables'):
            self._update_display()

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
                if label_text.startswith("上下电"):
                    if not hasattr(self, 'pwr_group'):
                        self.pwr_group = QButtonGroup()
                        self.pwr_group.setExclusive(False)
                        self.pwr_btns = {}
                    btns_map = self.pwr_btns
                    group = self.pwr_group
                else:
                    if not hasattr(self, 'rst_group'):
                        self.rst_group = QButtonGroup()
                        self.rst_group.setExclusive(False)
                        self.rst_btns = {}
                    btns_map = self.rst_btns
                    group = self.rst_group
                for text in items:
                    btn = QRadioButton(text)
                    btns_map[text] = btn
                    group.addButton(btn)
                    # 再次点击已选项可取消，恢复“未选”空白状态
                    btn.clicked.connect(
                        lambda checked, b=btn, m=btns_map: self._on_ctrl_radio_clicked(b, m)
                    )
                    row.addWidget(btn)
                row.addStretch()
                ctrl_layout.addLayout(row)

            lbl = QLabel("急停报警:")
            ctrl_layout.addWidget(lbl)
            estop_row = QHBoxLayout()
            estop_row.setSpacing(6)
            self.estop_group = QButtonGroup()
            self.estop_group.setExclusive(False)
            self.estop_btns = {}
            for text in ["正常", "急停"]:
                btn = QRadioButton(text)
                self.estop_btns[text] = btn
                self.estop_group.addButton(btn)
                btn.clicked.connect(
                    lambda checked, b=btn, m=self.estop_btns: self._on_ctrl_radio_clicked(b, m)
                )
                estop_row.addWidget(btn)
            estop_row.addStretch()
            ctrl_layout.addLayout(estop_row)

            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(8)
            self.send_ctrl_btn = QPushButton("发送控制指令")
            self.send_ctrl_btn.setEnabled(False)
            self.send_ctrl_btn.clicked.connect(self._send_control)
            ctrl_row.addWidget(self.send_ctrl_btn)

            self.heartbeat_btn = QPushButton("▶ 启动心跳")
            self.heartbeat_btn.setMinimumHeight(30)
            self.heartbeat_btn.setEnabled(False)
            self.heartbeat_btn.setCheckable(True)
            self.heartbeat_btn.clicked.connect(self._toggle_heartbeat)
            ctrl_row.addWidget(self.heartbeat_btn)
            ctrl_row.addStretch()
            ctrl_layout.addLayout(ctrl_row)

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
        # None=尚未有连接状态变化（初始灰点）；True/False=已连接/未连接
        self._link_state = None
        themed_qss(self.status_indicator, self._indicator_qss)
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

    # 各列最小宽度（px）
    _SIGNAL_COL_MIN = (140, 64, 80, 80, 56, 56, 110, 56)
    # 富余宽度分配权重：信号名略高，其余更均衡（不要再把信号名撑爆）
    _SIGNAL_COL_SHARE = (1.35, 0.9, 1.0, 1.0, 0.75, 0.75, 1.15, 0.75)

    def _setup_signal_table_columns(self, table: QTableWidget, col_count: int):
        """列宽可拖拽；默认按内容自适应 + 剩余宽度较均衡铺满"""
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)

        mins = list(self._SIGNAL_COL_MIN[:col_count])
        shares = list(self._SIGNAL_COL_SHARE[:col_count])
        while len(mins) < col_count:
            mins.append(48)
            while len(shares) < col_count:
                shares.append(0.9)

        for i in range(col_count):
            header.setSectionResizeMode(i, QHeaderView.Interactive)

        font = QFont('Microsoft YaHei', 10)
        fm = QFontMetrics(font)

        def content_widths():
            """按表头+单元格文字估算自然宽度"""
            widths = []
            for i in range(col_count):
                label = header.model().headerData(i, Qt.Horizontal)
                w = fm.horizontalAdvance(str(label) if label else "")
                for row in range(table.rowCount()):
                    item = table.item(row, i)
                    if item:
                        w = max(w, fm.horizontalAdvance(item.text()))
                widths.append(w + 20)  # 左右内边距
            return widths

        def reflow(viewport_w: int = None):
            if viewport_w is None:
                viewport_w = table.viewport().width()
            if viewport_w <= 40:
                return

            content = content_widths()
            preferred = [max(c, m) for c, m in zip(content, mins)]
            total_pref = sum(preferred)

            if total_pref <= viewport_w:
                # 不够占满：把富余按 share 分掉（信号名只多拿一点）
                extra = viewport_w - total_pref
                share_sum = float(sum(shares)) or 1.0
                target = [p + int(extra * s / share_sum)
                          for p, s in zip(preferred, shares)]
                # 消掉取整误差
                gap = viewport_w - sum(target)
                if gap != 0:
                    target[-1] += gap
            else:
                # 超出视口：按 preferred 等比缩小，但不低于 min
                scale = viewport_w / float(total_pref)
                target = [max(int(p * scale), m) for p, m in zip(preferred, mins)]
                # 仍可能略超，从最宽列开始削
                while sum(target) > viewport_w:
                    idx = max(range(col_count), key=lambda i: target[i] - mins[i])
                    if target[idx] <= mins[idx]:
                        break
                    target[idx] -= 1

            for i, w in enumerate(target):
                header.resizeSection(i, w)

        table._col_width_filter = _SignalTableColumnFilter(table, reflow)
        # 数据填完后再量一次内容
        QTimer.singleShot(0, reflow)
        QTimer.singleShot(80, reflow)
        table._reflow_column_widths = reflow

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
            themed_qss(table, _signal_table_qss)

            # 信号名列左对齐，其余列居中
            table.setItemDelegateForColumn(0, SignalNameDelegate(table))
            # 物理值列(第6列)选中态仍保留报警等级色，不影响其他列
            table.setItemDelegateForColumn(6, AlarmColorDelegate(table))
            self._setup_signal_table_columns(table, len(columns))

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

            # 内容填完后按实际文字宽度再排一次
            if hasattr(table, '_reflow_column_widths'):
                QTimer.singleShot(0, table._reflow_column_widths)

            tab_layout.addWidget(table)
            self.notebook.addTab(tab, tab_name)

    def _create_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.notebook = QTabWidget()
        self.notebook.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        themed_qss(self.notebook, lambda: f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS['border']};
            }}
        """)

        self._build_notebook_tables()

        # 切换分组标签时，只轮询当前标签对应寄存器
        self.notebook.currentChanged.connect(self._on_status_tab_changed)

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
        themed_qss(self.reg_text, lambda: f"""
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
                    row_html += f'<span style="color:{COLORS["reg_label"]};">{reg_4xxxx:05d}: </span>'
                    row_html += f'<span style="color:{COLORS["reg_dim"]};">&lt;----&gt;</span>'
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
                    row_html += f'<span style="color:{COLORS["reg_label"]};">{reg_4xxxx:05d}: </span>'
                    if raw_val is not None:
                        hex_str = f"{raw_val:04X}"
                        row_html += f'<span style="color:{COLORS["reg_value"]};">&lt;{hex_str}H&gt;</span>'
                    else:
                        row_html += f'<span style="color:{COLORS["reg_dim"]};">&lt;----&gt;</span>'
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

                # 未在本页面读到的数据不显示（避免切换瞬间出现旧值/默认值）
                fresh = signal_name in self._fresh_names
                raw_val = self.register_values.get(addr) if addr in self._fresh_addrs else None
                if raw_val is not None:
                    raw_hex = f"0x{raw_val:04X}" if raw_val > 255 else f"0x{raw_val:02X}"
                    raw_dec = str(raw_val)
                else:
                    raw_hex = "--"
                    raw_dec = "--"

                physical = self.parsed_data.get(signal_name, "--") if fresh else "--"

                item2 = table.item(idx, 2)
                item3 = table.item(idx, 3)
                item6 = table.item(idx, 6)
                if item2:
                    item2.setText(raw_hex)
                if item3:
                    item3.setText(raw_dec)
                if item6:
                    # 数值型字段（故障码 8位、组当前故障数量 uint8 等）保留原数字；
                    # 仅 1~2 位的位域报警/故障标志才归一化为正常/故障
                    if dtype == "bitfield" and bit_len <= 2:
                        display = _normalize_alarm_text(physical, signal_name, tab_name in _ALARM_TAB_NAMES)
                    else:
                        display = physical
                    item6.setText(str(display))
                    fg = _alarm_color(display)
                    if fg is not None:
                        item6.setForeground(fg)
                    else:
                        item6.setForeground(QColor(COLORS['text']))

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
        self.comm.stop_heartbeat()
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
        if hasattr(self, 'heartbeat_btn'):
            self.heartbeat_btn.setEnabled(connected)
            if not connected:
                self.heartbeat_btn.setChecked(False)
                self.heartbeat_btn.setText("▶ 启动心跳")
        self._link_state = bool(connected)
        self.status_indicator.setStyleSheet(self._indicator_qss())
        if not connected:
            self.poll_btn.setText("开始监控")
            self.is_polling = False

    def _indicator_qss(self) -> str:
        """状态指示灯样式（颜色随主题变化）"""
        if self._link_state is None:
            return f"background-color: {COLORS['status_off']}; border-radius: 8px;"
        color = COLORS['status_on'] if self._link_state else COLORS['status_off']
        return f"background-color: {color}; border-radius: 10px;"

    def _build_poll_ranges(self, addrs) -> list:
        """把地址列表合并成尽量少的连续读区间 [(start, quantity), ...]"""
        addrs = sorted(set(int(a) for a in addrs if a is not None and int(a) >= 20))
        groups = []
        if not addrs:
            return groups
        start = addrs[0]
        end = start
        for addr in addrs[1:]:
            if addr == end + 1 and addr - start < 20:
                end = addr
            else:
                groups.append((start, end - start + 1))
                start = addr
                end = addr
        groups.append((start, end - start + 1))
        return groups

    def _current_tab_poll_groups(self) -> list:
        """当前选中分组标签内信号对应的轮询地址组；无信号时回退为全部 poll_groups"""
        if not hasattr(self, 'notebook') or self.notebook is None:
            return list(self.poll_groups)
        idx = self.notebook.currentIndex()
        if idx < 0 or idx >= len(self.status_tabs):
            return list(self.poll_groups)
        _tab_name, signals = self.status_tabs[idx]
        addrs = []
        for name in signals:
            info = self.signal_info.get(name)
            if info:
                addrs.append(info[0])
        ranges = self._build_poll_ranges(addrs)
        return ranges if ranges else list(self.poll_groups)

    def _on_status_tab_changed(self, _index=None):
        """切换分组标签：更新轮询组，保证当前页数据持续刷新"""
        groups = self._current_tab_poll_groups()
        self.active_poll_groups = groups
        # 切换后清空"已读取"标记：新页面在真正读到数据前不显示任何值
        self._fresh_names.clear()
        self._fresh_addrs.clear()
        if self.is_polling and self.comm.is_connected:
            self.comm.update_poll_groups(groups)
        self._update_display()

    def _toggle_polling(self):
        if self.is_polling:
            self.comm.stop_polling()
            self.poll_btn.setText("开始监控")
            self.is_polling = False
        else:
            self.active_poll_groups = self._current_tab_poll_groups()
            self._fresh_names.clear()
            self._fresh_addrs.clear()
            self.comm.start_polling(self.active_poll_groups, self._poll_callback)
            self.poll_btn.setText("停止监控")
            self.is_polling = True

    def _poll_callback(self, group_index, response, timestamp, start_addr=None, quantity=None):
        if response is None:
            return

        if start_addr is None or quantity is None:
            groups = self.active_poll_groups or self.poll_groups
            if not groups:
                return
            start_addr, quantity = groups[group_index % len(groups)]
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
                    self._fresh_addrs.add(addr)

            decoded = parse_batch_response(response, start_addr, reg_defs)
            if decoded:
                self.parsed_data.update(decoded)
                self._fresh_names.update(decoded.keys())

        self._need_reg_refresh = True
        self.emitter.data_updated.emit()

    @staticmethod
    def _on_ctrl_radio_clicked(clicked_btn, btns_map):
        """组内互斥；再次点击已选按钮可取消，恢复空白（等价未选）"""
        if clicked_btn.isChecked():
            for btn in btns_map.values():
                if btn is not clicked_btn:
                    btn.setChecked(False)

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

    def _toggle_heartbeat(self):
        """启动/停止心跳写指令"""
        if not self.comm.is_connected:
            QMessageBox.warning(self, "警告", "请先连接串口")
            self.heartbeat_btn.setChecked(False)
            return

        if self.heartbeat_btn.isChecked():
            self.comm.start_heartbeat()
            self.heartbeat_btn.setText("■ 停止心跳")
            self.heartbeat_btn.setChecked(True)
        else:
            self.comm.stop_heartbeat()
            self.heartbeat_btn.setText("▶ 启动心跳")

    def _clear_log(self):
        self.register_values.clear()
        self._init_reg_display()
        self.comm.clear_log()
