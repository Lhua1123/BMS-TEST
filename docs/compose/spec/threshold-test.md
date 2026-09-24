---
feature: threshold-test
status: delivered
updated: 2026-09-18
branch: feature/threshold-test
commits: 84455c1212d82ec2321ec54bdba3d2b0ebee0823..working-tree
---

# 报警测试 — 阈值测试页

## Report

**What was built** — 在「报警测试」左侧导航增加「阈值测试」页：配置区（地址/域/测试类型/偏移/等待）、PID 列表（DIC Excel 全部使能等级，默认勾选）、开始/停止/单步与详情日志。引擎 `ThresholdTestEngine` 通过 `DAPP_ThresholdSet` 按环境实际值动态越限触发，回读完全复用 `BMSVerifier.verify_fault`（与故障码测试一致）。PID 表兼容 DIC 列名，Excel 已拷贝至 `resources/`。

**Verification** — `py_compile` 通过（engine/panel/tab/pid_table/constants）；系统 Python 导入 OK；`PIDTable.load_from_excel` → 25 PID / 75 等级行；环境信号名与 DBC 全名对齐并校验报文/信号存在；监听白名单动态扩展已实现；无 CAN 时 UI 冒烟通过、`start_test` 正确拒绝。

**Journey log**
- 失效 pyc 仅作接口/算法参考，未反编译入库。
- DIC Excel 与旧解析器列名不一致：增加别名；脏行/HEX 列导致覆盖，已加校验。
- 评审指出无前缀信号名 + 监听白名单空操作会使基线系统性失败；已改为 `NBCMU01_*`/`NBICU01_*` 全名并 `add_monitored_message`。
- 回读与故障码测试同路径是产品约定，勿另写验证逻辑。
- 本地产出在 `feature/threshold-test`，不自动 push。

## [S1] Problem

`BMS测试工具整合版` 的「报警测试」主 Tab 目前只有「故障码测试」和「测试报告」。业务需要通过 **PID 阈值越限** 触发 BMS 报警并做与故障码测试相同的回读判定，以覆盖阈值类场景。

现状缺口：

- `tabs/bms_alarm_test_tab.py` 导航未注册「阈值测试」
- `bms_alarm_test/ui/threshold_panel.py`、`bms_alarm_test/engine/threshold_engine.py` 源码缺失（仅存 `__pycache__`）
- `settings.json` 的 `pid_excel_path` 指向不存在的 `resources/DIC.BMS参数-原始.xlsx`
- 测试报告/落库/常量已预留 `threshold` 类型，但无页面与引擎产出数据

参考资料（只读依据）：

- `参考资料/功能描述.md` §4.4.4
- `参考资料/阈值测试备注.txt`（PID↔故障码、环境报文映射；**不**作为默认测试范围过滤）
- `参考资料/阈值测试模板.xlsx`（列表列结构参考）
- `参考资料/DIC.BMS参数-原始.xlsx`（PID 阈值权威数据源）
- 历史 pyc 文档字符串（接口与算法参考，不直接反编译入库）

## [S2] Design

### S2.1 产品行为

在「报警测试」左侧导航增加 **阈值测试**（key=`threshold`），布局与故障码测试同构：

- 左：测试配置 + PID 列表
- 右：测试控制 + 测试详情（实时日志 + 参数详情表）
- 顶部 CAN 连接栏与「一键清除」沿用现有 `BmsAlarmTestTab`，阈值页共享同一 `CANManager`

配置项：

| 控件 | 范围/取值 | 默认 |
|------|-----------|------|
| BMS 地址 | 1~255 | NBCMU=161 / SBCMU=177（与域联动） |
| 域类型 | NBCMU / SBCMU | NBCMU |
| 测试类型 | 上限测试 / 下限测试 / 上下限测试 | 上下限测试 |
| 阈值偏移 | 相对环境实际值的物理量偏移（单位随 PID） | 可配置，默认见实现常量 |
| 报警等待时间 | 1~60 s | 使用参数表成熟时间，可覆盖 |

PID 列表：

- 数据来自 `PIDTable` 加载的 DIC Excel，**默认展示全部使能 PID 等级行**
- 按 PID 分组，组内一级/二级/三级各一行（有阈值的等级）
- 列：选择 | PID | 名称 | 告警使能 | 确认时间 | 上限 | 下限 | 充放等级 | 精度 | 状态 | 设置故障 | 清除故障
- 全选 / 全不选 / 反选 / 刷新 / 搜索
- 测试类型切换时按 PID 报警方向过滤列表可见性（不删除数据）
- 状态列：待测试 / 成功 / 失败（测试中可更新）
- 「设置故障 / 清除故障」：对该 PID 通过阈值路径手动触发/恢复（后台线程）

