# 报警测试：对内失效状态（SysFailSta）读取问题

## 现象
报警测试中「对内失效状态」校验超时，报 `期望值=3, 实际值=None`；但监听缓存里一直有 `NBCMU01_SysFailSta: 3`。

## 根因（2026-09 已修复）
`verifier.py` 的 `_check_sys_fail_sta` 曾用回读配置里的通用信号名（`BMS_SysFailSta`，见 `can_readback_config.py` 的 `SysFailSta` 条目）**覆盖** DBC 真名（`NBCMU01_SysFailSta` / `SBCMU01_SysFailSta`）。
拿通用名查监听器缓存 → key 对不上 → 永远 None → 轮询超时。

- 对比：`_check_err_tab`、`_check_inner_specific` 直接用 DBC 名，所以一直正常。
- **验证配置（信号回读协议页）本身没有配错**，勿改配置来“绕”这个 bug。

## 修法（已落地）
- DBC 主读固定用默认具体名：`NBCMU{idx}_SysFailSta` / `SBCMU{idx}_SysFailSta`（报文 `WarningInfo1` / `WarningInfo`）。
- 回读配置仅作 `_wait_for_signal` 内 CAN ID 兜底：`readback_role="inner_sys_fail_sta"`, `readback_idx=idx`。
- idx 类型链路统一为 `Optional[Union[int, str]]`（`_get_dbc_index` 实际返回 str，如 `"01"`）。
- 对内/对外通道从 settings 读（`inner_channel=2`, `outer_channel=1`），不再写死 CH1/CH2。

## 遗留（未修，暂不影响）
- 回读配置 `SysFailSta` 的 `can_id=0x18B1FFA1`（96 故障码表）与实测硬件 `0x18A2F2F2` 可能不一致（见 summary.md）。
- 主读走 DBC 后不依赖该 ID；仅当 DBC 读失败走兜底时才会暴露。若需兜底可靠，用「注入报文设置」按实测核对。

## 验证方式
- 无真实测试套件：`python -m py_compile` + mock（`object.__new__(BMSVerifier)` 捕获 `_wait_for_signal` 参数）。
- 断言：NBCMU → `NBCMU01_SysFailSta` / `NBCMU01_WarningInfo1` / ch=2；SBCMU → `SBCMU01_*`。
- 2026-09-24 实机复测通过。

## 关联文件
- `bms_alarm_test/engine/verifier.py`：`_check_sys_fail_sta`, `_wait_for_signal`
- `bms_alarm_test/can/can_manager.py`：`read_signal`, `read_signal_via_readback`
- `bms_alarm_test/config/can_readback_config.py`：回读协议默认表
- `bms_alarm_test/config/settings.json`：通道角色
