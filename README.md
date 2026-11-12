# Chiplet Floorplanning

**当前主线：布局搜索与算法对比。** 物理模型以表达关键现象、支持一致的布局比较为目标，
不再把实测校准或完整制造签核作为算法实验的前提。
[首轮 HiTS 搜索对比](docs/tap-algorithm-reference-results.md) 已完成：77 个有限域热代表、
360 次等预算随机搜索／局部搜索／模拟退火回放。已观察到温度与通信距离代理的 Pareto 权衡，
但尚无稳定占优的方法。下一步是多案例、大域在线搜索与消融实验。

[三案例热敏感度诊断](docs/tap-sensitivity-results.md) 已完成 81 次本地求解：
每案例预选 20 个大域布局，Ascend／Micro150／MultiGPU 的抽样峰温跨度分别为
1.74／15.16／8.33°C。Ascend 原小域冷热差的约 98.9% 来自其他芯粒的热贡献变化；
不能用这一个弱敏感案例代表所有工作负载，也不能将抽样范围称作算法优化收益。

[合法移动结构与消融](docs/tap-search-structure-results.md) 已独立复核：小域中单独移动／旋转
会形成三个不连通区域，联合移动恢复连通；1,155 次全起点回放显示命中率改善，但随机搜索
仍有更好的最坏误差。该结构尚未证明适用于完整大域，也不是新算法贡献。

[在线基线协议](docs/tap-online-protocol.md) 已实现同域 Random／多权重 SA／NSGA-II，
共同的 16 个初始化查询计入 64 次预算。[本地烟测](docs/tap-online-smoke.md) 已验证
160 次 HiTS 查询并补做随机序列分离回归；完整三案例五种子试跑仍待协议审核后启动。

当前异温 Fabric 验证已按有限范围结束：三个固定布局与路由的 96 项逐路径
比较及 6 项最差窗口比较均未发生冷热排序反转，其中 85 项逐路径比较可分辨
非零温度交互。这是被测模型内的条件性结果，不是真实封装签核或联合优化优势。
见 [三布局结果与不确定性](docs/xyce-three-layout-results.md)。后续转向
[独立位置与旋转的 TAP 几何域](docs/tap-geometry-domains.md)及有限封装资源问题；
完整物理基准和新算法必要性仍未建立。

热评估现采用 [冻结的 TAP 有限体积研究模型](docs/tap-fv-contract.md)，由现有组装器和 HiTS 本地求解。
[三个完整案例的数值准入](docs/tap-fv-admission.md) 已通过；这不是实测校准或 HotSpot 原温度复现。
固定 HotSpot 7 Detailed-3D 的 [内部边界问题](docs/tap-native-boundary-audit.md) 保留为拒绝证据，
[Chat 审核](docs/tap-boundary-chat-review.md) 已确认该原生边界问题。
新增 [有限资源图的路由覆盖证据](docs/tap-global-routing-results.md)：冻结域中 77 个热等价类均有整数路由见证，
因此该粗粒度图模型内的最优热代价为零；详细逃逸、轨道分配、PHY 与回流仍未验证。

此前建立的评估平台见 [Goal 01：统一电热布局决策](docs/goal01-integrated-decision.md)。
新的 `evaluate(layout, configuration)` 已接通 3 芯粒、8 Lane、显式 Pin 旋转、
有限共享布线、分层热场、唯一导体 SPEF 和同工艺 SKY130 核心单元全路径 STA。
这是封装参数仍为假设的机制实验；真实 Pad 表征及实物结论尚未闭合。
首个 [完整决策基准](docs/integrated-decision-results.md) 已完成 96 个固定组合：
补充合法布线见证后，4 组条件均证明该离散模型内 ΔT=0；未发现联合优化必要性。
新增 [三个完整候选的 SPICE/STA 差分对照](docs/paired-transistor-layouts.md)：
常温下所有已测路径的排序方向一致，但这不是热场反馈或真实 Pad 校准。
[局部晶体管温度能力检查](docs/local-temperature-capability.md) 保留失败证据；
[STA 超时处理](docs/sta-execution-status.md) 将未完成分析明确记录为未知。