控制：

- 开始阈值测试 / 停止 / 单步（单个 PID 完整流程）
- 进度条 + 进度标签
- 未连接 CAN 时禁止启动，日志提示
- 测试完成刷新测试报告页（`test_completed` 信号，与故障码测试相同模式）

### S2.2 核心原则：回读与故障码测试一致

**验证/回读逻辑与故障码测试完全同一套；仅「触发故障」与「恢复」路径不同。**

```text
故障码测试:  DAPP_FaultSet 注入 ──► BMSVerifier.verify_fault ──► DAPP_FaultSet 清除
阈值测试:    DAPP_ThresholdSet 越限 ──► BMSVerifier.verify_fault ──► 阈值解除/恢复
```

共用组件（禁止复制实现）：

- `bms_alarm_test.engine.verifier.BMSVerifier.verify_fault(fault, target_address, domain, read_outer=...)`
- 对内：SysFailSta + ErrTab + specific
- 对外：NBCMU → outer SysFailSta / specific / Warning；SBCMU → specific
- `CANManager.read_signal` / `wait_for_signal` / `send_message`
- `FaultMapping` 取 `Fault` 对象
- `TestResult` / `Check` / `CheckType.THRESHOLD_*` / `CheckStatus`
- `TestLogger` 落库，`test_type="threshold"`

PID 等级 → 故障码映射：使用 `PIDConfig` 已有等级与故障码关联（与 `pid_table.py` / Excel 一致）；`参考资料/阈值测试备注.txt` 作人工对照，不另建平行映射表。

### S2.3 阈值触发算法（与故障码测试不同的部分）

对每个选中的 PID（`0xF001` 表示该 PID 全部使能等级；支持 `0xF001:2` 单级）：

1. **读环境实际值 baseline**  
   按 PID 类型从对内/相关 CAN 报文读取（单体电压极值、压差、模块/簇总压、温差、SOC/SOH、供电电压、环境温度、S 板温度等）。环境报文需动态加入监听监控列表。

2. **计算测试阈值**（标准 BMS 触发方向）  
   - 过高类（电压/温度/电流过高）：测试阈值 = 实际值 − n×偏移（阈值低于实际值才触发）  
   - 过低类（电压/温度/SOC 过低）：测试阈值 = 实际值 + n×偏移  
   - 三级动态：一级 n=3，二级 n=2，三级 n=1（相对偏移系数）  
   - 偏移为物理量，单位随 PID 精度单位

3. **下发阈值**  
   - CAN ID：`DAPP_ThresholdSet` = `0x18D2FFDF`  
   - 优先使用 Excel HEX 列 17 字节参数帧，改写对应等级的触发阈值字段后按 5 帧时序发送  
   - 发送时序复用 `TimingConstants` 中阈值相关常量；缺失 HEX17 时该 PID 级记失败/数据不全，不进入回读

4. **等待成熟**  
   使用参数表成熟时间或配置的报警等待时间。

5. **回读验证（与故障码测试一致）**  
   `verifier.verify_fault(mapped_fault, target_address, domain)`。  
   `TestResult` 额外可记录：PID、等级、环境实际值、设置阈值、解除值（metadata 或前置 Check）。

6. **恢复**  
   - 解除方向与触发相反：过高类解除 ≈ 实际值 + n×偏移；过低类 ≈ 实际值 − n×偏移  
   - 或按参数表原值发送完整 5 帧恢复  
   - 恢复失败记入 `THRESHOLD_RESTORE` 检查项；必要时可再走故障码清码路径清理残留

### S2.4 模块与接口

新建：

| 文件 | 职责 |
|------|------|
| `bms_alarm_test/engine/threshold_engine.py` | 阈值测试引擎 |
| `bms_alarm_test/ui/threshold_panel.py` | 阈值测试面板 |

修改：

| 文件 | 变更 |
|------|------|
| `tabs/bms_alarm_test_tab.py` | 导航增加「阈值测试」；`_create_pages` 装配 `PIDTable` + `ThresholdTestEngine` + `ThresholdTestPanel`；报告刷新连接 |
| `bms_alarm_test/config/settings.json` | `pid_excel_path` 指向 resources 下 DIC 文件 |

数据文件：

- 将 `参考资料/DIC.BMS参数-原始.xlsx` **复制**到 `bms_alarm_test/resources/DIC.BMS参数-原始.xlsx`，settings 使用该路径（与 DBC/故障表一致）

