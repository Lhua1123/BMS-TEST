"""
故障验证映射（期望值 / 回读信号）可编辑配置
覆盖内置 fault_mapping 中的期望值，并可为单个故障增加额外回读项。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from bms_alarm_test.config.fault_mapping import Fault, FaultDomain, FaultMapping

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CONFIG_DIR / "fault_verify_overrides.json"

OVERRIDABLE_FIELDS = (
    "name",
    "level",
    "sys_fail_sta_expected",
    "err_tab_expected",
    "inner_signal",
    "inner_expected",
    "outer_signal",
    "outer_expected",
    "outer_warning_expected",
    "category",
    "extra_checks",
    "enabled",
)


def fault_key(code: int, domain) -> str:
    d = domain.value if hasattr(domain, "value") else str(domain)
    return f"{code}:{d}"


def fault_to_dict(fault: Fault) -> Dict[str, Any]:
    return {
        "code": fault.code,
        "domain": fault.domain.value,
        "name": fault.name,
        "level": fault.level,
        "sys_fail_sta_expected": fault.sys_fail_sta_expected,
        "err_tab_expected": fault.err_tab_expected,
        "inner_signal": fault.inner_signal,
        "inner_expected": fault.inner_expected,
        "outer_signal": fault.outer_signal,
        "outer_expected": fault.outer_expected,
        "outer_warning_expected": fault.outer_warning_expected,
        "category": fault.category,
        "extra_checks": list(fault.extra_checks or []),
        "enabled": bool(fault.enabled),
    }


def default_file(mapping: FaultMapping) -> Dict[str, Any]:
    """从当前 FaultMapping 生成完整覆盖文件（便于直接改）"""
    items = []
    for f in mapping.all_faults_raw():
        items.append(fault_to_dict(f))
    return {
        "version": 1,
        "note": "改期望值/信号名/额外回读后保存；测试前生效。enabled=false 跳过该故障。",
        "faults": items,
    }


class FaultVerifyConfig:
    """故障期望值 / 回读信号覆盖配置"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else CONFIG_PATH
        self.data: Dict[str, Any] = {"version": 1, "faults": []}
        self.load()

    def load(self) -> bool:
        if not self.path.exists():
            self.data = {"version": 1, "faults": []}
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("faults"), list):
                self.data = loaded
            elif isinstance(loaded, list):
                self.data = {"version": 1, "faults": loaded}
            else:
                self.data = {"version": 1, "faults": []}
            return True
        except Exception as e:
            logger.error(f"加载故障验证覆盖配置失败: {e}")
            self.data = {"version": 1, "faults": []}
            return False

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            logger.info(f"已保存故障验证覆盖配置: {self.path}")
            return True
        except Exception as e:
            logger.error(f"保存故障验证覆盖配置失败: {e}")
            return False

    def export_from_mapping(self, mapping: FaultMapping) -> bool:
        """把当前内存映射写成覆盖文件（首次生成/恢复内置）"""
        self.data = default_file(mapping)
        return self.save()

    def list_entries(self) -> List[Dict[str, Any]]:
        return list(self.data.get("faults") or [])

    def get_entry(self, code: int, domain: Any) -> Optional[Dict[str, Any]]:
        key = fault_key(code, domain)
        for item in self.list_entries():
            if item.get("code") == code and str(item.get("domain", "")).upper() == key.split(":", 1)[1].upper():
                return item
            if fault_key(item.get("code", -1), item.get("domain", "")) == key:
                return item
        return None

    def upsert_entry(self, item: Dict[str, Any]) -> None:
        key = fault_key(item.get("code"), item.get("domain"))
        faults = self.data.setdefault("faults", [])
        for i, old in enumerate(faults):
            if fault_key(old.get("code", -1), old.get("domain", "")) == key:
                faults[i] = item
                return
        faults.append(item)

    def apply_to_mapping(self, mapping: FaultMapping) -> int:
        """把覆盖项写回 FaultMapping 中的 Fault 对象"""
        count = 0
        by_key = {}
        for f in mapping.all_faults_raw():
            by_key[fault_key(f.code, f.domain)] = f

        for item in self.list_entries():
            key = fault_key(item.get("code", -1), item.get("domain", ""))
            fault = by_key.get(key)
            if fault is None:
                # 新故障码不在内置表中则跳过（避免无效注入）
                continue
            for field in OVERRIDABLE_FIELDS:
                if field in item:
                    try:
                        setattr(fault, field, item[field])
                    except Exception as e:
                        logger.warning(f"覆盖字段失败 {key}.{field}: {e}")
            count += 1

        # 重建索引（同一 code 多域）
        mapping.rebuild_indexes()
        logger.info(f"已应用故障验证覆盖 {count} 条，配置文件: {self.path.name}")
        return count

    def ensure_exported(self, mapping: FaultMapping) -> None:
        if not self.path.exists():
            try:
                self.export_from_mapping(mapping)
                logger.info(f"已生成故障验证默认配置: {self.path}")
            except Exception as e:
                logger.warning(f"生成默认故障验证配置失败: {e}")


_global_fault_verify: Optional[FaultVerifyConfig] = None


def get_fault_verify_config() -> FaultVerifyConfig:
    global _global_fault_verify
    if _global_fault_verify is None:
        _global_fault_verify = FaultVerifyConfig()
    return _global_fault_verify


def reload_fault_mapping_with_overrides(mapping: FaultMapping) -> FaultMapping:
    """重载内置映射并应用覆盖文件"""
    mapping.reload_builtin()
    cfg = get_fault_verify_config()
    cfg.ensure_exported(mapping)
    cfg.load()
    cfg.apply_to_mapping(mapping)
    return mapping
