"""
DBC文件解析器
基于cantools加载DBC，支持加载内部DBC和外部DBC（两路独立）
"""

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

import cantools
from cantools.database.errors import ParseError

logger = logging.getLogger(__name__)


@dataclass
class DBCInfo:
    """DBC文件信息"""
    path: Path
    db: cantools.database.Database
    name: str
    description: str = ""


class DBCLoader:
    """DBC文件加载器"""

    def __init__(self):
        self._inner_dbc: Optional[DBCInfo] = None
        self._outer_dbc: Optional[DBCInfo] = None
        self._dbc_cache: Dict[Path, DBCInfo] = {}

    @staticmethod
    def _resolve_duplicate_signals(content: str) -> str:
        """同报文内重名 SG_ 自动加序号后缀，避免 cantools 因 overlap 拒绝加载"""
        result_lines = []
        in_message = False
        name_counts: Dict[str, int] = {}

        for line in content.splitlines(keepends=True):
            stripped = line.lstrip()
            if stripped.startswith('BO_ '):
                in_message = True
                name_counts = {}
                result_lines.append(line)
                continue

            if in_message and stripped.startswith('SG_'):
                m = re.match(r'(\s*SG_\s+)([A-Za-z_][A-Za-z0-9_]*)(\s*:.*)', line)
                if m:
                    prefix, name, rest = m.group(1), m.group(2), m.group(3)
                    name_counts[name] = name_counts.get(name, 0) + 1
                    if name_counts[name] > 1:
                        new_name = f"{name}_dup{name_counts[name]}"
                        logger.warning("DBC 重名信号: 同报文内将 %s 重命名为 %s", name, new_name)
                        line = f"{prefix}{new_name}{rest}"
                result_lines.append(line)
                continue

            if not stripped.strip():
                in_message = False
                name_counts = {}
            result_lines.append(line)

        return ''.join(result_lines)

    def _load_db(self, dbc_path: Path) -> cantools.database.Database:
        """读文件（多编码）→ 去重名 → cantools 解析"""
        last_error = None
        for enc in ('utf-8', 'gbk', 'gb2312', 'iso-8859-1'):
            try:
                content = dbc_path.read_text(encoding=enc)
                content = self._resolve_duplicate_signals(content)
                return cantools.database.load_string(content)
            except UnicodeDecodeError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                logger.warning("以 %s 加载 DBC 失败: %s", enc, e)
                continue
        raise ParseError(f"无法解析 DBC {dbc_path.name}: {last_error}")

    def load_inner_dbc(self, dbc_path: str | Path) -> DBCInfo:
        """
        加载内部DBC文件（用于CAN1 CH1，故障注入/回读验证）

        Args:
            dbc_path: DBC文件路径

        Returns:
            DBCInfo对象

        Raises:
            FileNotFoundError: DBC文件不存在
            cantools.database.ParseError: DBC文件格式错误
        """
        dbc_path = Path(dbc_path)
        if dbc_path in self._dbc_cache:
            self._inner_dbc = self._dbc_cache[dbc_path]
            return self._inner_dbc

        if not dbc_path.exists():
            raise FileNotFoundError(f"内部DBC文件不存在: {dbc_path}")

        try:
            db = self._load_db(dbc_path)
            # 同样需要归一化内 DBC 报文 ID（减去 0x80000000 偏移，恢复硬件 CAN 空间）
            self._normalize_outer_ids(db)

            dbc_info = DBCInfo(
                path=dbc_path,
                db=db,
                name=dbc_path.stem,
                description="通道0 DBC（故障注入/回读验证）"
            )

            self._dbc_cache[dbc_path] = dbc_info
            self._inner_dbc = dbc_info

            logger.info(f"成功加载内部DBC: {dbc_path.name}, 包含 {len(db.messages)} 个报文，并完成 ID 归一化")
            return dbc_info

        except ParseError as e:
            logger.error(f"内部DBC文件解析失败: {dbc_path}, 错误: {e}")
            raise

    def load_outer_dbc(self, dbc_path: str | Path) -> DBCInfo:
        """
        加载外部DBC文件（用于CAN2 CH2，只读监控）

        Args:
            dbc_path: DBC文件路径

        Returns:
            DBCInfo对象

        Raises:
            FileNotFoundError: DBC文件不存在
            cantools.database.ParseError: DBC文件格式错误
        """
        dbc_path = Path(dbc_path)
        if dbc_path in self._dbc_cache:
            self._outer_dbc = self._dbc_cache[dbc_path]
            return self._outer_dbc

        if not dbc_path.exists():
            raise FileNotFoundError(f"外部DBC文件不存在: {dbc_path}")

        try:
            db = self._load_db(dbc_path)

            # 归一化外 DBC 报文 ID（减去 0x80000000 偏移，恢复硬件 CAN 空间）
            self._normalize_outer_ids(db)

            dbc_info = DBCInfo(
                path=dbc_path,
                db=db,
                name=dbc_path.stem,
                description="通道1 DBC（只读监控）"
            )

            self._dbc_cache[dbc_path] = dbc_info
            self._outer_dbc = dbc_info

            logger.info(f"成功加载外部DBC: {dbc_path.name}, 包含 {len(db.messages)} 个报文")
            return dbc_info

        except ParseError as e:
            logger.error(f"外部DBC文件解析失败: {dbc_path}, 错误: {e}")
            raise
            
    def get_inner_dbc(self) -> Optional[DBCInfo]:
        """获取已加载的内部DBC"""
        return self._inner_dbc
        
    def get_outer_dbc(self) -> Optional[DBCInfo]:
        """获取已加载的外部DBC"""
        return self._outer_dbc
        
    def get_message(self, dbc_type: str, message_name: str) -> Optional[cantools.database.Message]:
        """
        获取指定报文
        
        Args:
            dbc_type: 'inner' 或 'outer'
            message_name: 报文名称
            
        Returns:
            cantools.database.Message对象，未找到时返回None
        """
        dbc_info = self._inner_dbc if dbc_type == 'inner' else self._outer_dbc
        if not dbc_info:
            logger.warning(f"{dbc_type} DBC未加载")
            return None
            
        try:
            return dbc_info.db.get_message_by_name(message_name)
        except KeyError:
            logger.warning(f"在{dbc_type} DBC中未找到报文: {message_name}")
            return None
            
    def get_signal(self, dbc_type: str, message_name: str, signal_name: str) -> Optional[cantools.database.Signal]:
        """
        获取指定信号
        
        Args:
            dbc_type: 'inner' 或 'outer'
            message_name: 报文名称
            signal_name: 信号名称
            
        Returns:
            cantools.database.Signal对象，未找到时返回None
        """
        message = self.get_message(dbc_type, message_name)
        if not message:
            return None
            
        try:
            return message.get_signal_by_name(signal_name)
        except KeyError:
            logger.warning(f"在报文{message_name}中未找到信号: {signal_name}")
            return None
            
    def decode_message(self, dbc_type: str, can_id: int, data: bytes) -> Optional[Dict]:
        """
        解码CAN报文（支持NBICU等地址占位符ID的自动归一化）
        """
        dbc_info = self._inner_dbc if dbc_type == 'inner' else self._outer_dbc
        if not dbc_info:
            logger.warning(f"{dbc_type} DBC未加载，无法解码")
            return None

        try:
            return dbc_info.db.decode_message(can_id, data)
        except KeyError:
            # DBC中NBICU等报文frame_id末字节为占位符(0x01)，
            # 实际硬件CAN ID用BMS地址（如0xA1），归一化后重试
            normalized_id = (can_id & 0xFFFFFF00) | 0x01
            try:
                return dbc_info.db.decode_message(normalized_id, data)
            except Exception as e2:
                logger.debug(f"解码失败: can_id=0x{can_id:X}, 归一化后0x{normalized_id:X}, 错误: {e2}")
                return None
        except Exception as e:
            logger.debug(f"解码失败: can_id=0x{can_id:X}, 错误: {e}")
            return None
            
    def encode_message(self, dbc_type: str, message_name: str, signals: Dict[str, any]) -> Optional[Tuple[int, bytes]]:
        """
        编码CAN报文
        
        Args:
            dbc_type: 'inner' 或 'outer'
            message_name: 报文名称
            signals: 信号字典 {信号名: 值}
            
        Returns:
            (can_id, data)元组，编码失败时返回None
        """
        message = self.get_message(dbc_type, message_name)
        if not message:
            return None
            
        try:
            data = message.encode(signals)
            return (message.frame_id, data)
        except Exception as e:
            logger.error(f"编码失败: message={message_name}, signals={signals}, 错误: {e}")
            return None
            
    def get_all_messages(self, dbc_type: str) -> Dict[str, cantools.database.Message]:
        """
        获取所有报文
        
        Args:
            dbc_type: 'inner' 或 'outer'
            
        Returns:
            报文名字典 {报文名: Message对象}
        """
        dbc_info = self._inner_dbc if dbc_type == 'inner' else self._outer_dbc
        if not dbc_info:
            return {}
            
        return {msg.name: msg for msg in dbc_info.db.messages}
        
    def get_all_signals(self, dbc_type: str, message_name: str) -> Dict[str, cantools.database.Signal]:
        """
        获取指定报文的所有信号
        
        Args:
            dbc_type: 'inner' 或 'outer'
            message_name: 报文名称
            
        Returns:
            信号名字典 {信号名: Signal对象}
        """
        message = self.get_message(dbc_type, message_name)
        if not message:
            return {}
            
        return {sig.name: sig for sig in message.signals}
        
    def clear_cache(self):
        """清除DBC缓存"""
        self._inner_dbc = None
        self._outer_dbc = None
        self._dbc_cache.clear()
        logger.info("DBC缓存已清除")

    def _normalize_outer_ids(self, db: cantools.database.Database) -> cantools.database.Database:
        """将外DBC的报文ID统一到硬件CAN空间（减去0x80000000偏移）"""
        delta = 0x80000000
        changed = 0
        for msg in db.messages:
            if msg.frame_id >= delta:
                msg.frame_id -= delta
                changed += 1
        if changed:
            # 重建cantools内部索引，否则decode_message仍用旧ID查找
            db._frame_id_to_message = {m.frame_id: m for m in db.messages}
            logger.info(f"外DBC ID归一化: {changed}个报文ID偏移-0x{delta:X}")
        return db