`ThresholdTestEngine` 对外接口（对齐历史 pyc，便于面板回调）：

```text
__init__(can_manager, pid_table, fault_mapping)
start_test(pid_codes, target_address, domain, test_type, offset_value, alarm_wait_time_sec) -> bool
run_single_pid(...) -> Optional[TestResult]
stop_test() / wait_for_completion(timeout_sec) / get_progress()
set_callbacks(on_progress_update, on_test_result, on_test_complete)
set_fault_by_threshold(...) / clear_fault_by_threshold(...)
reset()
```

`ThresholdTestPanel`：

```text
__init__(pid_table, parent=None)
set_threshold_engine(engine) / set_test_logger(logger)
信号：test_completed(list)  # 供主 Tab 刷新报告
```

装配（`bms_alarm_test_tab._create_pages`）：

```text
PIDTable 加载 settings.get_pid_excel_path()
ThresholdTestEngine(can_manager, pid_table, fault_mapping)
ThresholdTestPanel(pid_table)
panel.set_threshold_engine(engine)
panel.set_test_logger(test_logger)
stack.addWidget(panel)  # 导航 index 对应 threshold
```

### S2.5 通道与监控

- 发送阈值设置：对内通道（`settings.get_inner_channel()`，与故障注入同通道习惯）
- 回读验证：完全走 `BMSVerifier` 的对内/对外通道约定
- 环境值读取：引擎启动相关 PID 测试前，将所需环境报文 ID 动态加入监听监控；测试结束可恢复/清理

### S2.6 结果与报告

- 每个 PID 等级一条 `TestResult`（或每 PID 聚合、checks 内含各等级——实现取「每等级一条」便于报告明细）
- `test_type="threshold"`，名称含 PID 与等级
- `TestLogger.save` 供报告页过滤「阈值测试」
- 失败原因区分：环境值读取失败 / 阈值下发失败 / 验证未通过 / 恢复失败 / CAN 未连接 / 数据不全

### S2.7 工作区约定（项目覆盖）

- 分支：本地 `feature/threshold-test`
- **不创建** `.worktrees/`（用户要求：在当前目录用分支做本地区分；功能验证成功后由用户自行推送 git，agent 不 push）
- 基线：`84455c1`（创建分支时 HEAD）；工作区可能含 master 上未提交的 WIP 文件，实现时只改动本规格列出的文件，不顺手重构无关模块

## [S3] Out of Scope

- 不修改故障码测试的注入/验证算法与 `FaultTestEngine` 核心逻辑（仅复用）
- 不按 `阈值测试备注.txt` 默认缩小测试范围（备注中「不测」PID 仍出现在列表且默认可选）
- 不反编译 pyc 作为正式源码入库
- 不自动 push / 不创建 PR
- 不改 L2/L3 Modbus 监控、进制转换、CAN 解析等其他 Tab
- 不解决 `summary.md` 中故障 96 等硬件-DBC 历史不一致问题（环境值读不到时该 PID 级失败并记日志）
- 报告导出格式增强、协议配置弹窗问题（ISSUES.md）不在本特性内

## Tasks

- [x] T1: 修正 PID Excel 数据源 — acceptance: `resources/DIC.BMS参数-原始.xlsx` 存在，`settings.json` 的 `pid_excel_path` 指向该文件，`PIDTable` 能加载使能 PID（covers: S2.4）
- [x] T2: 实现 `ThresholdTestEngine` — acceptance: start/stop/单步/回调；触发 DAPP_ThresholdSet；验证调用 `BMSVerifier.verify_fault`；`test_type=threshold`（covers: S2.2; S2.3; S2.4; S2.6）
- [x] T3: 实现 `ThresholdTestPanel` UI — acceptance: 配置/PID 列表/控制/详情齐全；默认全部使能 PID；未连接 CAN 不能开测（covers: S2.1; S2.4）
- [x] T4: 接入报警测试导航与报告 — acceptance: 导航含阈值测试；装配成功；完成后报告可刷新（covers: S2.1; S2.4; S2.6）
- [x] T5: 环境值读取与监控 ID 扩展 — acceptance: 按 PID 类型读 baseline；信号名与 DBC 一致；`add_monitored_message` 扩展白名单；读失败该级失败不卡死（covers: S2.3; S2.5）
- [x] T6: 静态与导入验证 — acceptance: 语法/导入/PID 加载/环境信号映射冒烟通过（covers: S2.1; S2.4）
