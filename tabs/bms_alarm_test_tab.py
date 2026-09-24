"""
BMS报警测试Tab
集成故障码测试、测试报告两个子功能
改为左侧导航 + 右侧内容区，利用横向空间，不再垂直堆叠
"""

import logging
import atexit
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                             QPushButton, QFrame, QLabel, QSizePolicy,
                             QMessageBox, QApplication, QStyle, QStyleOptionButton, QStylePainter)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QIcon

from shared.style import COLORS, FONTS

logger = logging.getLogger(__name__)


class _NavButton(QPushButton):
    """导航按钮：强制文字左对齐"""
    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.textAlignment = Qt.AlignLeft | Qt.AlignVCenter
        painter.drawControl(QStyle.CE_PushButton, option)


_BTN_PRIMARY = (
    f"QPushButton {{ background-color: {COLORS['accent']}; color: white; "
    f"padding: 6px 18px; border: none; border-radius: 4px; font-weight: bold; }}"
    f"QPushButton:hover {{ background-color: {COLORS['accent_hover']}; }}"
    f"QPushButton:disabled {{ background-color: {COLORS['border']}; color: {COLORS['text_dim']}; }}"
)
_BTN_DANGER = (
    f"QPushButton {{ background-color: {COLORS['error']}; color: white; "
    f"padding: 6px 18px; border: none; border-radius: 4px; font-weight: bold; }}"
    f"QPushButton:hover {{ background-color: #b91c1c; }}"
    f"QPushButton:disabled {{ background-color: {COLORS['border']}; color: {COLORS['text_dim']}; }}"
)

_NAV_BTN_BASE = (
    f"QPushButton {{"
    f"background: {COLORS['bg_panel']};"
    f"color: {COLORS['text']};"
    f"border: 1px solid {COLORS['border']};"
    f"border-radius: 4px;"
    f"padding: 8px 8px 8px 24px;"
    f"font-weight: bold;"
    f"text-align: left;"
    f"}}"
    f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
    f"QPushButton:checked {{"
    f"background: {COLORS['accent']};"
    f"color: white;"
    f"border-color: {COLORS['accent']};"
    f"}}"
    f"QPushButton:checked:hover {{ background: {COLORS['accent_hover']}; }}"
    f"QPushButton:disabled {{ background: {COLORS['border']}; color: {COLORS['text_dim']}; }}"
)