面向 2.5D chiplet 布局的 Power–Thermal–Timing 评估项目。当前版本 **v0.8.0**
支持分层热网络、MFIT 数值对照、几何 RC/SPEF、真实 SKY130/GF180 库时序、
25 组核心单元 PVT 组合，以及逐实例局部温度到时序的实验性耦合。
新增 **GF180 发送 → SKY130 接收**的真实 3.3 V GPIO 源同步原型，
50 MHz、假设 3 mm 封装线下通过声明的时序、电气和 pad 查表范围检查。
原 SKY130→GF180 方向的 slew 超限仍作为失败对照保留。
实物校准、全 PVT、pad/PHY 资格验证、温度插值的独立物理验证仍未完成。

v0.6 新增同一 GPIO 模式的晶体管波形诊断与 GF180 温度扫描。
步长收敛通过，但两端常温波形均未通过原 Liberty 一致性门槛；
SKY130 源网表还存在可达空子电路。因此 **pad 温度模型尚未接入正式 STA**。
详细数据与阻断原因见 [v0.6 验证记录](docs/validation-v06.md)。

v0.7 固定同一组 27 个布局，对比经过单层几何检查的不同 data/clock 路由。
原 corridor 的本地 121 个指标冲突对被复现（CI 构建为 115 对，说明极小差异的
排序依赖构建）；最短合法连接下 setup 的全候选变化仅
0.007 ps。所有可评估策略均选中 layout 26 作为时序可行的最低温候选，
当前 50 MHz 假设下**尚未建立联合优化的必要性**。见 [v0.7 记录](docs/validation-v07.md)。

v0.8 完成 E1 热源贡献分解：保持两颗 die 的材料结构，独立求解总功率、TX-only、
RX-only。整体平移 00→24 降温 1.565 K，其中 TX 贡献减少 1.521 K；但 RX
在热点处仍贡献约 10 K，不能说热耦合可忽略。六组散热/TIM 假设表明排序依赖
边界与材料；低导热率 TIM 下 20/26 排序反转，20/23 尚未被网格变化筛选区分。
这仍是线性模型内的数值证据，E2 真实布线资源与 E3 时序约束必要性尚未验证。
见 [v0.8 结果、误差与复现](docs/validation-v08.md)。

Windows 本地现已跑通热计算、锁定 OpenSTA 和真实 TT GPIO 原型；新增独立的
源同步时序语义验收，覆盖边沿、反相器传播、early/late、setup/hold 负例与约束缺失。
这验证合成模型的时序语义，未关闭 pad 物理一致性问题。
见 [Windows 运行入口与本轮证据](docs/windows-local.md)。

本项目遵循：**验证输入 → 验证评估器 → 验证布局差异 → 开始优化**。
内置两芯粒例子的功耗与封装几何为演示假设；开源案例保留其声明输入。公开来源与数值一致性均不代表实物校准。

本地实测进展：已锁定 TTC 作者的真实 heater/sensor 几何和区间结束比较约定，
完成 26 组原始记录的三种读数算子对照。事件峰值对时标敏感，长期偏差仍在；
没有启用生产物理校准。见 [TTC 观测审计](docs/ttc-observation-results.md)
和 [十项研究证据门槛](docs/research-gates.md)。
后续 [真实几何空间实验](docs/ttc-spatial-results.md) 已完成：固定参数下未通过
空间误差改善门槛，并发现约 1.7 K 的主网格/连续体差异。新增独立分层连续体
参考与无新增拟合的测点差温诊断，负结果保留；135 项测试通过不等于物理校准。

## 快速开始

