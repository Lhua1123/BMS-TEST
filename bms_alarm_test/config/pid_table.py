"""
PID阈值表解析
从Excel文件读取PID阈值配置
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum

import openpyxl
from openpyxl import Workbook

logger = logging.getLogger(__name__)


class ThresholdType(Enum):
    """阈值类型"""
    CURRENT = "current"      # 电流类，原始值 = 实际值 + 30000
    TEMPERATURE = "temp"     # 温度类，原始值 = 实际值 + 40
    VOLTAGE = "voltage"      # 电压类，无偏移
    PERCENTAGE = "percent"   # 百分比类，如SOC/SOH
    RESISTANCE = "resistance"  # 电阻类，如绝缘电阻
    GENERAL = "general"      # 通用类


@dataclass
class PIDConfig:
    """PID配置"""
    pid: int                     # PID值，如0xF001
    alarm_category: str          # 告警类别，如"单体电压过高"
    fault_codes: List[int]       # 对应的故障码列表
    alarm_enable: int            # 告警使能：1=一级使能, 2=二级使能, 3=三级使能
    mature_time: float           # 成熟时间(秒)
    level1_threshold: Optional[float] = None  # 一级阈值（物理值）
    level2_threshold: Optional[float] = None  # 二级阈值（物理值）
    level3_threshold: Optional[float] = None  # 三级阈值（物理值）
    precision: float = 0.1       # 精度
    unit: str = ""               # 单位
    threshold_type: ThresholdType = ThresholdType.GENERAL  # 阈值类型
    threshold_hex: Optional[List[int]] = None  # 5帧阈值报文原始数据(17字节,来自参数表HEX列)
    
    def __post_init__(self):
        """数据验证"""
        if not 0x0000 <= self.pid <= 0xFFFF:
            raise ValueError(f"PID必须在0x0000-0xFFFF范围内: 0x{self.pid:04X}")
        if self.alarm_enable not in (1, 2, 3):
            raise ValueError(f"告警使能必须是1/2/3: {self.alarm_enable}")
        if self.mature_time < 0:
            raise ValueError(f"成熟时间必须>=0: {self.mature_time}")
            
    def get_raw_threshold(self, level: int) -> int:
        """
        获取指定等级的原始阈值（用于DAPP_ThresholdSet报文）
        
        Args:
            level: 等级 1/2/3
            
        Returns:
            原始阈值（整数）
            
        Raises:
            ValueError: 等级无效或该等级无阈值
        """
        if level == 1:
            physical = self.level1_threshold
        elif level == 2:
            physical = self.level2_threshold
        elif level == 3:
            physical = self.level3_threshold
        else:
            raise ValueError(f"无效的等级: {level}")
            
        if physical is None:
            raise ValueError(f"PID 0x{self.pid:04X} 无{level}级阈值")
            
        # 根据阈值类型转换为原始值
        if self.threshold_type == ThresholdType.CURRENT:
            # 电流类：原始值 = 实际电流(A) + 30000
            # 例: 5A → 30050, 10A → 30100, 15A → 30150
            return int(physical * 10 + 30000)  # 精度0.1A，所以乘以10
        elif self.threshold_type == ThresholdType.TEMPERATURE:
            # 温度类：原始值 = 实际温度(℃) + 40
            # 例: 90℃ → 130
            return int(physical + 40)
        elif self.threshold_type == ThresholdType.PERCENTAGE:
            # 百分比类：原始值 = 百分比 × 0.01
            # 例: 20% → 0.20
            return int(physical * 100)  # 转换为整数百分比
        else:
            # 其他类型直接取整
            return int(physical)
            
    def get_physical_threshold(self, level: int) -> Optional[float]:
        """
        获取指定等级的物理阈值
        
        Args:
            level: 等级 1/2/3
            
        Returns:
            物理阈值，无阈值时返回None
        """
        if level == 1:
            return self.level1_threshold
        elif level == 2:
            return self.level2_threshold
        elif level == 3:
            return self.level3_threshold
        else:
            return None
            
    def has_threshold_for_level(self, level: int) -> bool:
        """检查是否有指定等级的阈值"""
        return self.get_physical_threshold(level) is not None
        
    def get_supported_levels(self) -> List[int]:
        """获取支持的等级列表"""
        levels = []
        if self.level1_threshold is not None:
            levels.append(1)
        if self.level2_threshold is not None:
            levels.append(2)
        if self.level3_threshold is not None:
            levels.append(3)
        return levels
        
    @property
    def name(self) -> str:
        """PID名称（兼容旧代码中对 pid.name 的引用）"""
        return self.alarm_category

    def get_description(self) -> str:
        """获取描述信息"""
        return f"PID 0x{self.pid:04X}: {self.alarm_category} ({self.unit})"


class PIDTable:
    """PID阈值表管理器"""
    
    def __init__(self):
        self._pids_by_id: Dict[int, PIDConfig] = {}
        self._pids_by_fault: Dict[int, PIDConfig] = {}
        self._loaded = False
        
    def load_from_excel(self, excel_path: str | Path) -> bool:
        """
        从Excel文件加载PID阈值表
        
        Args:
            excel_path: Excel文件路径
            
        Returns:
            是否加载成功
        """
        excel_path = Path(excel_path)
        if not excel_path.exists():
            logger.error(f"PID阈值表文件不存在: {excel_path}")
            return False
            
        try:
            workbook = openpyxl.load_workbook(excel_path, data_only=True)
            
            # 根据文档，PID表在"2.按PID大小排序"工作表
            sheet_name = "2.按PID大小排序"
            if sheet_name not in workbook.sheetnames:
                # 尝试其他可能的表名
                for name in workbook.sheetnames:
                    if "PID" in name or "pid" in name:
                        sheet_name = name
                        break
                else:
                    logger.error(f"未找到PID工作表，可用工作表: {workbook.sheetnames}")
                    return False
                    
            sheet = workbook[sheet_name]
            
            # 解析表头，找到各列索引
            header_row = None
            for row in sheet.iter_rows(min_row=1, max_row=10, values_only=True):
                if any(cell and "PID" in str(cell) for cell in row):
                    header_row = row
                    break
                    
            if not header_row:
                logger.error("未找到表头行")
                return False
                
            # 构建列索引映射
            col_indices = {}
            for idx, cell in enumerate(header_row):
                if cell:
                    col_name = str(cell).strip()
                    col_indices[col_name] = idx
                    
            # 检查必要的列
            required_cols = ["PID", "告警类别", "对应故障码", "告警使能", "成熟时间(s)", 
                           "一级阈值", "二级阈值", "三级阈值", "精度&单位"]
            missing_cols = [col for col in required_cols if col not in col_indices]
            if missing_cols:
                logger.error(f"缺少必要的列: {missing_cols}")
                return False
                
            # 解析数据行
            data_start_row = None
            for i, row in enumerate(sheet.iter_rows(min_row=1, max_row=sheet.max_row, values_only=True), 1):
                if row[col_indices["PID"]] and isinstance(row[col_indices["PID"]], (int, str)):
                    try:
                        pid_str = str(row[col_indices["PID"]]).strip()
                        if pid_str.startswith("0x") or pid_str.startswith("0X"):
                            pid = int(pid_str, 16)
                        else:
                            pid = int(pid_str)
                            
                        if 0xF000 <= pid <= 0xFFFF:  # 有效的PID范围
                            data_start_row = i
                            break
                    except (ValueError, TypeError):
                        continue
                        
            if not data_start_row:
                logger.error("未找到有效的数据起始行")
                return False
                
            # 解析所有PID配置
            for row_idx in range(data_start_row, sheet.max_row + 1):
                row = [cell.value for cell in sheet[row_idx]]
                
                try:
                    # 解析PID
                    pid_cell = row[col_indices["PID"]]
                    if not pid_cell:
                        continue
                        
                    pid_str = str(pid_cell).strip()
                    if pid_str.startswith("0x") or pid_str.startswith("0X"):
                        pid = int(pid_str, 16)
                    else:
                        pid = int(pid_str)
                        
                    # 解析告警类别
                    alarm_category = str(row[col_indices["告警类别"]]).strip()
                    
                    # 解析对应故障码
                    fault_codes_str = str(row[col_indices["对应故障码"]]).strip()
                    fault_codes = []
                    if fault_codes_str and fault_codes_str != "—":
                        # 处理多种格式：单个数字、范围、逗号分隔
                        for part in fault_codes_str.split(","):
                            part = part.strip()
                            if "-" in part:
                                # 范围格式，如"1-3"
                                start_end = part.split("-")
                                if len(start_end) == 2:
                                    start = int(start_end[0].strip())
                                    end = int(start_end[1].strip())
                                    fault_codes.extend(range(start, end + 1))
                            else:
                                # 单个数字
                                try:
                                    fault_codes.append(int(part))
                                except ValueError:
                                    pass
                    
                    # 解析告警使能
                    alarm_enable_str = str(row[col_indices["告警使能"]]).strip()
                    alarm_enable = 3  # 默认三级使能
                    if alarm_enable_str == "一级":
                        alarm_enable = 1
                    elif alarm_enable_str == "二级":
                        alarm_enable = 2
                    elif alarm_enable_str == "三级":
                        alarm_enable = 3
                    elif alarm_enable_str.isdigit():
                        alarm_enable = int(alarm_enable_str)
                        
                    # 解析成熟时间
                    mature_time_str = str(row[col_indices["成熟时间(s)"]]).strip()
                    mature_time = float(mature_time_str) if mature_time_str else 0.0
                    
                    # 解析阈值
                    def parse_threshold(val):
                        if not val:
                            return None
                        val_str = str(val).strip()
                        if val_str in ("无", "—", "无(暂)", "无(暂无)"):
                            return None
                        try:
                            return float(val_str)
                        except ValueError:
                            return None
                            
                    level1_threshold = parse_threshold(row[col_indices["一级阈值"]])
                    level2_threshold = parse_threshold(row[col_indices["二级阈值"]])
                    level3_threshold = parse_threshold(row[col_indices["三级阈值"]])
                    
                    # 解析精度和单位
                    precision_unit = str(row[col_indices["精度&单位"]]).strip()
                    precision = 1.0
                    unit = ""
                    
                    if precision_unit:
                        # 解析格式如："1mV", "0.1A(-30000)", "1℃(-40)", "0.01"
                        if "(" in precision_unit:
                            # 有偏移说明，如"0.1A(-30000)"
                            main_part = precision_unit.split("(")[0].strip()
                        else:
                            main_part = precision_unit
                            
                        # 提取数字和单位
                        import re
                        match = re.match(r"([\d.]+)(.*)", main_part)
                        if match:
                            precision = float(match.group(1))
                            unit = match.group(2).strip()
                            
                    # 确定阈值类型
                    threshold_type = self._determine_threshold_type(alarm_category, precision_unit)
                    
                    # 解析阈值报文HEX数据（参数表HEX列17字节，用于DAPP_ThresholdSet 5帧）
                    threshold_hex = None
                    hex_col = col_indices.get("HEX")
                    if hex_col is not None:
                        try:
                            raw_hex = []
                            for _k in range(1, 18):
                                cell_val = row[hex_col + _k]
                                if cell_val is None:
                                    continue
                                s = str(cell_val).strip()
                                if s == "":
                                    continue
                                raw_hex.append((int(s, 16)) & 0xFF)
                            if raw_hex:
                                while len(raw_hex) < 17:
                                    raw_hex.append(0)
                                threshold_hex = raw_hex[:17]
                        except (ValueError, TypeError):
                            threshold_hex = None

                    # 创建PID配置
                    pid_config = PIDConfig(
                        pid=pid,
                        alarm_category=alarm_category,
                        fault_codes=fault_codes,
                        alarm_enable=alarm_enable,
                        mature_time=mature_time,
                        level1_threshold=level1_threshold,
                        level2_threshold=level2_threshold,
                        level3_threshold=level3_threshold,
                        precision=precision,
                        unit=unit,
                        threshold_type=threshold_type,
                        threshold_hex=threshold_hex
                    )
                    
                    # 添加到索引
                    self._pids_by_id[pid] = pid_config
                    for fault_code in fault_codes:
                        self._pids_by_fault[fault_code] = pid_config
                        
                    logger.debug(f"加载PID: 0x{pid:04X} - {alarm_category}")
                    
                except Exception as e:
                    logger.warning(f"解析PID行{row_idx}失败: {e}")
                    continue
                    
            self._loaded = True
            logger.info(f"成功加载 {len(self._pids_by_id)} 个PID配置")
            return True
            
        except Exception as e:
            logger.error(f"加载PID阈值表失败: {e}")
            return False
            
    def _determine_threshold_type(self, alarm_category: str, precision_unit: str) -> ThresholdType:
        """根据告警类别和精度单位确定阈值类型"""
        category_lower = alarm_category.lower()
        unit_lower = precision_unit.lower()
        
        if "电流" in category_lower or "A" in unit_lower:
            return ThresholdType.CURRENT
        elif "温度" in category_lower or "℃" in unit_lower or "度" in category_lower:
            return ThresholdType.TEMPERATURE
        elif "电压" in category_lower or "V" in unit_lower or "mV" in unit_lower:
            return ThresholdType.VOLTAGE
        elif "绝缘" in category_lower or "Ω" in unit_lower:
            return ThresholdType.RESISTANCE
        elif "SOC" in category_lower or "SOH" in category_lower or "%" in unit_lower:
            return ThresholdType.PERCENTAGE
        else:
            return ThresholdType.GENERAL
            
    def get_pid_by_id(self, pid: int) -> Optional[PIDConfig]:
        """根据PID获取配置"""
        return self._pids_by_id.get(pid)

    def get_pid_by_code(self, code) -> Optional[PIDConfig]:
        """
        根据 PID 代码字符串精确解析配置。
        支持 "0xF001"、"F001"、"f001"、十进制整数 "61441" 或 int 类型。
        """
        if isinstance(code, int):
            return self._pids_by_id.get(code)
        s = str(code).strip()
        if not s:
            return None
        try:
            if s.lower().startswith("0x"):
                pid = int(s, 16)
            elif s.isdigit():
                pid = int(s)
            else:
                pid = int(s, 16)
        except ValueError:
            return None
        return self._pids_by_id.get(pid)
        
    def get_pid_by_fault_code(self, fault_code: int) -> Optional[PIDConfig]:
        """根据故障码获取对应的PID配置"""
        return self._pids_by_fault.get(fault_code)

    def get_pids_by_names(self, names: List[str]) -> List[PIDConfig]:
        """根据PID代码或名称列表获取配置（支持PID值或名称模糊匹配）"""
        result = []
        name_set = {n.strip() for n in names}
        for pid_config in self._pids_by_id.values():
            pid_str = str(pid_config.pid)
            if pid_str in name_set:
                result.append(pid_config)
                continue
            if pid_config.alarm_category in name_set:
                result.append(pid_config)
                continue
            for name in name_set:
                if name.lower() in pid_config.alarm_category.lower():
                    result.append(pid_config)
                    break
        return result

    def get_all_pids(self) -> List[PIDConfig]:
        """获取所有PID配置"""
        return list(self._pids_by_id.values())

    def get_level_rows(self) -> List[Tuple[PIDConfig, int, Optional[float]]]:
        """
        获取所有使能的等级行，每个元素为 (PIDConfig, level, threshold)。
        仅包含该等级有阈值的行。
        """
        rows = []
        for pid in self._pids_by_id.values():
            levels = pid.get_supported_levels()
            for lv in levels:
                rows.append((pid, lv, pid.get_physical_threshold(lv)))
        return rows

    def get_pid_by_level_code(self, code) -> Optional[Tuple[PIDConfig, int]]:
        """
        解析形如 "0xF001:2" 的等级代码，返回 (PIDConfig, level)。
        """
        if isinstance(code, str) and ':' in code:
            pid_part, level_part = code.rsplit(':', 1)
            pid = self.get_pid_by_code(pid_part.strip())
            if pid is not None:
                try:
                    level = int(level_part.strip())
                    if level in pid.get_supported_levels():
                        return (pid, level)
                except ValueError:
                    pass
        return None
        
    def get_pids_for_fault_codes(self, fault_codes: List[int]) -> Dict[int, PIDConfig]:
        """获取多个故障码对应的PID配置"""
        result = {}
        for fault_code in fault_codes:
            pid_config = self.get_pid_by_fault_code(fault_code)
            if pid_config:
                result[fault_code] = pid_config
        return result
        
    def get_fault_codes_with_pid(self) -> List[int]:
        """获取所有有PID对应的故障码"""
        return list(self._pids_by_fault.keys())
        
    def get_fault_codes_without_pid(self, all_fault_codes: List[int]) -> List[int]:
        """获取没有PID对应的故障码"""
        with_pid = set(self._pids_by_fault.keys())
        return [code for code in all_fault_codes if code not in with_pid]
        
    def is_loaded(self) -> bool:
        """检查是否已加载"""
        return self._loaded
        
    def clear(self):
        """清除所有PID配置"""
        self._pids_by_id.clear()
        self._pids_by_fault.clear()
        self._loaded = False
        logger.info("PID配置已清除")
        
    def get_statistics(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            "total_pids": len(self._pids_by_id),
            "faults_with_pid": len(self._pids_by_fault),
            "current_type": len([p for p in self._pids_by_id.values() if p.threshold_type == ThresholdType.CURRENT]),
            "temperature_type": len([p for p in self._pids_by_id.values() if p.threshold_type == ThresholdType.TEMPERATURE]),
            "voltage_type": len([p for p in self._pids_by_id.values() if p.threshold_type == ThresholdType.VOLTAGE]),
            "percentage_type": len([p for p in self._pids_by_id.values() if p.threshold_type == ThresholdType.PERCENTAGE]),
            "resistance_type": len([p for p in self._pids_by_id.values() if p.threshold_type == ThresholdType.RESISTANCE]),
            "general_type": len([p for p in self._pids_by_id.values() if p.threshold_type == ThresholdType.GENERAL]),
        }


# 默认PID配置（当Excel文件不可用时使用）
DEFAULT_PID_CONFIGS = [
    # 电压类
    PIDConfig(0xF001, "单体电压过高", [1, 2, 3], 3, 2.0, 3455, 3500, 3550, 1, "mV", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x02, 0x0D, 0xDE, 0x00, 0x00, 0x11, 0x0D, 0xAC, 0x0D, 0x7F, 0x10, 0x0D, 0x7F, 0x0D, 0x7A, 0x10]),
    PIDConfig(0xF002, "单体电压过低", [4, 5, 6], 3, 2.0, 2950, 2900, 2850, 1, "mV", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x02, 0x0B, 0x22, 0x11, 0x94, 0x0E, 0x0B, 0x54, 0x0B, 0x86, 0x09, 0x0B, 0x86, 0x0B, 0xB8, 0x09]),
    PIDConfig(0xF003, "单体压差过大", [7, 8, 9], 3, 5.0, 150, 200, 250, 1, "mV", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x05, 0x00, 0xFA, 0x00, 0x00, 0x11, 0x00, 0xC8, 0x00, 0xC3, 0x0B, 0x00, 0x96, 0x00, 0x91, 0x01]),
    PIDConfig(0xF01E, "模块总压过高", [10, 11, 12], 3, 2.0, 63.9, 63.0, 62.2, 0.1, "V", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x02, 0x02, 0x7F, 0x00, 0x00, 0x11, 0x02, 0x76, 0x02, 0x6D, 0x10, 0x02, 0x6D, 0x02, 0x6D, 0x10]),
    PIDConfig(0xF01F, "模块总压过低", [13, 14, 15], 3, 2.0, 51.3, 52.2, 53.1, 0.1, "V", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x02, 0x02, 0x01, 0x03, 0x2A, 0x0E, 0x02, 0x0A, 0x02, 0x13, 0x0E, 0x02, 0x13, 0x02, 0x1C, 0x09]),
        PIDConfig(0xF00B, "簇总压过高", [16, 17, 18], 3, 2.0, 62.2, 63.0, 63.9, 0.1, "V", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x02, 0x02, 0x7F, 0x00, 0x00, 0x11, 0x02, 0x76, 0x02, 0x6D, 0x10, 0x02, 0x6D, 0x02, 0x6D, 0x10]),
    PIDConfig(0xF00C, "簇总压过低", [19, 20, 21], 3, 2.0, 53.1, 52.2, 51.3, 0.1, "V", ThresholdType.VOLTAGE, threshold_hex=[0x03, 0x02, 0x02, 0x01, 0x03, 0x2A, 0x0E, 0x02, 0x0A, 0x02, 0x13, 0x0E, 0x02, 0x13, 0x02, 0x1C, 0x09]),
    
    # 电流类
    PIDConfig(0xF00E, "簇放电电流过大", [22, 23, 24], 3, 5.0, 5.0, 10.0, 15.0, 0.1, "A", ThresholdType.CURRENT, threshold_hex=[0x03, 0x05, 0x75, 0xC6, 0x75, 0x30, 0x11, 0x75, 0x94, 0x75, 0x30, 0x09, 0x75, 0x62, 0x75, 0x30, 0x01]),
    PIDConfig(0xF00F, "簇充电电流过大", [25, 26, 27], 3, 5.0, 5.0, 10.0, 15.0, 0.1, "A", ThresholdType.CURRENT, threshold_hex=[0x03, 0x05, 0x75, 0xC6, 0x75, 0x30, 0x11, 0x75, 0x94, 0x75, 0x30, 0x0A, 0x75, 0x62, 0x75, 0x30, 0x01]),
    PIDConfig(0xF01C, "环流过大", [96], 1, 3.0, None, None, 10.0, 0.1, "A", ThresholdType.CURRENT, threshold_hex=[0x01, 0x03, 0x00, 0x64, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    
    # 绝缘类
    PIDConfig(0xF014, "高压绝缘故障", [28, 29, 30], 3, 20.0, 1000, 800, 600, 1, "Ω/V", ThresholdType.RESISTANCE, threshold_hex=[0x03, 0x14, 0x02, 0x58, 0x03, 0x20, 0x11, 0x03, 0x20, 0x03, 0xE8, 0x0B, 0x03, 0xE8, 0x04, 0xB0, 0x01]),
    
    # 温度类
    PIDConfig(0xF020, "充电温度高", [31, 32, 33], 3, 5.0, 90, 95, 100, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x03, 0x05, 0x00, 0x64, 0x00, 0x00, 0x11, 0x00, 0x5F, 0x00, 0x5A, 0x0B, 0x00, 0x5A, 0x00, 0x55, 0x01]),
    PIDConfig(0xF021, "充电温度低", [34, 35, 36], 3, 5.0, 46, 44, 42, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x03, 0x05, 0x00, 0x2A, 0x00, 0x64, 0x10, 0x00, 0x2C, 0x00, 0x2E, 0x0B, 0x00, 0x2E, 0x00, 0x30, 0x0A]),
    PIDConfig(0xF006, "放电温度高", [37, 38, 39], 3, 5.0, 90, 95, 100, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x03, 0x05, 0x00, 0x64, 0x00, 0x00, 0x11, 0x00, 0x5F, 0x00, 0x5A, 0x0B, 0x00, 0x5A, 0x00, 0x55, 0x01]),
    PIDConfig(0xF007, "放电温度低", [40, 41, 42], 3, 5.0, 30, 28, 10, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x03, 0x05, 0x00, 0x0A, 0x00, 0x64, 0x11, 0x00, 0x1C, 0x00, 0x1E, 0x0B, 0x00, 0x1E, 0x00, 0x20, 0x09]),
    PIDConfig(0xF008, "温差过大", [43, 44, 45], 3, 10.0, 48, 50, 55, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x03, 0x0A, 0x00, 0x37, 0x00, 0x00, 0x11, 0x00, 0x32, 0x00, 0x31, 0x01, 0x00, 0x30, 0x00, 0x2F, 0x01]),
    PIDConfig(0xF010, "环境温度过高", [74, 75, 76], 2, 5.0, 85, 95, 100, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x02, 0x05, 0x00, 0x64, 0x00, 0x00, 0x11, 0x00, 0x5F, 0x00, 0x55, 0x0A, 0x00, 0x55, 0x00, 0x52, 0x01]),
    PIDConfig(0xF011, "环境温度过低", [78, 79], 2, 5.0, None, 30, 10, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x02, 0x05, 0x00, 0x0A, 0x00, 0x1E, 0x11, 0x00, 0x1E, 0x00, 0x23, 0x0B, 0x00, 0x00, 0x00, 0x00, 0x00]),
    PIDConfig(0xF019, "S板过高温(单体)", [91], 1, 5.0, None, None, 105, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x01, 0x05, 0x00, 0x69, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    PIDConfig(0xF01A, "S板过高温(环境)", [92], 1, 5.0, None, None, 105, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x01, 0x05, 0x00, 0x69, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    PIDConfig(0xF01B, "S板充电插座过温", [93, 94], 3, 3.0, 135, 140, 200, 1, "℃", ThresholdType.TEMPERATURE, threshold_hex=[0x03, 0x03, 0x00, 0xC8, 0x00, 0xC8, 0x00, 0x00, 0x8C, 0x00, 0x00, 0x11, 0x00, 0x87, 0x00, 0x82, 0x0A]),
    
    # SOC/SOH类
    PIDConfig(0xF023, "SOC过低", [49, 50, 51], 3, 3.0, 20, 10, 0, 0.01, "%", ThresholdType.PERCENTAGE, threshold_hex=[0x03, 0x03, 0x00, 0x00, 0x00, 0x05, 0x01, 0x00, 0x0A, 0x00, 0x0A, 0x01, 0x00, 0x14, 0x00, 0x14, 0x01]),
    PIDConfig(0xF024, "SOH过低", [52], 3, 3.0, 70, None, None, 1, "%", ThresholdType.PERCENTAGE, threshold_hex=[0x03, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46, 0x00, 0x65, 0x01]),
    
    # 供电电压类
    PIDConfig(0xF012, "供电电压过高", [68], 1, 3.0, 32.0, None, None, 0.1, "V", ThresholdType.VOLTAGE, threshold_hex=[0x01, 0x03, 0x01, 0x40, 0x01, 0x04, 0x11, 0x01, 0xF4, 0x01, 0xF4, 0x00, 0x01, 0xF4, 0x01, 0xF4, 0x00]),
    PIDConfig(0xF013, "供电电压过低", [71], 1, 3.0, 9.0, None, None, 0.1, "V", ThresholdType.VOLTAGE, threshold_hex=[0x01, 0x03, 0x00, 0x5A, 0x00, 0x78, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
]


def create_default_pid_table() -> PIDTable:
    """创建包含默认PID配置的表"""
    pid_table = PIDTable()
    
    for pid_config in DEFAULT_PID_CONFIGS:
        pid_table._pids_by_id[pid_config.pid] = pid_config
        for fault_code in pid_config.fault_codes:
            pid_table._pids_by_fault[fault_code] = pid_config
            
    pid_table._loaded = True
    logger.info(f"创建了包含 {len(pid_table._pids_by_id)} 个默认PID配置的表")
    return pid_table


# 导出
__all__ = [
    "ThresholdType",
    "PIDConfig",
    "PIDTable",
    "create_default_pid_table"
]