class BmsAlarmTestTab(QWidget):
    """BMS报警测试主Tab，左侧导航 + 右侧内容区"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._can_manager = None
        self._settings = None
        self._fault_mapping = None
        self._test_logger = None
        self._backend_error = ""
        self._init_backend()
        self._init_ui()

    def _init_backend(self):
        """初始化后端对象（延迟导入，避免循环依赖）"""
        try:
            from bms_alarm_test.config.settings import get_global_settings, set_global_settings
            from bms_alarm_test.config.dbc_loader import DBCLoader
            from bms_alarm_test.config.fault_mapping import FaultMapping
            from bms_alarm_test.can.can_manager import CANManager
            from bms_alarm_test.logger.test_logger import TestLogger

            # 与 CANManager 共用同一份全局配置，避免 UI 修改不生效
            self._settings = get_global_settings()
            set_global_settings(self._settings)
            dbc_loader = DBCLoader()
            dbc_loader.load_inner_dbc(self._settings.get_inner_dbc_path())
            dbc_loader.load_outer_dbc(self._settings.get_outer_dbc_path())
            self._can_manager = CANManager(dbc_loader)
            self._fault_mapping = FaultMapping()

            # 初始化测试结果数据库
            self._test_logger = TestLogger("data/test_results.db")
            atexit.register(self._force_cleanup)
        except Exception as e:
            logger.error(f"报警测试后端初始化失败: {e}")
            import traceback
            traceback.print_exc()
            self._can_manager = None
            self._backend_error = str(e)

    def _force_cleanup(self):
        """强制清理CAN设备（atexit兜底）"""
        try:
            if self._can_manager:
                self._can_manager.disconnect()
        except Exception:
            pass

    def _init_ui(self):
        """初始化UI"""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # CAN 连接控制栏
        can_bar = self._create_can_control_bar()
        root.addWidget(can_bar)

        # 主体：左侧导航 + 右侧内容
        body = QHBoxLayout()
        body.setSpacing(8)

        # 左侧导航
        nav = self._create_nav()
        body.addWidget(nav, 0)

        # 右侧内容区
        self.stack = QStackedWidget()
        self._create_pages()
        body.addWidget(self.stack, 1)

        root.addLayout(body, 1)

    # ------------------------------------------------------------------
    # CAN 连接控制
    # ------------------------------------------------------------------
    def _create_can_control_bar(self) -> QWidget:
        """顶部 CAN 连接控制栏"""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"background: {COLORS['bg_panel']}; }}"
        )
        bar = QHBoxLayout(frame)
        bar.setContentsMargins(12, 8, 12, 8)
        bar.setSpacing(12)

        self.btn_connect = QPushButton("连接 CAN")
        self.btn_connect.setStyleSheet(_BTN_PRIMARY)
        self.btn_connect.setCursor(Qt.PointingHandCursor)
        self.btn_connect.clicked.connect(self._on_connect_clicked)

        self.btn_disconnect = QPushButton("断开 CAN")
        self.btn_disconnect.setStyleSheet(_BTN_DANGER)
        self.btn_disconnect.setCursor(Qt.PointingHandCursor)
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._on_disconnect_clicked)

        bar.addWidget(self.btn_connect)
        bar.addWidget(self.btn_disconnect)

        self.btn_config = QPushButton("CAN 配置")
        self.btn_config.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_input']}; color: {COLORS['text']}; "
            f"padding: 6px 14px; border: 1px solid {COLORS['border']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['bg_hover']}; }}"
        )
        self.btn_config.setCursor(Qt.PointingHandCursor)
        self.btn_config.clicked.connect(self._on_config_clicked)
        bar.addWidget(self.btn_config)

        self.btn_clear_all = QPushButton("一键清除所有故障")
        self.btn_clear_all.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['warning']}; color: white; "
            f"padding: 6px 14px; border: none; border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #d97706; }}"
            f"QPushButton:disabled {{ background-color: {COLORS['border']}; color: {COLORS['text_dim']}; }}"
        )
        self.btn_clear_all.setCursor(Qt.PointingHandCursor)
        self.btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        bar.addWidget(self.btn_clear_all)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        bar.addWidget(sep)

        self.can_status_label = QLabel("CAN: 未连接")
        self.can_status_label.setStyleSheet(
            f"color: {COLORS['error']}; font-weight: bold; font-size: 13px;"
        )
        bar.addWidget(self.can_status_label)

        bar.addStretch()

        self.tx_count_label = QLabel("TX: 0")
        self.rx_count_label = QLabel("RX: 0")
        for lbl in (self.tx_count_label, self.rx_count_label):
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-family: {FONTS['mono'][0]};")
            bar.addWidget(lbl)

        # TX/RX 定时刷新
        self._refresh_timer = __import__('PyQt5.QtCore', fromlist=['QTimer']).QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_counts)
        self._refresh_timer.start(500)

        return frame

    def _create_nav(self) -> QFrame:
        """左侧导航区"""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"background: {COLORS['bg_panel']}; }}"
        )
        nav = QVBoxLayout(frame)
        nav.setContentsMargins(8, 8, 8, 8)
        nav.setSpacing(6)

        self.nav_buttons = []
        pages = [
            ("故障码测试", "fault"),
            ("阈值测试", "threshold"),
            ("测试报告", "report"),
        ]
        for idx, (name, key) in enumerate(pages):
            btn = _NavButton(name)
            btn.setCheckable(True)
            btn.setStyleSheet(_NAV_BTN_BASE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(44)
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, k=key, i=idx: self._switch_page(k, i))
            nav.addWidget(btn)
            self.nav_buttons.append(btn)

        nav.addStretch(1)
        return frame

    def _switch_page(self, key: str, index: int):
        """切换右侧页面"""
        for btn in self.nav_buttons:
            btn.setChecked(False)
        self.nav_buttons[index].setChecked(True)

        mapping = {
            "fault": 0,
            "threshold": 1,
            "report": 2,
        }
        self.stack.setCurrentIndex(mapping.get(key, 0))

    # ------------------------------------------------------------------
    # 页面
    # ------------------------------------------------------------------
    def _create_pages(self):
        """创建子页面"""
        try:
            from bms_alarm_test.ui.fault_test_panel import FaultTestPanel
            from bms_alarm_test.ui.report_panel import ReportPanel
            from bms_alarm_test.ui.threshold_panel import ThresholdTestPanel
            from bms_alarm_test.config.pid_table import PIDTable

            # 故障码测试
            self.fault_panel = FaultTestPanel(fault_mapping=self._fault_mapping)
            if self._can_manager:
                from bms_alarm_test.engine.fault_engine import FaultTestEngine
                engine = FaultTestEngine(self._can_manager, self._fault_mapping)
                self.fault_panel.set_fault_engine(engine)
            if self._test_logger:
                self.fault_panel.set_test_logger(self._test_logger)
            self.stack.addWidget(self.fault_panel)

            # 阈值测试
            self.pid_table = PIDTable()
            pid_path = None
            if self._settings:
                try:
                    pid_path = self._settings.get_pid_excel_path()
                except Exception:
                    pid_path = None
            if pid_path:
                self.pid_table.load_from_excel(pid_path)
            self.threshold_panel = ThresholdTestPanel(pid_table=self.pid_table)
            if self._can_manager and self._fault_mapping:
                from bms_alarm_test.engine.threshold_engine import ThresholdTestEngine
                thr_engine = ThresholdTestEngine(self._can_manager, self.pid_table, self._fault_mapping)
                self.threshold_panel.set_threshold_engine(thr_engine)
            if self._test_logger:
                self.threshold_panel.set_test_logger(self._test_logger)
            self.stack.addWidget(self.threshold_panel)

            # 测试报告
            self.report_panel = ReportPanel(test_logger=self._test_logger)
            self.stack.addWidget(self.report_panel)
            self.fault_panel.test_completed.connect(lambda _results: self.report_panel.refresh_report())
            self.threshold_panel.test_completed.connect(lambda _results: self.report_panel.refresh_report())

            self.stack.setCurrentIndex(0)
        except Exception as e:
            logger.error(f"创建报警测试子页面失败: {e}")
            import traceback
            traceback.print_exc()
            error_label = QLabel(f"加载失败: {e}\n请检查依赖是否安装（python-can, cantools等）")
            error_label.setStyleSheet(f"color: {COLORS['error']}; padding: 20px;")
            self.stack.addWidget(error_label)

    # ------------------------------------------------------------------
    # CAN 计数刷新
    # ------------------------------------------------------------------
    def _refresh_counts(self):
        """从 CAN 管理器刷新 TX/RX 计数"""
        if not self._can_manager:
            return
        try:
            total_tx, total_rx = 0, 0
            for ch in (1, 2):
                status = self._can_manager.get_status(ch)
                if status:
                    counts = status.message_count
                    total_tx += counts.get("tx", 0)
                    total_rx += counts.get("rx", 0)
            self.tx_count_label.setText(f"TX: {total_tx}")
            self.rx_count_label.setText(f"RX: {total_rx}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CAN 控制
    # ------------------------------------------------------------------
    def _on_connect_clicked(self):
        """连接 CAN"""
        if not self._can_manager:
            detail = getattr(self, "_backend_error", "") or ""
            msg = (
                "后端初始化失败，无法连接 CAN。\n"
                "请检查以下事项：\n"
                "1. resources/ 目录是否存在\n"
                "2. DBC 和 Excel 文件是否完整\n"
                "3. 查看日志 bms_test.log 了解详细错误"
            )
            if detail:
                msg += f"\n\n详细错误:\n{detail}"
            QMessageBox.critical(self, "CAN 不可用", msg)
            return
        self.btn_connect.setEnabled(False)
        self.can_status_label.setText("CAN: 连接中...")
        self.can_status_label.setStyleSheet(
            f"color: {COLORS['warning']}; font-weight: bold; font-size: 13px;"
        )
        from PyQt5.QtCore import QThread, pyqtSignal

        class _ConnectWorker(QThread):
            finished = pyqtSignal(bool, str)

            def __init__(self, mgr):
                super().__init__()
                self.mgr = mgr

            def run(self):
                try:
                    ok = self.mgr.connect()
                    self.finished.emit(ok, "" if ok else "连接失败")
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._connect_worker = _ConnectWorker(self._can_manager)
        self._connect_worker.finished.connect(self._on_connect_finished)
        self._connect_worker.start()

    def _on_connect_finished(self, ok, err_msg):
        """CAN 连接完成回调"""
        if not ok:
            self.can_status_label.setText("CAN: 连接失败")
            self.can_status_label.setStyleSheet(
                f"color: {COLORS['error']}; font-weight: bold; font-size: 13px;"
            )
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            if err_msg:
                logger.error(f"CAN 连接失败: {err_msg}")
            return

        # 检查各通道实际连接状态
        failed_channels = []
        real_channels = []
        for ch in [1, 2]:
            status = self._can_manager.get_status(ch)
            if status and status.state.name == "CONNECTED":
                real_channels.append(ch)
            else:
                failed_channels.append(ch)

        if not real_channels:
            # 全部失败
            err_msgs = []
            for ch in failed_channels:
                status = self._can_manager.get_status(ch)
                err = status.last_error if status and status.last_error else "未知错误"
                err_msgs.append(f"CH{ch}: {err}")
            self.can_status_label.setText(f"CAN: 连接失败 — {'; '.join(err_msgs)}")
            self.can_status_label.setStyleSheet(
                f"color: {COLORS['error']}; font-weight: bold; font-size: 13px;"
            )
            logger.error(f"CAN连接失败: {'; '.join(err_msgs)}")
        else:
            ch_str = ",".join(f"CH{ch}" for ch in real_channels)
            self.can_status_label.setText(f"CAN: 已连接 ({ch_str})")
            self.can_status_label.setStyleSheet(
                f"color: {COLORS['success']}; font-weight: bold; font-size: 13px;"
            )
            if failed_channels:
                for ch in failed_channels:
                    status = self._can_manager.get_status(ch)
                    err = status.last_error if status and status.last_error else "未知错误"
                    logger.warning(f"CH{ch} 连接失败: {err}")
            role_desc = ""
            try:
                role_desc = self._can_manager.describe_channel_roles()
            except Exception:
                pass
            logger.info(f"CAN 硬件连接成功: {ch_str}" + (f" | {role_desc}" if role_desc else ""))
            if role_desc:
                logger.info(
                    "接线核对: 故障注入/清故障请接【对内通道】；"
                    "若发送报 VCI_Transmit 失败，优先检查对内线是否接到了对外口。\n"
                    f"当前: {role_desc}"
                )

        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)

    def _on_disconnect_clicked(self):
        """断开 CAN"""
        if self._can_manager:
            self._can_manager.disconnect()
        self.can_status_label.setText("CAN: 未连接")
        self.can_status_label.setStyleSheet(
            f"color: {COLORS['error']}; font-weight: bold; font-size: 13px;"
        )
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        logger.info("CAN 已断开")

    def _on_clear_all_clicked(self):
        """一键清除所有故障"""
        logger.info("[一键清除] 按钮被点击")
        if not self._can_manager or not self._can_manager.is_connected():
            logger.info("[一键清除] CAN未连接，退出")
            QMessageBox.warning(self, "提示", "请先连接 CAN")
            return

        reply = QMessageBox.question(
            self, "确认清除",
            f"将清除目标地址 0x{self.fault_panel.nbcmu_spin.value():X} 的所有故障（1-96）\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            logger.info("[一键清除] 用户取消")
            return

        self.btn_clear_all.setEnabled(False)
        self.btn_clear_all.setText("清除中...")
        QApplication.processEvents()

        try:
            if self.fault_panel.fault_engine:
                addr = self.fault_panel.nbcmu_spin.value()
                logger.info(f"[一键清除] 目标地址=0x{addr:X}")
                ok = self.fault_panel.fault_engine.clear_all_faults(domain=addr)
                logger.info(f"[一键清除] 结果: {ok}")
                msg = "所有故障已清除" if ok else "部分故障清除失败，请查看日志"
                QMessageBox.information(self, "完成", msg)
            else:
                logger.warning("[一键清除] fault_engine 为 None")
                QMessageBox.warning(self, "错误", "故障引擎未初始化")
        except Exception as e:
            logger.error(f"[一键清除] 异常: {e}")
            QMessageBox.critical(self, "错误", f"清除故障异常: {e}")
        finally:
            self.btn_clear_all.setEnabled(True)
            self.btn_clear_all.setText("一键清除所有故障")

    def _on_config_clicked(self):
        """打开CAN配置对话框"""
        from PyQt5.QtWidgets import QDialog, QGridLayout, QComboBox, QLabel, QPushButton, QGroupBox

        dlg = QDialog(self)
        dlg.setWindowTitle("CAN盒通道配置")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)

        # === 通道角色选择 ===
        grp_role = QGroupBox("通道角色分配")
        gr = QGridLayout(grp_role)
        gr.addWidget(QLabel("对内通道（发送故障注入）:"), 0, 0)
        inner_combo = QComboBox()
        inner_combo.addItems(["CH1", "CH2"])
        gr.addWidget(inner_combo, 0, 1)
        gr.addWidget(QLabel("对外通道（接收BMS响应）:"), 1, 0)
        outer_combo = QComboBox()
        outer_combo.addItems(["CH1", "CH2"])
        gr.addWidget(outer_combo, 1, 1)

        # 初始化：读取当前配置
        if self._settings:
            inner_ch = self._settings.get_inner_channel()
            outer_ch = self._settings.get_outer_channel()
            inner_combo.setCurrentIndex(inner_ch - 1)
            outer_combo.setCurrentIndex(outer_ch - 1)

        def on_role_changed(idx):
            """角色切换时联动：自动将另一个通道设为相反角色"""
            sender = dlg.sender()
            if sender == inner_combo:
                other_idx = 1 - idx
                outer_combo.setCurrentIndex(other_idx)
            else:
                other_idx = 1 - idx
                inner_combo.setCurrentIndex(other_idx)

        inner_combo.currentIndexChanged.connect(on_role_changed)
        outer_combo.currentIndexChanged.connect(on_role_changed)
        lay.addWidget(grp_role)

        # === 各通道波特率 ===
        grp1 = QGroupBox("CH1 波特率")
        g1 = QGridLayout(grp1)
        g1.addWidget(QLabel("波特率:"), 0, 0)
        ch1_baud = QComboBox()
        ch1_baud.addItems(["125k", "250k", "500k", "1M"])
        ch1_baud.setCurrentText("500k")
        g1.addWidget(ch1_baud, 0, 1)
        lay.addWidget(grp1)

        grp2 = QGroupBox("CH2 波特率")
        g2 = QGridLayout(grp2)
        g2.addWidget(QLabel("波特率:"), 0, 0)
        ch2_baud = QComboBox()
        ch2_baud.addItems(["125k", "250k", "500k", "1M"])
        ch2_baud.setCurrentText("250k")
        g2.addWidget(ch2_baud, 0, 1)
        lay.addWidget(grp2)

        # 初始化波特率：从当前配置读取
        if self._settings:
            cfg1 = self._settings.get_can_config(1)
            cfg2 = self._settings.get_can_config(2)
            if cfg1:
                baud_str = str(cfg1.baud_rate.value // 1000) + "k" if cfg1.baud_rate.value < 1000000 else "1M"
                if ch1_baud.findText(baud_str) >= 0:
                    ch1_baud.setCurrentText(baud_str)
            if cfg2:
                baud_str = str(cfg2.baud_rate.value // 1000) + "k" if cfg2.baud_rate.value < 1000000 else "1M"
                if ch2_baud.findText(baud_str) >= 0:
                    ch2_baud.setCurrentText(baud_str)

        def apply_config():
            from bms_alarm_test.config.settings import BaudRate
            br_map = {"125k": BaudRate.BAUD_125K, "250k": BaudRate.BAUD_250K,
                      "500k": BaudRate.BAUD_500K, "1M": BaudRate.BAUD_1M}
            br1 = br_map[ch1_baud.currentText()]
            br2 = br_map[ch2_baud.currentText()]
            if self._settings:
                # 保存通道角色
                inner_ch = inner_combo.currentIndex() + 1
                outer_ch = outer_combo.currentIndex() + 1
                self._settings.set_channel_roles(inner_ch, outer_ch)
                # 保存波特率
                self._settings.set_can_baud_rate(1, br1)
                self._settings.set_can_baud_rate(2, br2)
                # 落盘，避免重启后丢失
                self._settings.save()
                logger.info(
                    f"CAN配置已更新: 对内=CH{inner_ch}@{br1}, 对外=CH{outer_ch}@{br2}"
                )
                # 已连接时用新配置重连，否则硬件仍是旧参数
                if self._can_manager and self._can_manager.is_connected():
                    logger.info("检测到CAN已连接，使用新配置重连...")
                    self._can_manager.reconnect()
            dlg.accept()

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(apply_config)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        dlg.exec_()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def cleanup(self):
        """清理资源"""
        try:
            if getattr(self, "threshold_panel", None):
                self.threshold_panel.cleanup()
        except Exception as e:
            logger.error(f"清理阈值测试面板失败: {e}")
        try:
            if self._can_manager:
                self._can_manager.disconnect()
        except Exception as e:
            logger.error(f"清理报警测试资源失败: {e}")
