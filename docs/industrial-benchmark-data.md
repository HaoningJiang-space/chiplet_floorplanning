# 工业级基准：公开产品数据核查（2026-11-16）

目的：判断能否用真实产品数据构造"工业级"芯粒布局基准，以及哪些数字是官方、实测或估计的。只用公开来源。

## 数据可得性总表

| 量 | H100 SXM | B200 | EPYC 9654（Genoa） | HBM3/3E 堆叠 |
| --- | --- | --- | --- | --- |
| 芯粒面积 | **官方**：GH100 814 mm²（另有实测 822.9 mm²，含划片道） | 未公开；估计每颗约 800 mm²（另有一来源称约 460 mm²，与"双芯粒、光罩尺寸"矛盾） | **泄露/实测**：CCD 10.70×6.75 mm（72.2 mm²）；IOD 24.79×16.0 mm（396.6 mm²），另一实测 26.08×16.07 mm（419.1 mm²） | **二手**：约 11×11 mm（121 mm²），高 720 µm（HBM3 上限） |
| 芯粒长宽 | **未找到**（只有面积；光罩上限 26×33 mm） | 未找到 | 见上（实测） | 见上 |
| 中介层或基板尺寸 | **估计**：中介层约 2,350–2,500 mm²（约 3× 光罩） | 未公开（CoWoS-L，带 LSI 桥） | **泄露**：基板 72.0×75.4 mm（5,428 mm²），有机基板，不是硅中介层 | — |
| 排布 | **照片可见**：GPU 居中，6 个 HBM 两侧各 3 个（5 个工作、1 个假片） | 两颗 GPU 并排，8 个 HBM；具体布局未见可测量的图 | **照片可见**：IOD 居中，12 个 CCD 环绕 | — |
| 总功率 | **官方**：SXM 700 W | 约 1,000 W（多来源一致） | **官方**：360 W TDP（另有泄露称峰值插座功率可达 700 W） | **二手且不一致**：约 10–18 W/堆叠 |
| 各芯粒功率拆分 | **未找到**（GPU 对 HBM 无实测拆分；H200 同为 700 W，间接说明 HBM 占比不大） | 未找到 | 未找到（CCD 对 IOD 无公开拆分） | — |
| 芯粒间连线（网表） | **不公开**。只能按接口规格合成：每个 HBM3 1024 位数据，加地址与控制信号 | NV-HBI 10 TB/s（官方口径） | 每个 CCD 一条 GMI 链路到 IOD（AMD 调优指南） | 1024 位接口 |
| 温度上限 | 未公开结温上限 | 未公开 | 未公开（数据表给 Tctl） | JEDEC 刷新跳变：约 85/95 °C（见 Karfakis 等） |

## 结论

1. **能做**：构造"以公开数据校准、估计部分逐项标注"的产品级基准。
   - **EPYC Genoa 数据最全**：每个芯粒的长宽、基板尺寸、排布照片都有，适合作第一个工业案例。它是有机基板 MCM，不是硅中介层。
   - **H100 次之**：芯粒面积官方、排布照片清楚；中介层尺寸只有估计值，芯粒长宽要从照片按比例测。
   - **B200 数据太少**，暂不采用。
2. **必须估计的部分**：
   - 各芯粒的功率拆分：所有产品都没有公开。做法是 HBM 按 10–15 W/堆叠的区间取值，其余归计算芯粒，并做敏感度分析；
   - 网表：按接口规格合成；
   - 温度上限：用 JEDEC 和公开资料的典型值。
   这些都要在论文里写明是"声明的假设"。
3. **真实布局可以作为人工基线**：H100 和 Genoa 的排布从照片可读。在同一模型、同一约束下比较"人工布局、ATPlace、我们的方法"，是最有工业说服力的实验。
4. **局限**：芯粒长宽、中介层尺寸、功率拆分的误差会直接影响绝对温度。所以结论应基于相对比较（同一假设下谁更好），并报告对功率拆分的敏感度。

## 下一步

1. 从官方产品照片按比例测出 H100 的 GPU 与 HBM 长宽和间距，并核对 814 mm²。
2. 把 Genoa 和 H100 各写成一个案例文件，所有数字附来源与"官方、实测、估计"标记。
3. 加入"人工布局"作为基线，然后在同一模型下比较三方。

## 来源