需要 Python 3.10+。使用独立环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
chiplet-floorplanning validate examples/two_chiplets.json
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two_chiplets
python -m unittest discover -s tests -p '*_unittest.py' -v
```

每次评估使用一个新的输出目录，避免覆盖已有结果。输出为：

| 文件 | 内容 |
| --- | --- |
| `input.json` | 本次实际使用的输入快照；统一排序便于比较 |
| `grid.csv` | 单元中心坐标、功率 W、功率密度 W/mm²、温度 °C |
| `report.json` | 功率守恒、热平衡、温度统计、接口距离和 RC、验证状态、输入哈希及软件版本 |

报告在其他文件写入完成后生成。未提供 STA 输入时，`timing.status` 为 `not_run`，slack 为
`null`。提供完整模型时，slack 来自真实 STA 路径；`thermal.calibration` 仍为 `not_calibrated`。
从源码目录运行时记录 Git commit 与 dirty 状态；从独立 wheel 运行时源码提交可能未知。

## 已经实现

- 独立 die 侧壁默认隔热、显式成对接触热阻、逐 die 导热率和偏移矩形材料层。
- 保留全部被动材料的逐 die 热源贡献、同一热点采样、全节点叠加和封装旋转对称检查。
- 固定设计的位置 API、独立 data/clock 走线和 27 个候选布局排序实验。
- 声明单层上的有限线宽、间距、显式障碍与交叉检查；双线顺序寻路及有限路由组合比较。
- 约束优先的温度最优解、共同候选比较，以及网格、热矩阵、求解、SPEF、STA 分项计时。
- MFIT 三个原始几何/功耗案例、RapidChiplet 16-die 几何、PULP SDR PHY 和 OpenSTA 上游报告回归。
- 保持矩形芯粒坐标的贴合网格；非均匀有限体积、各向异性导热及显式界面热阻。
- 芯粒内连续温度重建、局部温度与 slack 网格收敛；不跨空隙插值。
- 可选显式直角折线，与旋转后端口核对；移动芯粒后拒绝过期走线端点。
- 严格 JSON 字段、有限数值、单位和来源文本检查；拒绝未知字段、重复键和无效端点。
- chiplet 越界、重叠检查；局部块范围检查；0/90/180/270° 旋转及接口变换。
- 将每个矩形块的均匀功率按面积交集分配到热网格；逐块检查功率守恒。
- 均匀薄板、绝热侧面、分布式对环境散热条件下的稳态有限体积求解。
- interposer/bump/die/TIM/lid 分层导热、芯粒岛与空隙、半层热阻和顶/底对流边界。
- 固定版本 MFIT 网络组装对照、三档网格收敛和独立 ngspice RC 波形对照。
- 真实 SKY130→GF180 的 TT、25°C、1.8 V 核心单元链路，显式数据/时钟 SPEF 与反边沿采样。
- 5 个 SKY130 库工况 × 5 个 GF180 库工况，独立 die 工况组合；这不是完整 PVT 签核。
- 将热网格映射到 5 个实例，按固定工艺、电压的温度端点插值延迟、slew、setup/hold 表。
- 实际 pad 负载、模式引脚、跨库 slew 定义和电气上限检查；拒绝有电气超限的时序结果。
- 分别输出 data 和 forwarded-clock 端点间的曼哈顿距离及用户给定系数下的 R/C。
- 解析解、独立两节点热网络、旋转、非网格对齐功耗、异常输入与 CLI 验证；GitHub Actions。

两芯粒示例总功率为 **3 W**，data/clock 的曼哈顿距离均为 **3 mm**。
未给 `route_points_mm` 时距离是无障碍几何下界；给定折线时使用实际声明长度。
默认距离模型不验证路由；独立双线寻路器仅支持声明单层的有限几何规则，
尚无多 lane 资源容量、跨层/via、bump escape、bump 寄生或串扰模型。
I/O 块功耗由用户给定，当前不另加 link power，以避免重复计数。

## 模型和验证边界

保留 v0.1 的均匀薄板作为回归对照；`layered_package_steady` 则显式表示多层材料与芯粒岛。
MFIT 对照核验相同边界条件下的方程组装，未使用其 C 瞬态求解器，也不等价于实物温度验证。
现阶段的时序使用真实标准单元库和假设封装几何，内部连线采用显式零线负载；
未提供真实提取寄生、全 PVT signoff、瞬态热或温度相关漏电反馈。
默认分析仍将热结果与常温时序独立输出；显式开启温度模式后，才将局部温度
用于逐实例核心单元库。该模式固定为 SKY130 FF/1.65 V 与 GF180 FF/1.98 V，
没有合格的跨电压 pad 接口，不能代表已验证的物理 D2D 链路。

详见 [输入格式与物理假设](docs/model.md)、[分阶段路线](docs/roadmap.md)
和 [验证记录](docs/validation.md)。公开仓库仅包含源代码、合成输入和文档；
运行结果放在忽略的 `results/`，本机配置放在忽略的 `local/`。

## 真实库与封装验证复现

```bash
python -m pip install -e '.[validation]'
python tools/bootstrap_validation.py --build-sta
python tools/validate_package.py --output results/package-check
# ngspice needs to be installed separately; pass its executable path explicitly.
python tools/validate_electrical.py --ngspice /path/to/ngspice --output results/electrical-check
chiplet-floorplanning evaluate examples/layered_two_chiplets.json \
  --sta local/upstream/OpenSTA/app/sta \
  --sky-lib local/pdk/sky130_tt_1v8.lib --gf-lib local/pdk/gf180_tt_1v8.lib \
  --output results/integrated
