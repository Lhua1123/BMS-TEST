# 阈值测试：DAPP_ThresholdSet 触发/解除协议

## 来源
2026-10-12 用实测 BLF（`D:\00.Yutend\96.测试报文\HD08_T191-测试阈值.blf`，手动触发成功）逐字节逆出来的。
代码和 DIC 参数表里都看不出时序与 Mode 语义，**别再靠猜**。

## 报文
- CAN ID `0x18D2FFDF` = `DAPP_ThresholdSet`，对内通道发
- 8 字节：`Addr_Target | PID(2) | Number+Mode | Data1..4`
- `Number` 1~5（低 4 位），`Mode` 在 byte3 的 bit4：`0x1N` → Mode=0，`0x11|0x12|...` → Mode=1
- 5 帧 × 4 字节 = 17 字节参数块，逐帧下发

## 17 字节布局（`threshold_engine._FIELD_*`）
```
idx:  0  1 | 2  3    4  5  | 6  | 7  8     9 10 | 11 | 12 13   14 15 | 16
      前缀 | L3触发 L3解除 | 旗 | L2触发  L2解除 | 旗 | L1触发  L1解除 | 旗
```
已用 F001/F002/F003 的 `threshold_hex` 对 `level1/2/3_threshold` 三次交叉验证。

## 四个关键点（缺一不可，现象都是「BMS 不报警」或「告警清不掉」）

1. **`DAPP_Threshold_Mode` 必须是 1（Manual Setting）**
   DBC：`0 "Program Setting" 1 "Manual Setting"`。发 0 等于让 BMS 用参数表原阈值，写进去的值不生效。
   对照：故障码注入用 `DAPP_FaultDetect_Mode=1`，同理。

2. **5 帧间隔约 1 秒，不能用故障注入的 50ms**
   实测 BLF 帧间隔 1.00~1.01s。50ms 是给 `DAPP_FaultSet`（单帧）调的，套到 5 帧参数块上 BMS 收不全。
   现用 `TimingConstants.THRESHOLD_FRAME_INTERVAL_MS = 500`（用户指定，实测可用）。

3. **触发值：`触发 == 解除 == 环境值 − 偏移×系数`（过高类）**
   系数 L1=3 / L2=2 / L3=1。两个字段写同一个值，且都落在实际值的**触发侧**。
   实测：实际 3332mV、触发=解除=3329 → `Level 1 Warning`。

4. **解除值：`触发 == 解除 == 环境值 + 偏移×系数`（过高类）**
   同样两字段同值，但落在实际值的**不触发侧**。
   反例：`触发=3335、解除=3329` 时实际 3332 落在两阈值死区 → 清警条件不成立、告警清不掉。

> 通用规则：**两字段写同值，靠数值在实际值的哪一侧决定置位/清零。**
> 过低类方向相反。迟滞关系（表里 L1 是 触发3455/解除3450）在测试路径下不适用。

## 环境值
`0x18B2FFA1` = `NBCMU01_VoltExtremeInfo`，读 `NBCMU01_SysCellVoltMax`（单位 mV）。
各 PID 的环境信号见 `参考资料/阈值测试备注.txt`。

## 恢复必须回读确认
只把解除帧发出去不算恢复成功。现由 `verifier.wait_signal_cleared()` 轮询对内告警位回到 0
（DBC VAL_ 里这些告警位一律 `0="Normal"`），未清零则 `THRESHOLD_RESTORE` 记失败。

## 关联文件
- `bms_alarm_test/engine/threshold_engine.py`：`_calc_level_value` / `_calc_release_value` / `_send_hex_as_5frames` / `_release_all_thresholds`
- `bms_alarm_test/config/constants.py`：`TimingConstants.THRESHOLD_FRAME_INTERVAL_MS`
- `bms_alarm_test/config/pid_table.py`：`PIDConfig.threshold_hex`（17 字节骨架，来自 DIC Excel HEX 列）
