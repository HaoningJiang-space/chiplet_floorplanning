# 表征来源、上游修正与物理必要条件（2026-11-11）

从本地 `50046cb` 开始，成功 fetch 后远端仍为 `c124aa9`，无新 push。
本轮全部在本机执行，不推送、不触发远端 CI。
预声明条件见 [实验计划](pad-provenance-plan.md)，物理判断标准见
[物理准入契约](physical-admission-contract.md)。

完成 12 次新增 pad 瞬态、6 组半步长检查、1 个包含 11 个器件对照的直流实验、
4 个热学假设案例和 97 项软件测试。基础双 chiplet CLI 也通过，3 W 功率、
参考峰值 34.1886068 C，时序明确未运行。**原始表征未完整恢复，物理模型未准入。**

## 文件来源已经追到哪里

锁定 17 份来源，检查 5 棵完整源树和 3 份原安装归档：

| 固定来源 | 源树条目 | 未截断 |
| --- | ---: | --- |
| GF IO `2aeec51` | 536 | 是 |
| SKY IO `01b1869` | 295 | 是 |
| SKY IO 补充 PR5 `e2a521d` | 746 | 是 |
| open_pdks `fa87f8f` | 931 | 是 |
| skywater-pdk `f70d8ca` | 556 | 是 |