```

OpenSTA 构建需要 C++ 编译器、CMake、Tcl 开发包、Flex、Bison、SWIG 和 zlib 开发包。
下载文件的版本与 SHA-256 固定在 `tools/sources.lock.json`；PDK 文件存于忽略的 `local/`。
详见 [v0.2 验收与边界](docs/validation-v02.md) 和[运行前验收计划](docs/validation-plan-v02.md)。

## PVT、pad 和局部温度复现

```bash
python tools/bootstrap_validation.py --build-sta
python tools/prepare_characterization.py
python tools/validate_characterization.py --output results/characterization
chiplet-floorplanning evaluate examples/layered_two_chiplets.json \
  --sta local/upstream/OpenSTA/app/sta \
  --temperature-model-root local/pdk-v03 \
  --instance-locations examples/lane_instances.json \
  --output results/local-temperature
```

实例位置是用于测试的 die 局部坐标（mm），并非真实布局提取结果。温度模式
保留芯粒旋转、原始库来源哈希、每个实例的温度/插值区间和独立数据/时钟路径。
不同温度表先在共同有效坐标范围重采样，再插值；禁止温度外推。
温度升高不必然增加每条弧的延迟，具体变化须由源库和实际路径解释。

验证脚本成功表示软件检查通过，**包含正确拒绝不合格 pad case**。
该 case 的 GF180 PAD slew 约 1.84 ns，超过库规定的 1.00 ns。
不能用正的 setup/hold 裕量宣称它可用。报告的 `qualification` 字段始终列明
未完成的物理校准、PVT、PHY 和温度插值验证；不会输出完整封装签核通过。

见 [v0.3 结果与负例](docs/validation-v03.md)、[验证计划与修订](docs/validation-plan-v03.md)
和[实物校准所需证据](docs/physical-calibration.md)。

## 参考工具

- [HISIM](https://github.com/mec-UMN/HISIM)：适用架构的分析式模型参考；尚未集成。
- [MFIT](https://github.com/AlishKanani/MFIT)：分层热网络的外部组装参考。
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA)：已接入真实库的核心单元链路时序。
- [PULP serial_link](https://github.com/pulp-platform/serial_link)：固定版本 SDR PHY 原始 RTL 的独立功能验证；尚未映射到 GPIO STA 案例。
- [RapidChiplet](https://github.com/spcl/rapidchiplet)：原始 16-die 布局、功耗与 PHY 端点转换验证。

本仓库没有复制上述项目源码或分发 PDK。后续接入时分别记录上游版本、许可证和模型来源。

## 低速源同步 GPIO 原型（v0.4）

```bash
python tools/bootstrap_validation.py --build-sta
python tools/prepare_characterization.py
chiplet-floorplanning evaluate examples/low_speed_gpio.json \
  --sta local/upstream/OpenSTA/app/sta \
  --sky-lib local/pdk/sky130_tt_1v8.lib \
  --gf-lib local/pdk-v03/gf_core_tt_3v3.lib \
  --sky-pad-lib local/pdk-v03/sky_io_tt_1v8_3v3.lib \
  --gf-pad-lib local/pdk-v03/gf_bi_t_tt_3v3_assembled.lib \
  --pad-direction gf180_to_sky130 --period-ns 20 \
  --output results/low-speed-gpio