- [SemiAnalysis：CoWoS 与 HBM 供应链](https://newsletter.semianalysis.com/p/ai-capacity-constraints-cowos-and)（H100 为 CoWoS-S 7 芯粒封装，中介层约 3× 光罩）
- [VideoCardz：H100 SXM 实物照片](https://videocardz.com/newz/nvidia-h100-sxm-with-4nm-hopper-gpu-and-80gb-hbm3-memory-has-been-pictured-up-close)（5 个工作 HBM 加 1 个假片）
- [Hothardware：H100 实测面积 822.88 mm²](https://hothardware.com/news/h100-hopper-gpu-gets-pictured)；[TechPowerUp：GH100 814 mm²](https://techpowerup.com/gpu-specs/nvidia-gh100.g1011)
- [NVIDIA H100 架构白皮书](https://www.hpctech.co.jp/assets/images/info/catalog/pdf/gtc22-whitepaper-hopper_v1.02.pdf)
- [Wikipedia：Blackwell](https://en.wikipedia.org/wiki/Blackwell_(microarchitecture))；[Silicon Analysts：B200 成本拆解](https://siliconanalysts.com/analysis/nvidia-b200-blackwell-cost-breakdown)；[NextPCB：B200 1000 W](https://www.nextpcb.com/blog/nvidia-blackwell-architecture-b200-gb200-pcb-design)
- [Wccftech：Genoa 尺寸泄露](https://wccftech.com/amd-epyc-genoa-zen-4-server-cpus-and-sp5-lga-6096-server-platform-details-leaked/)；[Wccftech：Genoa 实物与 IOD 实测](https://wccftech.com/amd-epyc-genoa-zen-4-cpu-pictured-in-all-its-glory-12-ccds-featuring-up-to-96-cores-massive-iod/)；[TechPowerUp：EPYC 9654](https://www.techpowerup.com/cpu-specs/epyc-embedded-9654.c3189)；[AMD EPYC 9004 调优指南](https://docs.amd.com/api/khub/documents/NgOfoW49HKdzztTeLBbekA/content)
- [Wikipedia：HBM](https://en.wikipedia.org/wiki/High_Bandwidth_Memory)；[Vikram Sekar：HBM 制造](https://www.viksnewsletter.com/p/why-is-hbm-so-hard-to-manufacture)；[arXiv 2510.05245](https://arxiv.org/pdf/2510.05245)（HBM3 底片 121 mm²）

## 下一代与同系列产品（同日补充）

| 档位 | 依据 | 可靠程度 |
| --- | --- | --- |
| 2 GPU + 8 HBM（B200） | 两颗接近光罩上限的 GPU，每颗配 4 个 HBM3e，用硅桥连接（[AnandTech](https://www.anandtech.com/show/21310)、[TechInsights](https://www.techinsights.com/blog/techinsights-nvidia-hgx-b200-analysis-reveals-hbm3e-supplier-and-advanced-packaging-innovation)）；单颗面积有 400 与 800 mm² 两种说法，后者与"接近光罩"一致 | 结构可靠；中介层尺寸无可靠数字 |
| 4 GPU + 16 HBM4E + 2 IO（Rubin Ultra，GTC 2025） | 一排 4 颗光罩尺寸 GPU，两侧 2 个 IO 芯粒，16 个 HBM4E，约 1 TB；SemiAnalysis 估计用两块中介层（[SemiAnalysis](https://newsletter.semianalysis.com/p/nvidia-gtc-2025-built-for-reasoning-vera-rubin-kyber-cpo-dynamo-inference-jensen-math-feynman)）；约 3.6 kW 的功率说法未核实 | 探索性 |
| 同上，后续报道 | 2026 年 7 月报道称 4 芯片设计因封装限制改为 2 芯片加 8 个 HBM4E，NVIDIA 未确认（[TechTimes](https://www.techtimes.com/articles/319410/20260701/nvidia-rubin-ultra-four-die-gpu-cancelled-packaging-limits-cut-2027-performance-half.htm)） | 未确认报道，可作动机，引用时注明 |
| EPYC Turin（Zen 5） | 最多 16 个 CCD，每个 70.6 mm²；IO 芯片与 Genoa 相同；SP5 封装（[Wikipedia: Zen 5](https://en.wikipedia.org/wiki/Zen_5)、[Thomas-Krenn](https://www.thomas-krenn.com/en/wiki/AMD_EPYC_9005_Turin)、[Wccftech 照片](https://wccftech.com/amd-zen-5-epyc-turin-cpus-pictured-128-core-zen-5-192-core-zen-5c-flavors/)） | 真实产品；CCD 面积来自 Wikipedia |
| EPYC Turin Dense（Zen 5c） | 12 个 CCD，最高 500 W（[Tom's Hardware](https://www.tomshardware.com/pc-components/cpus/amd-launches-epyc-turin-9005-series-our-benchmarks-of-fifth-gen-zen-5-chips-with-up-to-192-cores-500w-tdp)）；CCD 尺寸未找到 | 部分 |
| HBM4 | 2048 位接口（JEDEC JESD270-4）；堆叠尺寸未找到；功率说法 18–20 W 与 75 W 不一致（[Wikipedia: HBM](https://en.wikipedia.org/wiki/High_Bandwidth_Memory)） | 尺寸与功率需声明假设 |

### 案例清单（计划）

| 编号 | 案例 | 作用 |
| --- | --- | --- |
| G1 | H100：1 GPU + 6 HBM | 验证：能否找回接近真实产品的排法 |
| G2 | B200 类：2 GPU + 8 HBM | 真实结构，热冲突开始出现 |
| G3 | Rubin Ultra 类：4 GPU + 16 HBM + 2 IO | 主要检验：排法不显然、热冲突强 |
| C1 | Genoa：12 CCD + IOD | 验证 |
| C2 | Turin：16 CCD + IOD（同一封装） | 真实产品，封装更满 |
| C3 | 24 CCD（推测） | 可扩展性 |

先建 G3，并筛查：在硬约束下，最好的合法布局比人工对称排法好多少。

## 开源 2.5D 基准现状与"真实功耗"的来源（同日，已读全文）

| 工作 | 芯粒数据来源 | 功耗 | 温度 |
| --- | --- | --- | --- |
| Open3DBench（[仓库](https://github.com/lamda-bbo/Open3DBench)、[arXiv 2503.12946](https://arxiv.org/pdf/2503.12946)） | 13 个 ORFS 开源 RTL 设计 + ICCAD 2022/2023 竞赛用例；NanGate45 改成两层；OpenROAD 实现 | 工具算出 | HotSpot |
| UCLA 3D-IC 用例集（[arXiv 2608.25155](https://arxiv.org/pdf/2608.25155)，2026-08） | 基于 CATCH 的 5 类**虚拟芯粒模板**（面积与逻辑、存储比例），20 个 2.5D/3D 用例，3Dblox 格式 | **无**（全文没有出现"power"） | 无 |
| ChipletPart（UCLA Gupta + UCSD Kahng，[arXiv 2507.19819](https://arxiv.org/pdf/2507.19819)） | 开源设计（晶圆级图处理器、MemPool）在 45 nm 综合，提取模块面积与模块级网表；另有一个 16 nm 工业设计（不公开），以及按公开信息构造的 EPYC 7282、GA100 | 综合得到的模块功耗，按工艺缩放因子换算，再人为放大"以利于划分"，加上 I/O 功耗 | **无**，作者列为未来工作 |
| ATPlace 基准 | 人工给定 | 人工给定 | — |

**结论**：目前没有一个开源 2.5D 基准的功耗是"按负载算出来的"，也没有带温度评估的。

**获得真实功耗的途径**（可信度从高到低）：
1. 实测：红外热像反演、片上传感器（CPU 的 RAPL 可分域，GPU 有板级功耗、部分有显存功耗）；数据零散，基本没有芯粒粒度。
2. 真实实现加负载仿真：OpenROAD + 开源工艺实现每颗芯粒，用负载仿真得到翻转率，再用 OpenSTA 算功耗图。数字是算出来的，但开源工艺下芯片小、功耗低。
3. 架构级功耗模型加负载：CPU 用 McPAT，GPU 用 AccelWattch，加速器用 Accelergy/Timeloop，存储用 DRAMPower/CACTI，多芯粒 DNN 用 CHIPSIM（开源，按芯粒输出微秒级功耗）；再对照公开 TDP 校准。可放大到产品规模，每个数字有可追溯的模型。
4. 人工估计。

**机会**：一个"功耗由负载驱动、可追溯，并带温度评估"的开源 2.5D 基准目前空缺，最相关的两个组都把温度列为未来工作。
**建议的最小验证**：用 CHIPSIM 在一个开源多芯粒 DNN 案例上得到逐芯粒功耗，接入我们的布局与热流程，看布局结论与"人工写的功耗"相比是否明显不同。

## 开源仓库核查（2026-11-16，四个子代理只读核查，另核查 thermal_stco）

**热布局工具**
- ATPlace2.5D（`PKU-IDEA/ATPlace_pub`，MIT）：核心在 `b342fe2`–`8185e15`（2026-06 至 10）用 Pyarmor 加密；从 `fdf11e5`（2026-11-07）起改为明文 Python。我们使用的 `fe3dbfd` 是开源版本。ATSim 只提供可执行文件，没有许可证。
  - 开源版默认对流热阻 0.01 K/W，论文是 0.1 K/W，热仿真器也从 HotSpot 换成 ATSim，所以结果本来就与论文不同（作者在 README 中说明）。
  - 10 个例子都没有给出数据来源；Case1 疑似由 TAP 的 multiGPU 例子改出。
- TAP-2.5D（Apache-2.0）：源码开源；线长需要 CPLEX，没有免费替代；HotSpot 6.0 可以重新编译；只有 3 个手写的 6–8 颗芯粒的例子。
- STAMP-2.5D（Apache-2.0）：TAP 的分支，需要 ANSYS 加 CPLEX，没有纯开源的有限元路径，每种结构约 60 小时，只能引用论文数字。
- 三者的功耗都是每颗芯粒一个固定值，不随负载变化。

**基准与设计空间探索工具**
- ChipletPart（`ABKGroup/ChipletPart`，BSD-3）：模块的面积和功耗写死在生成脚本中，WS 系列乘以 1600；EPYC 与 GA100 是整数取值的人工数字；没有热模型。
- CATCH（`nanocad-lab/CATCH`，Apache-2.0）：成本模型，功耗手写，没有热模型和布局。
- UCLA 3D-IC 用例集：Dryad 下载需要令牌；对应的 GitHub 仓库是 3Dblox 格式，芯粒来自 CATCH 虚拟模板，热字段只是占位，坐标是构造的而不是优化得到的。
- RapidChiplet（`spcl/rapidchiplet`，无许可证）：功耗 = 20 W + 0.125 W × PHY 数，没有热模型，布局是规则网格。
- CHIPSIM（无许可证，作者称"功能正确性尚不能保证"）：
  - 数字芯粒按每 MAC 50 fJ 的手写系数计算；存内计算芯粒的数据来自 CiMLoop Docker；
  - 没有漏电和校准，芯粒没有尺寸，每颗只有约 0.2–2 W；
  - 输出 CSV 的单位疑似有误（140 W 与 2000 W 对不上）；
  - 只能借用它的逐层 DNN 定义和映射思路，生成相对负载占比。

**中介层布线**
- OpenROAD：能读写 3Dblox，`check_3dblox` 只做声明级检查，`rdl_route` 每次只布一层；没有多层中介层全局布线和拥塞分析。
- IHP Open-ADK（Apache-2.0，v0.3.0 预览）：只有装配几何 DRC，布线器 `interposer-pnr` 尚未公开。
- 公开设计规则：
  - 芯粒间最小间距 ASM.b = **200 µm**（v0.2 为 50 µm），见 `IHP-Open-ADK/config/rule_params.json`；
  - 铜柱 pitch 75/80/95 µm，焊料凸点 pitch 130 µm；
  - 中介层 4 层铝布线。
- GT Interposer-PnR-tutorial：全部步骤依赖 Cadence。

**thermal_stco（`nanocad-lab/thermal_stco`，Apache-2.0，UCLA Gupta 组，对应 ECTC 论文）**
- 用 LLM 负载仿真（Rapid-LLM/DeepFlow）得到功耗，再用热仿真评估降频与运行时间；
- 系统为 1 GPU + 6 HBM，比较 2.5D 与 3D、HBM 8 层与 16 层、TIM、infill、underfill 导热率，水冷散热；
- 热仿真器是商业软件 Anemoi，需要订阅令牌；布局固定，不做布局优化，也不是基准集。

**修正后的空白判断**
- "负载驱动功耗 + 热评估"已有先例（thermal_stco），但只针对单一固定结构，且依赖商业热仿真器。
- 仍然空缺的是：一个开源、可复现的，"负载驱动功耗 + 开源热评估 + 布局优化"、并覆盖多种规模的 2.5D 基准。
- UCLA Gupta 组在这一方向非常活跃（ChipletPart、CATCH、3D-IC 用例集、thermal_stco、嵌入式隔热体），竞争风险高。
- 对我们的直接影响：工业场景的芯粒间距应改为 200 µm（IHP 公开规则），与 Intel 专利的 100–200 µm 一致；现有 gap0 前沿不满足这一规则。
