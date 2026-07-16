# BMS测试工具整合版

统一界面，支持进制转换、CAN报文解析、L2-BMS监控、L3-BMS监控。

## 技术栈

- PyQt5 >= 5.15
- pyserial >= 4.0
- openpyxl >= 3.1
- pyperclip >= 1.8.2
- cantools >= 39.0.0, < 42.0.0

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 项目结构

```
BMS测试-整合版/
├── main.py                    # 入口，创建主窗口和所有tab
├── requirements.txt           # 依赖列表
├── shared/                    # 共享基础模块
│   ├── style.py              # 统一样式系统（颜色、字体、QSS）
│   ├── modbus_comm.py        # Modbus RTU串口通信
│   └── modbus_parser.py      # Modbus协议解析
├── convert_ascii/             # 进制转换与CAN解析核心库
│   ├── core/
│   │   └── converter.py      # ASCII/进制转换核心
│   ├── bms/
│   │   └── bms_formatter.py  # BMS数据格式化、DBC解码
│   └── gui/
│       └── styles.py         # Convert_ASCII原始样式（仅该模块使用）
└── tabs/                      # 每个tab独立封装
    ├── convert_ascii_tab.py  # 进制转换标签页
    ├── can_parser_tab.py     # CAN报文解析标签页
    └── bms_monitor_tab.py    # L2/L3 BMS监控标签页
```

## 架构约定

### Tab隔离原则

每个标签页都是**完全独立**的QWidget子类，满足：

- **类隔离**：每个tab独立类，无继承关系，互不引用
- **状态隔离**：每个tab在`__init__`中实例化自己的业务对象，不共享实例
- **样式隔离**：统一从`shared/style.py`导入`COLORS`/`FONTS`，不依赖全局样式副作用
- **关闭隔离**：`main.py`的`closeEvent`只对需要清理资源的tab（如`BmsMonitorTab`）调用特定清理方法

### 新增一个Tab的步骤

1. 在`tabs/`下创建新文件，如`tabs/my_feature_tab.py`
2. 实现一个继承自`QWidget`的类，在`__init__`中完成所有UI和业务对象初始化
3. 在`main.py`中：
   ```python
   from tabs.my_feature_tab import MyFeatureTab
   self.tab_widget.addTab(MyFeatureTab(), "我的功能")
   ```
4. **不需要修改任何现有tab的代码**

### 必须遵守的约定

| 约定 | 说明 |
|------|------|
| **禁止模块级全局单例** | 所有业务对象（通信器、解析器、定时器）必须在`__init__`中实例化，禁止在模块顶层创建全局实例 |
| **禁止跨tab直接调用** | Tab之间通过信号/槽或主窗口转发通信，禁止一个tab直接访问另一个tab的内部属性 |
| **样式统一从shared/style导入** | 使用`COLORS`、`FONTS`常量，保持视觉一致性 |
| **串口资源独占** | 如果新tab需要串口通信，自行实例化`ModbusComm`，不要与其他tab共享 |
| **清理逻辑自主负责** | 如果tab持有线程/定时器/串口等资源，自行实现`cleanup()`方法，并在`main.py`的`closeEvent`中注册 |

### 共享模块使用规范

- `shared/style.py`：所有tab的样式来源，新增颜色/字体常量需在此处定义
- `shared/modbus_comm.py`：串口通信封装，按需导入，每个tab独立实例化
- `convert_ascii/`：进制转换和CAN解析核心库，被`convert_ascii_tab`和`can_parser_tab`共享，修改时需确保不影响两者

## 现有Tab说明

| Tab | 文件 | 核心功能 | 依赖 |
|------|------|----------|------|
| 进制转换 | `tabs/convert_ascii_tab.py` | 二进制/八进制/十进制/十六进制/字符串互转 | `convert_ascii/core/converter.py` |
| CAN报文解析 | `tabs/can_parser_tab.py` | CAN ID解析、数据帧解析、DBC文件导入解码 | `convert_ascii/bms/bms_formatter.py` |
| L2-BMS监控 | `tabs/bms_monitor_tab.py` | Modbus RTU轮询、寄存器监控、控制指令 | `shared/modbus_comm.py` |
| L3-BMS监控 | `tabs/bms_monitor_tab.py` | 同L2，不同协议配置 | `shared/modbus_comm.py` |

## Git提交规范

- `feat:` 新功能
- `fix:` 修复bug
- `style:` 样式调整
- `refactor:` 重构
- `docs:` 文档更新