python tools/validate_prototype.py --output results/prototype
```

发送核心为 GF180、3.3 V；接收核心为 SKY130、1.8 V，双方 I/O 均为 3.3 V。
数据在上升沿发出，随路时钟经接收反相器后在下降沿采样。固定模式见报告
`timing.interface`；真实接收缓冲器让 pad 输出负载落在原库表征范围内。

默认案例的 setup/hold 分别为 **8.705309 / 11.008110 ns**。这是 TT、25°C、
理想时钟、假设封装线和零片内线寄生下的模型结果。`timing_constraints_met`
与“分析成功”分别记录；2 ns 周期的负 setup 会正常报告失败。电气超限或 pad
查表越界则生成 `rejection.json` 并终止评估，保留日志，不生成成功报告。

本案例的晶体管级 pad 波形诊断尚未通过模型一致性门槛，完整协议仿真和实测校准也未完成；没有把常温 pad
与局部温度核心模型拼接成已验证的热链路。见 [v0.4 验证记录](docs/validation-v04.md)。

## 多开源案例与布局排序（v0.5）

```bash
python tools/bootstrap_validation.py --build-sta
OPENBLAS_NUM_THREADS=1 python tools/validate_open_thermal.py --output results/open-thermal
python tools/validate_sta_goldens.py --output results/sta-goldens
# Requires Verilator 5.020 or compatible version, GNU make and a C++ compiler.
python tools/validate_pulp_phy.py --verilator verilator --output results/pulp-phy
OPENBLAS_NUM_THREADS=1 python tools/validate_layout_ranking.py --output results/ranking
```

首轮 27 个几何合法布局中，20 个通过 TT GPIO 电气/时序检查，7 个因电气超限被拒绝。
热与常温时序目标确实出现数值可区分的排序冲突；部分 timing 最优布局相互并列。
这尚未证明局部温度改变了真实 pad 链路的排序，因此仍不进入 SA 优化阶段。
详见 [v0.5 实验、失败对照与复现](docs/validation-v05.md)。

`layout.place_design()` 接受固定设计、位置与每条 link 的独立走线走廊，返回新 Case；
`layout.evaluate_layout()` 可在内存中计算温度和互连，默认明确标注时序未评估。
此兼容接口本身不检查布线合法性；v0.7 的 `routing.audit_routes()` 单独执行几何检查。

## 布线反事实与约束必要性（v0.7）

```bash
# Reuse a fresh ranking report generated with the same STA executable/libraries.
OPENBLAS_NUM_THREADS=1 python tools/validate_routing_policies.py \
  --reference-ranking results/ranking/report.json --output results/routing-policies
