"""
故障码映射表加载
包含所有86个有效故障（不含10个预留）的映射信息
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class FaultDomain(Enum):
    """故障所属域"""
    NBCMU = "NBCMU"
    SBCMU = "SBCMU"
    BOTH = "BOTH"  # 共有故障，需要在两个域各测一次


@dataclass
class Fault:
    """故障数据模型"""
    code: int                   # 故障码 1-96
    name: str                   # 故障名
    level: int                  # 等级 1/2/3
    domain: FaultDomain         # 所属域
    
    # 对内验证（CAN1）
    sys_fail_sta_expected: int  # SysFailSta期望值
    err_tab_expected: int       # ErrTab期望值
    inner_signal: Optional[str]  # 内specific信号名（None表示无信号）
    inner_expected: Optional[int]  # 内specific期望值
    
    # 对外验证（CAN2）
    outer_signal: Optional[str]  # 外specific信号名（None表示对外跳过，支持{idx}占位符）
    outer_expected: Optional[int]  # 外specific期望值
    outer_warning_expected: Optional[int]  # BMS_NBCMU0x_Warning期望值
    
    # 分类信息
    category: str               # 故障类别：电压/电流/绝缘/温度/SBCMU/继电器/通讯/其他
    
    def __post_init__(self):
        """数据验证"""
        if not 1 <= self.code <= 96:
            raise ValueError(f"故障码必须在1-96范围内: {self.code}")
        if self.level not in (1, 2, 3):
            raise ValueError(f"故障等级必须是1/2/3: {self.level}")
        if self.sys_fail_sta_expected not in (0, 1, 2, 3):
            raise ValueError(f"SysFailSta期望值必须是0-3: {self.sys_fail_sta_expected}")
        if self.err_tab_expected != self.code:
            raise ValueError(f"ErrTab期望值必须等于故障码: {self.err_tab_expected} != {self.code}")
            
    @property
    def fault_level(self) -> int:
        """故障等级（向后兼容别名，映射level）"""
        return self.level
    
    def has_inner_specific(self) -> bool:
        """是否有内specific信号"""
        return self.inner_signal is not None and self.inner_expected is not None
        
    def has_outer_mapping(self) -> bool:
        """是否有对外映射（需要验证CAN2）"""
        return (self.outer_signal is not None and self.outer_expected is not None) or \
               self.outer_warning_expected is not None
        
    def is_skip_outer(self) -> bool:
        """是否对外跳过（仅验证CAN1）"""
        return not self.has_outer_mapping()
        
    def is_reserved(self) -> bool:
        """是否为预留故障（跳过）"""
        return self.code in RESERVED_FAULT_CODES
        
    def get_expected_values(self) -> Dict[str, Optional[int]]:
        """获取所有期望值"""
        return {
            "sys_fail_sta": self.sys_fail_sta_expected,
            "err_tab": self.err_tab_expected,
            "inner_specific": self.inner_expected,
            "outer_specific": self.outer_expected,
            "outer_warning": self.outer_warning_expected,
        }


# 预留故障码（测试中跳过）
RESERVED_FAULT_CODES = {48, 53, 54, 58, 66, 67, 69, 70, 73, 77, 96}

# 共有故障码（需要在NBCMU和SBCMU两个域各测一次）
SHARED_FAULT_CODES = {57, 68, 71, 81}

# 继电器故障码（特殊期望值：1=开路，2=粘连，不是故障等级）
RELAY_FAULT_CODES = {59, 60, 62, 63}


class FaultMapping:
    """故障映射表管理器"""
    
    def __init__(self):
        self._faults_by_code: Dict[int, Fault] = {}
        self._faults_by_domain: Dict[FaultDomain, List[Fault]] = {
            FaultDomain.NBCMU: [],
            FaultDomain.SBCMU: [],
            FaultDomain.BOTH: []
        }
        self._faults_by_category: Dict[str, List[Fault]] = {}
        self._all_faults_list: List[Fault] = []
        self._load_all_faults()
        
    def _load_all_faults(self):
        """加载所有故障映射数据"""
        # 电压类故障 (1-21, 80, 82)
        voltage_faults = [
            # 单体过压1-3级
            Fault(1, "单体过压1级", 3, FaultDomain.NBCMU, 3, 1, "NBCMU01_CellVolt_HighWarning", 1, None, None, 3, "电压"),
            Fault(2, "单体过压2级", 3, FaultDomain.NBCMU, 3, 2, "NBCMU01_CellVolt_HighWarning", 2, None, None, 3, "电压"),
            Fault(3, "单体过压3级", 3, FaultDomain.NBCMU, 3, 3, "NBCMU01_CellVolt_HighWarning", 3, None, None, 3, "电压"),
            # 单体欠压1-3级
            Fault(4, "单体欠压1级", 2, FaultDomain.NBCMU, 2, 4, "NBCMU01_CellVolt_LowWarning", 1, None, None, 2, "电压"),
            Fault(5, "单体欠压2级", 2, FaultDomain.NBCMU, 2, 5, "NBCMU01_CellVolt_LowWarning", 2, None, None, 2, "电压"),
            Fault(6, "单体欠压3级", 3, FaultDomain.NBCMU, 3, 6, "NBCMU01_CellVolt_LowWarning", 3, None, None, 3, "电压"),
            # 压差过大1-3级
            Fault(7, "压差过大1级", 1, FaultDomain.NBCMU, 1, 7, "NBCMU01_CellVoltDiff_Warning", 1, "BMS_CellVoltDiff_Warning", 1, 1, "电压"),
            Fault(8, "压差过大2级", 2, FaultDomain.NBCMU, 2, 8, "NBCMU01_CellVoltDiff_Warning", 2, "BMS_CellVoltDiff_Warning", 2, 2, "电压"),
            Fault(9, "压差过大3级", 3, FaultDomain.NBCMU, 3, 9, "NBCMU01_CellVoltDiff_Warning", 3, "BMS_CellVoltDiff_Warning", 3, 3, "电压"),
            # 电池包总压过压1-3级
            Fault(10, "电池包总压过压1级", 3, FaultDomain.NBCMU, 3, 10, "NBCMU01_SumVolt_HighWarning", 1, None, None, 3, "电压"),
            Fault(11, "电池包总压过压2级", 3, FaultDomain.NBCMU, 3, 11, "NBCMU01_SumVolt_HighWarning", 2, None, None, 3, "电压"),
            Fault(12, "电池包总压过压3级", 3, FaultDomain.NBCMU, 3, 12, "NBCMU01_SumVolt_HighWarning", 3, None, None, 3, "电压"),
            # 电池包总压欠压1-3级
            Fault(13, "电池包总压欠压1级", 2, FaultDomain.NBCMU, 2, 13, "NBCMU01_SumVolt_LowWarning", 1, None, None, 2, "电压"),
            Fault(14, "电池包总压欠压2级", 3, FaultDomain.NBCMU, 3, 14, "NBCMU01_SumVolt_LowWarning", 2, None, None, 3, "电压"),
            Fault(15, "电池包总压欠压3级", 3, FaultDomain.NBCMU, 3, 15, "NBCMU01_SumVolt_LowWarning", 3, None, None, 3, "电压"),
            # 簇总压过压1-3级
            Fault(16, "簇总压过压1级", 3, FaultDomain.NBCMU, 3, 16, "NBCMU01_BattVolt_HighWarning", 1, "BMS_NBCMU01_BattVoltHighWarning", 1, 3, "电压"),
            Fault(17, "簇总压过压2级", 3, FaultDomain.NBCMU, 3, 17, "NBCMU01_BattVolt_HighWarning", 2, "BMS_NBCMU01_BattVoltHighWarning", 2, 3, "电压"),
            Fault(18, "簇总压过压3级", 3, FaultDomain.NBCMU, 3, 18, "NBCMU01_BattVolt_HighWarning", 3, "BMS_NBCMU01_BattVoltHighWarning", 3, 3, "电压"),
            # 簇总压欠压1-3级
            Fault(19, "簇总压欠压1级", 2, FaultDomain.NBCMU, 2, 19, "NBCMU01_BattVolt_LowWarning", 1, "BMS_NBCMU01_BattVolt_LowWarning", 1, 2, "电压"),
            Fault(20, "簇总压欠压2级", 3, FaultDomain.NBCMU, 3, 20, "NBCMU01_BattVolt_LowWarning", 2, "BMS_NBCMU01_BattVolt_LowWarning", 2, 3, "电压"),
            Fault(21, "簇总压欠压3级", 3, FaultDomain.NBCMU, 3, 21, "NBCMU01_BattVolt_LowWarning", 3, "BMS_NBCMU01_BattVolt_LowWarning", 3, 3, "电压"),
            # 电压采集线故障
            Fault(80, "电压采集线故障", 3, FaultDomain.NBCMU, 3, 80, "NBCMU01_CellVoltOpen", 1, "BMS_NBCMU01_VoltDetectFault", 1, 3, "电压"),
            # 电池包一致性故障
            Fault(82, "电池包一致性故障", 3, FaultDomain.NBCMU, 3, 82, "NBCMU01_BattVoltDiff_Warning", 1, None, None, 3, "电压"),
        ]
        
        # 电流类故障 (22-27, 96)
        current_faults = [
            Fault(22, "簇放电过流1级", 1, FaultDomain.NBCMU, 1, 22, "NBCMU01_DischrgCurr_OverWarning", 1, "BMS_DischrgCurr_OverWarning", 1, 1, "电流"),
            Fault(23, "簇放电过流2级", 2, FaultDomain.NBCMU, 2, 23, "NBCMU01_DischrgCurr_OverWarning", 2, "BMS_DischrgCurr_OverWarning", 2, 2, "电流"),
            Fault(24, "簇放电过流3级", 3, FaultDomain.NBCMU, 3, 24, "NBCMU01_DischrgCurr_OverWarning", 3, "BMS_DischrgCurr_OverWarning", 3, 3, "电流"),
            Fault(25, "簇充电过流1级", 1, FaultDomain.NBCMU, 1, 25, "NBCMU01_ChrgCurr_OverWarning", 1, "BMS_ChrgCurr_OverWarning", 1, 1, "电流"),
            Fault(26, "簇充电过流2级", 2, FaultDomain.NBCMU, 2, 26, "NBCMU01_ChrgCurr_OverWarning", 2, "BMS_ChrgCurr_OverWarning", 2, 2, "电流"),
            Fault(27, "簇充电过流3级", 3, FaultDomain.NBCMU, 3, 27, "NBCMU01_ChrgCurr_OverWarning", 3, "BMS_ChrgCurr_OverWarning", 3, 3, "电流"),
            Fault(96, "电池簇间环流过大", 3, FaultDomain.NBCMU, 3, 96, "NBCMU01_CurrentLoop_HighWarning", 1, None, None, 3, "电流"),
        ]
        
        # 绝缘类故障 (28-30)
        insulation_faults = [
            Fault(28, "高压绝缘故障1级", 1, FaultDomain.NBCMU, 1, 28, "NBCMU01_InsulationWarning", 1, "BMS_InsulationWarning", 1, 1, "绝缘"),
            Fault(29, "高压绝缘故障2级", 2, FaultDomain.NBCMU, 2, 29, "NBCMU01_InsulationWarning", 2, "BMS_InsulationWarning", 2, 2, "绝缘"),
            Fault(30, "高压绝缘故障3级", 3, FaultDomain.NBCMU, 3, 30, "NBCMU01_InsulationWarning", 3, "BMS_InsulationWarning", 3, 3, "绝缘"),
        ]
        
        # 温度类故障 (31-45, 74-76, 78-79, 81)
        temperature_faults = [
            # 充电温度过高1-3级
            Fault(31, "充电温度过高1级", 1, FaultDomain.NBCMU, 1, 31, "NBCMU01_ChrgTemp_HighWarning", 1, "BMS_NBCMU01_Temp_HighWarning", 1, 1, "温度"),
            Fault(32, "充电温度过高2级", 2, FaultDomain.NBCMU, 2, 32, "NBCMU01_ChrgTemp_HighWarning", 2, "BMS_NBCMU01_Temp_HighWarning", 2, 2, "温度"),
            Fault(33, "充电温度过高3级", 3, FaultDomain.NBCMU, 3, 33, "NBCMU01_ChrgTemp_HighWarning", 3, "BMS_NBCMU01_Temp_HighWarning", 3, 3, "温度"),
            # 充电温度过低1-3级
            Fault(34, "充电温度过低1级", 2, FaultDomain.NBCMU, 2, 34, "NBCMU01_ChrgTemp_LowWarning", 1, None, None, 2, "温度"),
            Fault(35, "充电温度过低2级", 2, FaultDomain.NBCMU, 2, 35, "NBCMU01_ChrgTemp_LowWarning", 2, None, None, 2, "温度"),
            Fault(36, "充电温度过低3级", 3, FaultDomain.NBCMU, 3, 36, "NBCMU01_ChrgTemp_LowWarning", 3, None, None, 3, "温度"),
            # 放电温度过高1-3级
            Fault(37, "放电温度过高1级", 1, FaultDomain.NBCMU, 1, 37, "NBCMU01_DischrgTemp_HighWarning", 1, "BMS_NBCMU01_Temp_HighWarning", 1, 1, "温度"),
            Fault(38, "放电温度过高2级", 2, FaultDomain.NBCMU, 2, 38, "NBCMU01_DischrgTemp_HighWarning", 2, "BMS_NBCMU01_Temp_HighWarning", 2, 2, "温度"),
            Fault(39, "放电温度过高3级", 3, FaultDomain.NBCMU, 3, 39, "NBCMU01_DischrgTemp_HighWarning", 3, "BMS_NBCMU01_Temp_HighWarning", 3, 3, "温度"),
            # 放电温度过低1-3级
            Fault(40, "放电温度过低1级", 2, FaultDomain.NBCMU, 2, 40, "NBCMU01_DischrgTemp_LowWarning", 1, None, None, 2, "温度"),
            Fault(41, "放电温度过低2级", 2, FaultDomain.NBCMU, 2, 41, "NBCMU01_DischrgTemp_LowWarning", 2, None, None, 2, "温度"),
            Fault(42, "放电温度过低3级", 3, FaultDomain.NBCMU, 3, 42, "NBCMU01_DischrgTemp_LowWarning", 3, None, None, 3, "温度"),
            # 温差过大1-3级
            Fault(43, "温差过大1级", 1, FaultDomain.NBCMU, 1, 43, "NBCMU01_TempDiff_Warning", 1, None, None, 1, "温度"),
            Fault(44, "温差过大2级", 1, FaultDomain.NBCMU, 1, 44, "NBCMU01_TempDiff_Warning", 2, None, None, 1, "温度"),
            Fault(45, "温差过大3级", 3, FaultDomain.NBCMU, 3, 45, "NBCMU01_TempDiff_Warning", 3, None, None, 3, "温度"),
            # 环境温度过高1-3级
            Fault(74, "环境温度过高1级", 1, FaultDomain.NBCMU, 1, 74, "NBCMU01_AmbientTemp_HighWarning", 1, None, None, 1, "温度"),
            Fault(75, "环境温度过高2级", 2, FaultDomain.NBCMU, 2, 75, "NBCMU01_AmbientTemp_HighWarning", 2, None, None, 2, "温度"),
            Fault(76, "环境温度过高3级", 3, FaultDomain.NBCMU, 3, 76, "NBCMU01_AmbientTemp_HighWarning", 3, None, None, 3, "温度"),
            # 环境温度过低2-3级
            Fault(78, "环境温度过低2级", 2, FaultDomain.NBCMU, 2, 78, "NBCMU01_AmbientTemp_LowWarning", 2, None, None, 2, "温度"),
            Fault(79, "环境温度过低3级", 3, FaultDomain.NBCMU, 3, 79, "NBCMU01_AmbientTemp_LowWarning", 3, None, None, 3, "温度"),
            # 温度采集线故障（共有故障，NBCMU版本）
            Fault(81, "温度采集线故障[NBCMU]", 3, FaultDomain.NBCMU, 3, 81, "NBCMU01_CellTempOpen", 1, "BMS_NBCMU{idx}_TempDetectFault", 1, 3, "温度"),
            Fault(81, "温度采集线故障[SBCMU]", 3, FaultDomain.SBCMU, 3, 81, "SBCMU01_CellTempOpen", 1, "BMS_SBCMU{idx}_TempDetectFault", 1, None, "温度"),
        ]
        
        # SBCMU域故障 (91-95)
        sbcmu_faults = [
            Fault(91, "S板过高温(单体)", 3, FaultDomain.SBCMU, 3, 91, "SBCMU01_Temp_HighWarning", 1, "BMS_SBCMU{idx}_TempOverFault", 1, None, "SBCMU"),
            Fault(92, "S板过高温(环境)", 3, FaultDomain.SBCMU, 3, 92, "SBCMU01_AmbientTemp_HighWarning", 1, "BMS_SBCMU{idx}_AmbientTemp_HighWarning", 1, None, "SBCMU"),
            Fault(93, "充电插座过温1级", 2, FaultDomain.SBCMU, 2, 93, "SBCMU01_SocketTemp_HighWarning", 1, None, None, 2, "SBCMU"),
            Fault(94, "充电插座过温2级", 3, FaultDomain.SBCMU, 3, 94, "SBCMU01_SocketTemp_HighWarning", 2, None, None, 3, "SBCMU"),
            Fault(95, "充电故障", 3, FaultDomain.NBCMU, 3, 95, "NBCMU01_ChrgFault", 1, "BMS_NBCMU01_ChrgFault", 1, 3, "继电器"),
        ]
        
        # 继电器/接触器类故障 (46-47, 59-63)
        relay_faults = [
            Fault(46, "加热继电器回路开路", 1, FaultDomain.NBCMU, 1, 46, "NBCMU01_ContactorHeat_Fault", 1, "BMS_NBCMU{idx}_Contactor_Fault", 1, 1, "继电器"),
            Fault(47, "加热继电器粘连", 1, FaultDomain.NBCMU, 1, 47, "NBCMU01_ContactorHeat_Fault", 2, "BMS_NBCMU{idx}_Contactor_Fault", 2, 1, "继电器"),
            # 继电器故障特殊期望值：1=开路，2=粘连，不是故障等级
            Fault(59, "主正继电器开路", 3, FaultDomain.NBCMU, 3, 59, "NBCMU01_ContactorPosi_Fault", 1, "BMS_NBCMU{idx}_Contactor_Fault", 1, 3, "继电器"),
            Fault(60, "主正继电器粘连", 3, FaultDomain.NBCMU, 3, 60, "NBCMU01_ContactorPosi_Fault", 2, "BMS_NBCMU{idx}_Contactor_Fault", 2, 3, "继电器"),
            Fault(62, "主负继电器开路", 3, FaultDomain.NBCMU, 3, 62, "NBCMU01_ContactorNega_Fault", 1, "BMS_NBCMU{idx}_Contactor_Fault", 1, 3, "继电器"),
            Fault(63, "主负继电器粘连", 3, FaultDomain.NBCMU, 3, 63, "NBCMU01_ContactorNega_Fault", 2, "BMS_NBCMU{idx}_Contactor_Fault", 2, 3, "继电器"),
        ]
        
        # 通讯类故障 (57, 72, 83-84, 87-88)
        communication_faults = [
            # 与三级BICU通讯失败（共有故障，NBCMU版本）
            Fault(57, "与三级BICU通讯失败[NBCMU]", 3, FaultDomain.NBCMU, 3, 57, "NBCMU01_NBICU_TimeOut", 1, None, None, 3, "通讯"),
            Fault(57, "与三级BICU通讯失败[SBCMU]", 3, FaultDomain.SBCMU, 3, 57, "SBCMU01_SBICU_TimeOut", 1, None, None, None, "通讯"),
            Fault(72, "与电流传感器通讯失败", 3, FaultDomain.NBCMU, 3, 72, "NBCMU01_CurrSensor_TimeOut", 1, None, None, 3, "通讯"),
            Fault(83, "与TMS通讯失败", 1, FaultDomain.NBCMU, 1, 83, "NBCMU01_TMS_TimeOut", 1, None, None, 1, "通讯"),
            Fault(84, "与PCS通讯失败", 1, FaultDomain.NBCMU, 1, 84, "NBCMU01_PCS_TimeOut", 1, None, None, 1, "通讯"),
            Fault(87, "与EMS通讯失败", 1, FaultDomain.NBCMU, 1, 87, "NBCMU01_EMS_TimeOut", 1, "BMS_EMS_TimeOut", 1, 1, "通讯"),
            Fault(88, "与SBCMU通讯失败", 1, FaultDomain.NBCMU, 1, 88, "NBCMU01_SBCMU01_TimeOut", 1, None, None, 1, "通讯"),
        ]
        
        # 其他故障 (49-52, 55-56, 68, 71, 85-86, 89-90)
        other_faults = [
            Fault(49, "SOC过低1级", 1, FaultDomain.NBCMU, 1, 49, "NBCMU01_SOC_LowWarning", 1, "BMS_NBCMU01_SOC_LowWarning", 1, 1, "其他"),
            Fault(50, "SOC过低2级", 1, FaultDomain.NBCMU, 1, 50, "NBCMU01_SOC_LowWarning", 2, "BMS_NBCMU01_SOC_LowWarning", 2, 1, "其他"),
            Fault(51, "SOC过低3级", 1, FaultDomain.NBCMU, 1, 51, "NBCMU01_SOC_LowWarning", 3, "BMS_NBCMU01_SOC_LowWarning", 3, 1, "其他"),
            Fault(52, "SOH过低1级", 1, FaultDomain.NBCMU, 1, 52, "NBCMU01_SOH_LowWarning", 1, None, None, 1, "其他"),
            Fault(55, "簇高压互锁故障", 3, FaultDomain.NBCMU, 3, 55, "NBCMU01_HVIL_Fault", 1, "BMS_HVIL_Fault", 1, 3, "其他"),
            Fault(56, "熔断器故障", 3, FaultDomain.NBCMU, 3, 56, "NBCMU01_Fuse_Fault", 1, None, None, 3, "其他"),
            # 供电电压过高3级（共有故障，NBCMU版本）
            Fault(68, "供电电压过高3级[NBCMU]", 3, FaultDomain.NBCMU, 3, 68, "NBCMU01_SupplyVolt_HighWarning", 3, "BMS_NBCMU{idx}_SupplyVoltFault", 1, 3, "其他"),
            # 供电电压过低3级（共有故障，NBCMU版本）
            Fault(71, "供电电压过低3级[NBCMU]", 3, FaultDomain.NBCMU, 3, 71, "NBCMU01_SupplyVolt_LowWarning", 3, "BMS_NBCMU{idx}_SupplyVoltFault", 1, 3, "其他"),
            # 供电电压过高3级（SBCMU版本）
            Fault(68, "供电电压过高3级[SBCMU]", 3, FaultDomain.SBCMU, 3, 68, "SBCMU01_SupplyVolt_HighWarning", 3, "BMS_SBCMU{idx}_SupplyVoltFault", 1, None, "其他"),
            # 供电电压过低3级（SBCMU版本）
            Fault(71, "供电电压过低3级[SBCMU]", 3, FaultDomain.SBCMU, 3, 71, "SBCMU01_SupplyVolt_LowWarning", 3, None, None, None, "其他"),
            Fault(85, "初始化故障", 3, FaultDomain.NBCMU, 3, 85, "NBCMU01_InitialFault", 1, None, None, 3, "其他"),
            Fault(86, "急停故障", 3, FaultDomain.NBCMU, 3, 86, "NBCMU01_EmergyShutdown_Fault", 1, "BMS_EmergyShutdown_Fault", 1, 3, "其他"),
            Fault(89, "保护功能故障", 3, FaultDomain.NBCMU, 3, 89, "NBCMU01_ProtectFault", 1, "BMS_NBCMU01_ProtectFault", 1, 3, "其他"),
            Fault(90, "热管理故障", 1, FaultDomain.NBCMU, 1, 90, "NBCMU01_ThermalManagement_Fault", 1, None, None, 1, "其他"),
        ]
        
        # 合并所有故障，并按故障码升序排序
        all_faults = sorted(
            voltage_faults + current_faults + insulation_faults + temperature_faults +
            sbcmu_faults + relay_faults + communication_faults + other_faults,
            key=lambda f: f.code
        )
        
        # 构建索引
        for fault in all_faults:
            self._all_faults_list.append(fault)
            self._faults_by_code[fault.code] = fault
            self._faults_by_domain[fault.domain].append(fault)
            
            if fault.category not in self._faults_by_category:
                self._faults_by_category[fault.category] = []
            self._faults_by_category[fault.category].append(fault)
            
        logger.info(f"加载了 {len(self._faults_by_code)} 个故障映射, 共 {len(self._all_faults_list)} 条")
        
    def get_fault(self, code: int, domain: Optional[FaultDomain] = None) -> Optional[Fault]:
        """根据故障码获取故障，可选指定域（用于同码多版本如57-NBCMU/57-SBCMU）"""
        if domain is not None:
            for fault in self._all_faults_list:
                if fault.code == code and fault.domain == domain:
                    return fault
            return None
        return self._faults_by_code.get(code)
    
    def get_faults_by_codes(self, codes: List) -> List[Fault]:
        """根据故障码列表获取故障（支持int或字符串格式，如'1'或'0x01'或'57:NBCMU'）"""
        faults = []
        seen_ids = set()
        for code in codes:
            try:
                if isinstance(code, str):
                    # 支持 "code:domain" 格式，如同码多版本区分
                    if ":" in code:
                        code_str, domain_str = code.split(":", 1)
                        code_int = int(code_str, 16) if code_str.startswith("0x") else int(code_str)
                        try:
                            domain = FaultDomain(domain_str.upper())
                        except ValueError:
                            domain = None
                        if domain:
                            fault = self.get_fault(code_int, domain)
                            if fault and id(fault) not in seen_ids:
                                faults.append(fault)
                                seen_ids.add(id(fault))
                        else:
                            # domain不匹配时，返回所有匹配的版本
                            for fault in self._all_faults_list:
                                if fault.code == code_int and id(fault) not in seen_ids:
                                    faults.append(fault)
                                    seen_ids.add(id(fault))
                        continue
                    else:
                        code_int = int(code, 16) if code.startswith("0x") else int(code)
                else:
                    code_int = int(code)
            except (ValueError, TypeError):
                continue
            # 返回所有匹配的故障（包括同码多版本，如57-NBCMU/57-SBCMU）
            for fault in self._all_faults_list:
                if fault.code == code_int and id(fault) not in seen_ids:
                    faults.append(fault)
                    seen_ids.add(id(fault))
        return faults
        
    def get_faults_by_domain(self, domain: FaultDomain) -> List[Fault]:
        """获取指定域的所有故障"""
        return self._faults_by_domain.get(domain, [])
        
    def get_faults_by_category(self, category: str) -> List[Fault]:
        """获取指定类别的所有故障"""
        return self._faults_by_category.get(category, [])
        
    def get_all_faults(self) -> List[Fault]:
        """获取所有故障（包含同码多条，如57-NBCMU/57-SBCMU）"""
        return list(self._all_faults_list)
        
    def get_valid_faults(self) -> List[Fault]:
        """获取所有有效故障（非预留）"""
        return [f for f in self._faults_by_code.values() if not f.is_reserved()]
        
    def get_reserved_faults(self) -> List[int]:
        """获取所有预留故障码"""
        return list(RESERVED_FAULT_CODES)
        
    def get_shared_faults(self) -> List[Fault]:
        """获取共有故障（所有共享故障码的所有版本）"""
        return [fault for fault in self._all_faults_list if fault.code in SHARED_FAULT_CODES and not fault.is_reserved()]
    
    def get_relay_faults(self) -> List[Fault]:
        """获取继电器故障"""
        return [self.get_fault(code) for code in RELAY_FAULT_CODES if self.get_fault(code)]
        
    def is_reserved_fault(self, code: int) -> bool:
        """检查是否为预留故障"""
        return code in RESERVED_FAULT_CODES
        
    def is_shared_fault(self, code: int) -> bool:
        """检查是否为共有故障"""
        return code in SHARED_FAULT_CODES
        
    def is_relay_fault(self, code: int) -> bool:
        """检查是否为继电器故障"""
        return code in RELAY_FAULT_CODES
        
    def get_nbcmu_faults(self) -> List[Fault]:
        """获取NBCMU域故障"""
        return self.get_faults_by_domain(FaultDomain.NBCMU)

    def get_sbcmu_faults(self) -> List[Fault]:
        """获取SBCMU域故障"""
        return self.get_faults_by_domain(FaultDomain.SBCMU)

    def get_common_faults(self) -> List[Fault]:
        """获取共有故障"""
        return self.get_shared_faults()

    def get_faults_for_test_sequence(self, target_domain: str) -> List[Fault]:
        """
        获取测试序列故障列表
        
        Args:
            target_domain: 目标域，'NBCMU' 或 'SBCMU'
            
        Returns:
            该域需要测试的故障列表（包含共有故障）
        """
        if target_domain.upper() == "NBCMU":
            domain = FaultDomain.NBCMU
        elif target_domain.upper() == "SBCMU":
            domain = FaultDomain.SBCMU
        else:
            raise ValueError(f"无效的目标域: {target_domain}")
            
        # 获取该域专属故障 + 共有故障
        domain_faults = self.get_faults_by_domain(domain)
        shared_faults = self.get_shared_faults()
        
        # 合并并去重
        all_faults = domain_faults + shared_faults
        seen_codes = set()
        result = []
        
        for fault in all_faults:
            if fault.code not in seen_codes and not fault.is_reserved():
                seen_codes.add(fault.code)
                result.append(fault)
                
        # 按故障码排序
        result.sort(key=lambda f: f.code)
        return result
        
    def get_fault_statistics(self) -> Dict[str, int]:
        """获取故障统计信息"""
        valid_faults = self.get_valid_faults()
        
        stats = {
            "total_valid": len(valid_faults),
            "nbcmu_only": len([f for f in valid_faults if f.domain == FaultDomain.NBCMU]),
            "sbcmu_only": len([f for f in valid_faults if f.domain == FaultDomain.SBCMU]),
            "shared": len([f for f in valid_faults if f.domain == FaultDomain.BOTH]),
            "reserved": len(RESERVED_FAULT_CODES),
            "with_inner_specific": len([f for f in valid_faults if f.has_inner_specific()]),
            "with_outer_mapping": len([f for f in valid_faults if f.has_outer_mapping()]),
            "skip_outer": len([f for f in valid_faults if f.is_skip_outer()]),
        }
        
        # 按类别统计
        for category in self._faults_by_category:
            category_faults = [f for f in self._faults_by_category[category] if not f.is_reserved()]
            stats[f"category_{category}"] = len(category_faults)
            
        return stats