安装的 SKY IO SPICE 与 `fa87f8f` 的 custom 源文件逐字相同。
[补充 PR5](https://github.com/google/skywater-pdk-libs-sky130_fd_io/pull/5)
中的 TT 库与当前原时序库，在四处 library/cell/bus 名称替换后，完整文本一致。
这恢复了部分文件血缘，不能证明网表、PEX 与原始表征电路等价。

SKY 库头明确记录 `snps_predriver`、HSPICE H-2013.03、仿真选项和测量阈值。
这些标签并不提供驱动电路或完整输入波形。GF 库头给出 2014-07-31、revision 1.1，
但未给出 driver/simulator 字段。
[GF issue 11](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_io/issues/11)
的 2023 年维护者讨论说明 CDL 主要用于 LVS，当时未提供相应仿真网表。
语法转换不等于补齐原表征寄生。

本轮也查看了候选文档：锁定 skywater-pdk 的三个 PEX 工具页面为 TODO；
open_pdks 的 `characterize_help.txt` 是通用项目表征帮助，不是这两个 pad 的原始
表征输入。归档/树的关键词筛选只是发现线索，不能证明未命名内容不存在。
“未找到”限定在已记录来源和检查范围，不声称全网不存在。

仍未恢复的六项字段保持 `null`：原始 characterization deck、完整驱动波形、
负载参考面、提取网表与 PEX 配方、生成 Liberty 所用器件模型版本、原 HSPICE
复现。`condiode` 和 `com_pad` 两个可达空定义及模型警告也没有被删除。

## 有源依据的修正与多点对照

[上游 `11af1927` 提交](https://github.com/fossi-foundation/open-pdks/commit/11af1927d0866ecd23e7cd611c51aa8fc31e780d)
明确修正 `hvsbt_nor` 中两只 pFET 的数量。
采用已合入上游的 [完整参考 `2d935092`](https://github.com/fossi-foundation/open-pdks/blob/2d93509249763cb83dae021fd0dbf3c79e262f47/sky130/custom/sky130_fd_io/spice/sky130_fd_io.spice)：
当前 GPIO 可达的 95 个 IO 定义中，只有三个定义不同，且修正版本的这 95 个定义
与 PR5 相同。三个差异为 NOR 的 `m=1→2`、控制短接电阻的 L/W 补充、Pad 金属
电阻的 L/W 修正。其余源文件及所有原始模型保持不变。

比较 `nor_only` 和 `reachable_updates` 两种派生副本，各运行三个既有工作点、
5/2.5 ps 两档步长。旧基线六份波形复用前检查原文件哈希、仿真器及模型身份、
重新生成的逐字相同 deck，以及源定义重测结果。输出摘要又复核了全部新 deck、
日志、主波形、内部节点波形和派生网表的字节哈希。

以下采用三个可达块全部替换的细步结果，误差为相对原 Liberty 的绝对差：

| 工作点 | 上升延迟变化 / ps | 下降延迟变化 / ps | 剩余上升误差 / ps | 剩余下降误差 / ps |
| --- | ---: | ---: | ---: | ---: |
| 名义点 | -2.3632 | -0.0335 | 328.00 | 425.44 |
| STA rise anchor | -1.0387 | -0.0432 | 351.82 | 433.27 |
| STA fall anchor | -0.8977 | -0.0454 | 353.42 | 435.11 |

最大半步长指标变化 0.05843 ps；六个配置均通过既定数值检查，但 **0/6** 通过
四指标名义门槛 max(20 ps, 10%)。NOR-only 与全部替换的最大指标差仅
1.42e-14 ns，在这些测试中未区分。不能据此推出两组电阻在其他模式下都无作用。
下降延迟的微小变化还不能一概认为超过各自端点步长变化之和。逐指标经验筛查
已保存，不能将其当作严格数值误差界或物理误差界。

独立直流器件对照在同一模型/偏置下确认：单独改变 mult 不改变所用 pFET 电流，
m 加倍使电流加倍；金属电阻的 L/W 修改确实改变有效电阻。它不是全 PDK 乘数语义
证明，也不是物理表征。对照还保存了十个 NOR 实例的内部 `net16` 波形和父层位置；
内部节点幅度不能单独证明参与或未参与有效信号传播。

实验只检验这几个有来源的网表变化在当前模式/模型组合下的作用，不是完整 PDK
升级，更不是原始 characterization/PEX 的重现。原始模型警告、部分 gmin/source
初始化失败信息保留；最终波形和半步长检查通过没有消除模型适用性问题。

## 物理定律检查与真实系统验证分开

新增必要检查覆盖四个明确的热学条件：原边界、底部散热、双面散热和各向异性。
检查导热矩阵互易、非正非对角元、行和等于散热导纳、所有连通分量有散热通路、
局部/整体稳态功率平衡、非负温升。使用 Kelvin 计算内部和边界熵产生。
四例均通过，最大总功率平衡误差 2.5535e-13 W。

熵产生非负是所选被动网络的结构性结果，不能当成独立物理校准。手算两节点例
以及负导纳、非互易、未记账导纳、无散热孤岛的失败对照验证审计逻辑。
材料、TIM、散热边界、固定功率和实际结温之间的对应关系仍需外部证据。

同一理想平行板假设下，现有 3 mm 通道的 R=5.04 ohm、C=1.03594 pF，
外部电感量级约 0.37699 nH，理想 TEM 传播时间尺度 19.762 ps。
这揭示 RC 近似需检查的遗漏项，**不能判定 RC 已失效，也不能直接给 STA 加上
19.762 ps**。要结合输入边沿频谱、驱动阻抗、终端、回流路径与同一寄生归属。
完整 Pad 电荷/能量核查和真实通道校准也仍未完成。

## 复现与后续

`results/characterization-provenance/` 保存来源、原始波形与日志。最初一次启动因
Windows include 路径匹配失败，在任何仿真开始前终止；该目录保留，正式十二次
运行在 `revision-controls-v2/`。未将启动错误计作模型失败或有效样本。
紧凑证据见 `docs/evidence/local-pad-provenance.json`。

```powershell
. ./tools/windows_env.ps1
python tools/audit_pad_provenance.py --download --output results/characterization-provenance/provenance.json
python tools/validate_pad_revision.py --ngspice local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe --output results/characterization-provenance/revision-repro
python tools/validate_pad_device_semantics.py --ngspice local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe --output results/characterization-provenance/device-repro
python tools/audit_physical_invariants.py --output results/characterization-provenance/physical-invariants.json
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/characterization-provenance/basic-repro
```

依赖上一轮 `results/pad-diagnostic/matrix/report.json` 和锁定安装；新实验目录须
不存在。原库/模型的 bootstrap 与上一轮矩阵复现见之前的 pad 诊断文档。

通过 `codex-chatgpt-skill` 在[现有研究审核会话](https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865)
复核了来源追踪、对照设计和物理推理；采纳了参数语义、可达不等于有效传播、
复合修正归因、热网络结构不等于校准、RC 量级不能代替适用性判定等建议。
监督者未独立复现本机实验。

下一步先做同几何、同回流路径、同驱动和接收负载的 RC/RLC 独立机制对照，
建立电荷/能量记录和预声明的时序判定容差；原 Pad 表征依赖继续单列。
之后才能讨论时序约束是否改变热最优布局，不用优化器掩盖模型缺口。
