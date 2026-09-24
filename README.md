# BMS测试工具整合版

基于 PyQt5 的 BMS（电池管理系统）测试工具，统一界面集成进制转换、CAN报文解析、L2/L3 BMS寄存器监控与协议配置编辑。

## 功能概览

| Tab | 核心功能 |
|-----|---------|
| **进制转换** | 二进制/八进制/十进制/十六进制/ASCII 互转，一键复制 |
| **CAN报文解析** | CAN ID 解析、数据帧解析、DBC 文件导入解码 |
| **BMS监控(L2/L3)** | 单个监控 Tab，左侧下拉切换 L2/L3 架构，Modbus RTU 轮询、寄存器实时监控、信号物理值解析、控制指令 |
| **报警测试** | 故障码测试、阈值测试、测试报告 |
| **协议核对** | 以 Excel 接收模板为标准，对离线 asc/blf 或实时 ZLG 报文做 ID/DLC/信号可解码自动核对 |

### 协议核对功能说明

- **判断标准**：内置编辑器生成的接收模板；可从 **DBC 导入** 或 **Excel 导入**，编辑后保存
- **DBC 导入**：默认将文档 ID `&0x1FFFFFFF` 映射为总线 ID（如 `0x98A3FFA1`→`0x18A3FFA1`）；「必须出现」默认否，由测试范围手改
- **内置编辑器**：中栏可改报文 ID/名称/DLC/是否必须；选中报文后可增删信号；支持「按实报补齐缺失 ID」
- **报文来源**：离线 `.asc`/`.blf`/宽松 HEX `.txt`，或 ZLG 通道+波特率实时采集
- **核对规则**：协议外 ID、必须出现但缺失、DLC 不一致、信号位段无法解码（Intel/Motorola 按 DBC 规则）
- **界面**：左=模板/设备，中=编辑器，右=实报统计，底=异常列表
- **新增代码**：`protocol_check/` + `tabs/protocol_check_tab.py`

### 协议配置功能说明

- **可编辑字段**：地址、起始位、结束位、长度、精度(因子)、偏移、单位
- **自动联动**：起始位、结束位、长度 三值联动（改起始位→自动更新结束位；改结束位→自动更新长度；改长度→自动更新结束位）
- **只读字段**：信号名、类型（自动推断）
- **导入协议**：支持导入新 Excel 协议文件，替换当前协议配置（持久化保存，重启后仍有效）
- **恢复默认**：清除所有用户修改，回到启动时的初始协议配置
- **用户配置存储**：`protocol_user_config.json`，仅保存与默认值不同的字段，L2/L3 分离存储

### 协议配置存储

```
protocol_user_config.json
├── L2
│   └── signals
│       └── SignalName
│           ├── addr: 21
│           ├── bit_start: 0
│           ├── bit_length: 16
│           ├── factor: 0.1
│           ├── offset: -40
│           └── unit: "℃"
└── L3
    └── signals
        └── ...
```

仅记录用户修改过的字段，未修改的字段使用协议默认值。

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
│   ├── bms_alarm_test_tab.py      # 报警测试标签页
│   ├── protocol_check_tab.py      # 协议核对标签页
│   └── protocol_config_dialog.py  # 协议配置编辑弹窗
│
├── protocol_check/                 # CAN 协议核对引擎
│   ├── models.py                  # 帧/模板/异常模型
│   ├── excel_template.py          # Excel 接收模板读写
│   ├── log_parser.py              # ASC/BLF/HEX 解析
│   ├── checker.py                 # ID/DLC/信号核对
│   └── zlg_live.py                # ZLG 实时采集（独立开关）
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

- 单个 Tab 支持 L2/L3 两种架构，左侧"架构类型"下拉即时切换（自动断开连接、重载协议、重建信号表格）
- Modbus RTU 轮询采集寄存器数据，自动解析为物理值
- 寄存器视图：9 个寄存器/行，可拖拽调整上下比例（QSplitter）
- 信号名列左对齐，其余列居中（自定义 Delegate 绘制）
- 支持控制指令下发

### 协议配置 (`protocol_config_dialog.py`)

- 弹窗式编辑，占屏幕 65%，支持最大化
- **9列表格展示**：信号名、地址、起始位、结束位、长度、精度、偏移、单位、类型
- 按地址升序排列，所有列居中对齐
- 修改过的单元格高亮显示（`#dbeafe`）
- 支持 Excel 协议文件导入，替换当前协议配置（持久化保存）
- 点击"恢复默认"清除所有用户修改，回到初始协议配置

### 协议配置存储

```
protocol_user_config.json
├── L2
│   └── signals
│       └── SignalName
│           ├── addr: 21
│           ├── bit_start: 0
│           ├── bit_length: 16
│           ├── factor: 0.1
│           ├── offset: -40
│           └── unit: "℃"
└── L3
    └── signals
        └── ...
```

L2/L3 配置分离存储，仅记录用户修改过的字段，未修改的字段使用协议默认值。

## Git 提交规范

- `feat:` 新功能
- `fix:` 修复 bug
- `style:` 样式调整
- `refactor:` 重构
- `docs:` 文档更新