```

`layout.relocate_design()` 移动芯粒并使旧路由失效；`routing.shortest_route_pairs()`
尝试两种布线顺序，`routing.with_routes()` 保留原输入并生成新的 Case。
`examples/planar_routing_contract.json` 声明 10 μm 线宽、10 μm 间距与边界净空，
允许 interposer 层在 die 下方走线；这些是实验假设，不是 PDK 布线规则。
交换 corridor 产生的同层短接在 STA 前被拒绝，没有默认添加跨线桥或第二信号层。

固定 TT25 GPIO 模型只提供几何时序对照。真实时序压力 benchmark 尚未获准，
热反馈时序及其成对差分仍为 `null`。单层几何通过不代表 bump escape、串扰、
封装 DRC 或物理签核通过。详见 [预先声明的实验条件](docs/validation-plan-v07.md)
和 [时序 benchmark 准入审查](docs/timing-benchmark-admission.md)。

## 独立热源与边界敏感性（v0.8 / E1）

完整数值集成：[共享时钟布线容量、唯一寄生与完整时序](docs/shared-routing-results.md)。
120 条数据 Lane 加一棵时钟树已连接到有限轨道资源、可复核的容量不足证明和 SPEF；
1,824 条带布线路径通过检查，169 项测试通过。真实封装规则、Pad/通道表征和热耦合
仍开放；首组更细热网格仍有约 0.98 K 温度变化，尚不能宣布空间收敛或物理校准。

多 Lane 基础能力：[共享时钟完整路径核对](docs/multilane-timing-results.md)。
本地覆盖 2/4/8/16 个 chiplet、最多 120 条数据 Lane，1,668 个路径结果与独立
边沿时间参考一致；错误接线、漏 Lane、时钟极性和负载控制均检出，157 项测试通过。
该人工延迟实验只验证共享时钟与路径记账，真实布线容量、Pad 和温度耦合仍未完成。

最新本地进展：[封装瞬态与储热检查](docs/ttc-package-transient-results.md)。
原始降阶失败已保留；补足快速扩散后，四种粗网格模型全部通过同网格数值控制，
26 个原生实测记录保留两种初态与三级阶数。大幅储热可以与近稳态差温并存；
细网格、真实边界与实物校准仍未完成。151 项测试通过，更细计算继续在本机运行。

进行中的下一阶段：[接触垫、铜底座和鳍片边界对照](docs/ttc-package-boundary-results.md)。
完整对齐三维热网络已建立，146 项测试通过；前两级边界效应仍未收敛，更细网格在本机计算。
实测自然冷却均温仍明显上升，空间差温稳定不能替代铜储热和完整瞬态验证。

最新数值进展：[TTC 稳态数值一致性](docs/ttc-numerical-closure-results.md)。
不修改材料或边界，联合加密横向与厚度网格，使 13 种功率图样、两组材料下
与独立连续体参考的最大差异从约 1.7 K 降至 0.020 K；140 项测试通过。
此结果只通过预定稳态数值门槛，原粗网格瞬态与真实 Pad/封装校准仍未获准。

最新本地进展见 [42 个时序参数配置与 4 个热输入案例](docs/local-multicase-results.md)：
两类电路的真实库契约、逐路径源表核对、定量时钟控制和失败分类。仅本机实验，
没有推送或触发远端 CI；数值一致性与物理校准分别报告。

后续 [Pad 模型诊断](docs/pad-diagnostic-results.md) 已在本机完成 48 次瞬态运行、
实际 STA 工作点与 17 对差分检查。已检查的测量定义与负载映射未消除不一致，
没有据此释放温度 pad 模型；原始波形、工具失败和模型失败分别保留。

表征来源审计见 [上游修正与物理必要条件](docs/pad-provenance-results.md)。
研究遵循 [物理准入契约](docs/physical-admission-contract.md)：区分守恒/被动性、
数值求解与真实系统校准。原始表征、PEX 和通道近似的适用性仍是未关闭的依赖。

最新进展见 [理想通道 RC/RLC 守恒与独立求解对照](docs/passive-channel-results.md)：
12 组条件的最终 96 条记录全部通过预声明数值检查，108 项软件测试通过；
早期波形误差、超时和中断仍完整保留。通道延迟差可正可负，不能统一加一个
飞行时间常数。该结果只完成理想模型的数值审计，真实 PHY/热反馈仍未获准。

公开实测进展见 [TTC 与高压晶体管测量对照](docs/measured-calibration-results.md)：
26 个真实热实验完成含储热的条件拟合与预定留出评估，108 组实际硅晶体管
曲线对照完成，119 项测试通过。原稳态方案因样本不满足准入而拒绝拟合；
原始失败保留。风扇组热容触及数值下限，事件时标与测量边界仍有歧义，
不能把平均误差或守恒通过当成真实物理参数已校准。完整 Pad、封装电气和
目标 chiplet 热边界保持未校准；本地提交，无远端推送。

```bash
python -m pip install -e '.[validation]'
OPENBLAS_NUM_THREADS=1 python tools/validate_thermal_decomposition.py \
  --output results/thermal-decomposition
```

无需 PDK 或 STA。运行 27 个布局 × 6 组散热/TIM 假设、两档 XY 网格；仅底部散热
对全部 27 个布局再加密一档。输出独立源温升场、完整报告、紧凑 `summary.json`
和 PNG/SVG 图。温升逐点相加，环境温度只加一次；不同热源各自的峰值不能相加。
`coldest_id` 是有限网格的原始最小值，同时输出网格变化筛选下未区分的候选。
时序明确为 `not_evaluated`，封装实测校准和完整签核保持 `false`。
