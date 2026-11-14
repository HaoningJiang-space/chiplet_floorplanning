# 真实接口时序链：IHP 130 nm 串行链路（草案，未冻结）

目的：在少量**固定布局**上接通
空间温度 → 器件局部温度 → 数据与时钟路径 → 早/晚到达 → setup/hold 裕量。
这是机制验证，不是优化目标；在两项一致性门槛通过前，不给出任何“真实时序达标”的结论。

## 来源（固定版本）

| 项目 | 来源 | 用途 |
| --- | --- | --- |
| 接口与约束 | `pulp-platform/cheshire-ihp130-o` @ `560f00f`，`basilisk.sdc`、`basilisk_io.tcl`、`mc_pad.sv` | 时钟关系、负载、不确定度、Pad 类型 |
| 器件与单元 | `IHP-GmbH/IHP-Open-PDK` @ `e73adb4`：PSP103 Verilog-A、`cornerMOSlv/hv.lib`、`sg13g2_stdcell.spice`、`sg13g2_io.spice` 及其 Liberty | 晶体管级仿真与一致性对照 |
| 编译与仿真 | OpenVAF-Reloaded `v24.0.2mob`（在 eex005 上以 conda-forge LLVM 18.1.8 源码编译）；ngspice 46 | PSP103 → OSDI；瞬态仿真 |

Basilisk SDC 中与串行链路相关的约束：系统周期 11 ns；串行时钟为系统时钟四分频（44 ns），
发送数据生成时钟取系统边沿 {1 5 9}，转发时钟取 {3 7 11}，即四分之一周期（90°）相位关系（注释称最坏情况）；
串行输出负载 4–16 pF；时钟不确定度 0.1 ns。这不是历史演示链路的半周期采样假设。

## 已知不匹配与声明的替代

- Basilisk 串行链路使用 `ixc013_b16m`（双向）与 `ixc013_i16x`（输入）Pad，仓库只提供它们的 Liberty、LEF
  与行为模型（`pdk/future/sg13g2_iocell`），**没有晶体管网表**。
- 开源 PDK 提供带 SPICE 网表的 `sg13g2_IOPadInOut16mA`、`sg13g2_IOPadOut16mA`、`sg13g2_IOPadIn`。
  本链路以它们**替代**原 Pad，这是声明的适配，不是 Basilisk 原电路。
- IHP Liberty 角同时改变工艺、电压与温度（typ 1.2 V 25 °C；slow 1.08 V 125 °C；fast 1.32 V −40 °C），
  不能用角间插值得到温度效应。温度效应只由**固定典型工艺与电压、只改变温度**的晶体管级仿真给出。

## 链路结构（拟定）

发送端：标准单元触发器（发射）→ 驱动 → 输出 Pad；转发时钟走同类路径。
通道：两颗芯粒 pin 之间的封装/中介层走线，长度取所选 ATPlace 网络在该布局下的两端 pin Manhattan 距离
（下界），单位长度 R/C 为声明假设，需给出来源或做敏感性分析；接收端加输入 Pad 的输入电容。
接收端：输入 Pad → 采样触发器，由转发时钟采样。
端点映射：在案例中选定一条跨芯粒网络，把发送/接收端放在其两个 pin 的位置，温度取该位置所在芯粒的局部温度。
这一映射是本项目的声明，ATPlace 的芯粒不是 IHP 设计。

## 裕量定义

按协议确定发射与采样边沿后，逐通道：

S_setup = t_capture,early − t_data,late − t_setup − U_setup
S_hold  = t_data,early − t_capture,late − t_hold − U_hold

数据与时钟共同增加的延迟会相互抵消，只有差分变化直接改变窗口，所以升温不必然单调缩小所有窗口。
接收触发器的 setup/hold 须在同一温度与工作条件下独立表征，不能沿用未扣除约束的窗口。

## 进入结论前的门槛

1. 一致性：典型角 25 °C 下，自行晶体管级仿真的单元/Pad 延迟与开源 Liberty 相符（门槛在看到结果前写定）。
2. 替代偏差：开源 Pad 与 `ixc013` 原 Pad 在相同负载下的典型角 Liberty 延迟差，作为替代误差如实报告。
3. 数值：时间步长与收敛性检查。
4. 物理：温度扫描下延迟随温度的变化方向与量级合理；不外推到仿真温度范围之外。

## 当前状态

- eex005：IHP PDK 必要子集已按 `e73adb4` 取到 `local/ihp/`；openvaf-r 发布版需 glibc 2.39，本机 2.28，
  Docker Hub 不可达，因此改为源码编译（进行中）。
- 尚未运行任何晶体管级仿真；以上链路结构与端点映射仍是草案。
