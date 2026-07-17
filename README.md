# BMS测试工具整合版

基于 PyQt5 的 BMS（电池管理系统）测试工具，统一界面集成进制转换、CAN报文解析、L2/L3 BMS寄存器监控与协议配置编辑。

## 功能概览

| Tab | 核心功能 |
|-----|---------|
| **进制转换** | 二进制/八进制/十进制/十六进制/ASCII 互转，一键复制 |
| **CAN报文解析** | CAN ID 解析、数据帧解析、DBC 文件导入解码 |
| **L2-BMS监控** | Modbus RTU 轮询、寄存器实时监控、信号物理值解析、控制指令 |
| **L3-BMS监控** | 同 L2，使用 L3 协议配置 |
| **协议配置** | 弹窗编辑信号参数（因子/偏移/单位/位长度），导入 Excel 协议文件，用户配置持久化 |

## 技术栈

- **PyQt5** >= 5.15 — GUI 框架
- **pyserial** >= 4.0 — Modbus RTU 串口通信
- **openpyxl** >= 3.1 — Excel 协议文件解析
- **pyperclip** >= 1.8.2 — 剪贴板复制
- **cantools** >= 39.0.0, < 42.0.0 — DBC 文件解析

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

Windows 用户可直接双击 `run.bat`。

## 项目结构

```
BMS测试-整合版/
├── main.py                         # 入口，主窗口与 Tab 管理
├── requirements.txt                # 依赖列表
├── run.bat                         # Windows 快捷启动
├── protocol_user_config.json       # 用户协议配置（L2/L3 分离存储）
│
├── shared/                         # 共享基础模块
│   ├── style.py                   # 统一样式系统（颜色、字体、QSS）
│   ├── modbus_comm.py             # Modbus RTU 串口通信封装
│   ├── modbus_parser.py           # Modbus 协议解析（单帧/批量）
│   └── excel_parser.py            # Excel 协议文件解析器
│
├── tabs/                           # Tab 模块（每个 Tab 独立封装）
│   ├── convert_ascii_tab.py       # 进制转换标签页
│   ├── can_parser_tab.py          # CAN 报文解析标签页
│   ├── bms_monitor_tab.py         # L2/L3 BMS 监控标签页
│   └── protocol_config_dialog.py  # 协议配置编辑弹窗
│
├── l2_protocol/                    # L2 协议定义
│   ├── protocol_config.py         # L2 寄存器配置（从 Excel 自动生成）
│   └── *.xlsx                     # L2 原始协议 Excel
│
├── l3_protocol/                    # L3 协议定义
│   ├── protocol_config.py         # L3 寄存器配置（从 Excel 自动生成）
│   └── *.xlsx                     # L3 原始协议 Excel
│
└── convert_ascii/                  # 进制转换与 CAN 解析核心库
    ├── core/
    │   └── converter.py           # ASCII/进制转换核心算法
    ├── bms/
    │   └── bms_formatter.py       # BMS 数据格式化、DBC 解码
    └── gui/
        └── styles.py              # Convert_ASCII 模块独立样式
```

## 架构设计

### Tab 隔离原则

每个标签页都是**完全独立**的 `QWidget` 子类：

- **类隔离**：独立类，无继承关系，互不引用
- **状态隔离**：在 `__init__` 中实例化自己的业务对象，不共享实例
- **样式隔离**：统一从 `shared/style.py` 导入 `COLORS`/`FONTS`，不依赖全局样式副作用
- **关闭隔离**：`main.py` 的 `closeEvent` 只对需要清理资源的 Tab 调用清理方法

### 新增 Tab 步骤

1. 在 `tabs/` 下创建新文件，如 `tabs/my_feature_tab.py`
2. 实现继承 `QWidget` 的类，在 `__init__` 中完成所有 UI 和业务初始化
3. 在 `main.py` 中导入并添加：
   ```python
   from tabs.my_feature_tab import MyFeatureTab
   self.tab_widget.addTab(MyFeatureTab(), "我的功能")
   ```
4. **不需要修改任何现有 Tab 的代码**

### 开发约束

| 约定 | 说明 |
|------|------|
| 禁止模块级全局单例 | 所有业务对象在 `__init__` 中实例化 |
| 禁止跨 Tab 直接调用 | 通过信号/槽或主窗口转发通信 |
| 样式统一导入 | 使用 `COLORS`、`FONTS` 常量 |
| 串口资源独占 | 每个 Tab 独立实例化 `ModbusComm` |
| 清理逻辑自主负责 | 持有线程/定时器/串口的 Tab 自行实现 `cleanup()` |

## 核心模块说明

### BMS 监控 (`bms_monitor_tab.py`)

- 支持 L2/L3 两种协议模式，通过 `mode` 参数区分
- Modbus RTU 轮询采集寄存器数据，自动解析为物理值
- 寄存器视图：9 个寄存器/行，可拖拽调整上下比例（QSplitter）
- 信号名列左对齐，其余列居中（自定义 Delegate 绘制）
- 支持控制指令下发

### 协议配置 (`protocol_config_dialog.py`)

- 弹窗式编辑，占屏幕 65%，支持最大化
- 可编辑字段：信号名、地址、因子、偏移、单位、位长度
- 类型（uint8/uint16/int16/bitfield）由位长度自动推断，不可手动修改
- 修改过的单元格高亮显示（`#dbeafe`）
- 支持 Excel 协议文件导入，替换当前协议配置
- 用户配置存储在 `protocol_user_config.json`，仅保存与默认值不同的覆写

### 协议配置存储

```
protocol_user_config.json
├── L2
│   └── signals
│       └── SignalName
│           ├── factor: 0.1
│           ├── offset: -40
│           └── unit: "℃"
└── L3
    └── signals
        └── ...
```

L2/L3 配置分离存储，仅记录用户修改过的字段，未修改的字段使用 Excel 默认值。

## Git 提交规范

- `feat:` 新功能
- `fix:` 修复 bug
- `style:` 样式调整
- `refactor:` 重构
- `docs:` 文档更新
