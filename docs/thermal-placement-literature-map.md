# 热感知芯粒布局：文献地图与空白（2026-11-15）

目的：先查清"与布局、温度一起优化过什么"，再在空白处选题。前面的方向都是先做实验、后发现撞车，这一页用来避免再出现这种情况。

来源：
- 用户 Zotero 库：热感知架构与设计探索、热建模与冷却、2.5D 芯粒架构、封装与良率等收藏夹；
- 本轮全文核对的两篇：Coskun 等 TCAD 2020，Karfakis 等 embedded isolators；
- 网络检索：2024–2026 年的布局工作。
"已读全文"与"只读摘要或检索摘要"分开标注。

## 1. 与布局、温度一起优化过的量

| 与布局联合的量 | 代表工作 | 读到的程度 | 我们的实验 |
| --- | --- | --- | --- |
| 线长（线性代理） | TAP-2.5D（DATE'21）、ATPlace2.5D（ICCAD'24）、序列对树（TODAES'25）、MaskPlace2.5D、RLPlanner、DiffChip（2025，可微热求解）、TACPAs（代理模型）、TDPNavigator（多智能体 RL，按 TDP）、Chiplet3D（3D，pin 与热，MILP）、TACPlace | 摘要 | 冻结前沿即此类 |
| 中介层面积或成本 | FAPlace（2026，布局与中介层面积）、Coskun DATE'18、TESA（DATE'23，芯粒尺寸与间距、MCM 成本）、Coskun TCAD'20 | 摘要；TCAD'20 全文 | — |
| 应力、翘曲 | STAMP-2.5D（2025）、ATMPlace（2025） | 摘要 | — |
| 网络拓扑、链路可达长度、链路流水线、µbump 边缘 | Coskun、Kahng 等 TCAD'20（式 (3) 可达长度）、ICCAD'18；PlaceIT（无温度） | 全文 | 可达距离 v1–v3：已覆盖 |
| 对温度敏感的芯粒（HBM 刷新跳变、性能闭环） | Karfakis、Gupta 等（嵌入隔热体；结论：布局作用有限，耦合主要经均热板） | 全文 | 鲁棒模式中内存 95 °C：已覆盖 |
| 封装材料、2.5D 与 3D 对性能 | Thermally-Aware STCO for AI Systems（Zotero）；Imec HBM-on-GPU | 摘要 | 封装杠杆：与布局可分 |
| 架构粒度、映射与热 | ThermoDSE（2026）、TESA、Tasa（3D）、Gemini（无热） | 摘要 | — |
| 液冷与布局 | 3D 微通道与 TSV、功率分布（2012、2017）、可变流量液冷（DATE'10）、Hot-LEGO | 摘要 | 冷板联合：未找到 2.5D 先例，但收益只有 1–2 K |
| 负载、模式与布局（设计期） | 未找到直接先例 | — | 负载杠杆、鲁棒模式、b_max：增益 ≤ 0.025，停止 |
| 多 SKU 共用布局 | 未找到直接先例 | — | 不确定，停止 |

运行时热管理（DVFS、调度、迁移）有大量工作，例如 Zotero 中的 ReThermal、HeatCache、ThermE、CoolPIM、NeuroCool。它们都不改布局。
热模型与求解器（3D-ICE 4.0、MFIT、CUTh-Solver、HotSpot）是工具，不是选题。

## 2. 我们已经学到的物理规律（用于筛选空白）

1. 线性稳态下 T = T_amb + R(x)p。布局通过互热起一阶作用：互热占最热芯粒温升的 31–76%。
2. 只要一个旋钮不改变"把高功耗芯粒分开、放在散热好的位置"这个最优结构，它就与布局可分，或者收益只有 1–2 K。
   - 整体缩放 R 或 p 属于这一类；
   - 冷板的位置不对称受冷却液温升（约 11 K）限制。
3. 与布局冲突的量必须要求"高功耗芯粒靠近"。链路可达距离、HBM 邻近都是这样，但都已被研究。
4. Karfakis 等的结论（耦合主要经均热板，布局作用有限）与我们的互热分解并不矛盾：互热本身就主要经均热板传递。
   但他们的系统是一颗 GPU 加 HBM，我们多芯粒例子的互热占六成以上。这一差别本身不足以成为新问题。

## 3. 仍可能是空白的方向（只检索过一轮，均未全文核查）

| 方向 | 为什么可能是一阶问题 | 已知最近的工作 | 主要风险 |
| --- | --- | --- | --- |
| A. 光电共封装（CPO）中光芯粒的位置：微环需要温度稳定，调谐功耗随局部温度变化，并反过来产热 | 敏感量是温度偏差和梯度，不是峰温，所以最优结构可能不同于"分开热源"；调谐功耗与布局形成闭环 | 光片上网络的热感知映射（多为片上，非 2.5D 布局）；Zotero 中晶圆级光互连热调谐停顿分析（MoE 训练） | 需要可靠的微环热光系数、调谐效率等校准数据；先例可能在光子学社区 |
| B. 瞬态：突发负载（LLM 预填充与解码、MoE 突发）下的布局 | 稳态 R(x) 之外，热容决定短时峰值；不同芯粒的突发时间尺度不同 | 未找到 2.5D 布局先例；运行时 DTM 很多 | 均热板与散热器时间常数为秒级，毫秒级突发可能被平均掉，需要先用第一性原理估算 |
| C. 供电（IR 压降、稳压器位置）与布局、温度 | 稳压器本身发热，并且要靠近负载，与"分开热源"冲突 | 未检索 | 未检索，可能已有 PDN 感知的芯粒布局 |
| D. 冷板与布局 | 未找到 2.5D 先例 | — | 已测得收益只有 1–2 K，弱 |

## 3.1 针对性检索结果（同日，第一轮）

**A. 光芯粒位置与热调谐**
- 已知的近邻工作：
  - Coskun 组 PROWAVES（TCAD 2020，已读摘要并检索正文）：2.5D 光子片上网络在运行时选择激活的波长。热调谐功耗是一阶量，相对基线节省 24–26 W。
    文中加热器效率取 120 pm/mW，相邻器件热耦合 < 0.02 K/mW。它是运行时策略，不改布局。
  - RingAware、FreqAlign：用线程分配与迁移减小微环附近的温度变化，属于运行时方法。
  - Chen、Fu、Feng 的 BAT（Integration 2022）：光芯粒的热可靠性，方法是光学桥接加调谐，摘要提到"热布局"，未读全文；
    后续有 ISVLSI 2024 的会议论文。
  - Pasricha 组：LIBRA 用运行时迁移降低调谐功耗；HELIX、OPAL 包含光片上网络的布图规划与热通孔。都是片上网络，不是 2.5D 芯粒布局。
  - 光电共封装（CPO）综述指出光引擎与计算芯粒之间存在热串扰，应该联合设计，但没有给出布局优化方法。
- **未找到**：2.5D 封装中，把光芯粒（光引擎）相对 GPU 或交换芯片的位置作为变量，以热调谐功耗（或调谐范围）为目标的布局优化。
- 第一性原理（待算）：
  - 加热器只能升温，所以微环要按工作范围内的最高局部温度来设计，调谐功耗 ∝ 局部温度在各负载模式下的摆幅，而不是平均温度。
  - 因此光芯粒想放在"温度最稳定"的位置，而不是"最冷"的位置。这个最优结构与"分开热源"不同。
  - 量级：硅的谐振漂移约 0.08 nm/K，PROWAVES 的加热器效率为 0.12 nm/mW，即每个微环每 K 约 0.7 mW。
    以 1000 个微环、20 K 摆幅计，约 14 W。若光链路共 32 Tb/s，相当于约 0.4 pJ/bit，与光链路 1–5 pJ/bit 的总预算同量级。
  - 需要核实：微环数量、负载摆幅（可复用鲁棒模式的闲置场景）、光芯粒对电链路长度的要求。

**B. 瞬态与突发负载**
- 未找到布局层面的先例；稳态布局工具都用峰温。
- 第一性原理（粗算）：
  - 芯粒间互热主要经铜均热板，横向 20 mm 的扩散时间约 L²/α = (0.02)²/1.17e-4 ≈ 3 s；
  - 芯片自身的局部温升在毫秒量级（150 µm 硅约 0.3 ms）。
  - 所以毫秒到百毫秒的突发（MoE、解码步）只改变自热，而自热与布局无关；布局只对秒级以上的平均功率起作用，问题又回到稳态。
  - 这个方向很可能退化，除非负载相位长达数秒。暂不推进。

**C. 供电与布局**
- Georgia Tech 的芯粒—中介层 PDN 协同设计（TCPMT 2021，含 IVR 模型）、Missouri S&T 的热感知 DC-IR 分析、Coskun TCAD'20（目标含 IR 压降）已覆盖一部分。
- 未找到"稳压器位置作为布局变量、同时考虑其发热"的工作，但相关工作较多，风险中等。

## 4. 建议的下一步

1. 对 A、B、C 各做一轮针对性检索，必要时读全文，确认是否已有先例。
2. 对仍未覆盖的方向做第一性原理估算：
   - B 的热时间常数；
   - A 的调谐功耗量级（对比芯粒功耗）与温度容差。
3. 只在估算显示"与布局冲突并且收益为一阶"时，才写冻结计划。

## 参考（检索所得，未全部读全文）

- [Coskun et al., Cross-Layer Co-Optimization..., TCAD 2020](https://www.bu.edu/peaclab/files/2020/02/Cross-Layer-TCAD-2020.pdf)
- [Karfakis et al., Embedded Isolators](https://nanocad.ee.ucla.edu/wp-content/papercite-data/pdf/j84.pdf)
- [TAP-2.5D](https://people.bu.edu/joshi/files/Ma_TAP-2.5D-DATE2021.pdf)；[ATPlace2.5D](https://yibolin.com/publications/papers/PLACE_ICCAD2024_Wang.pdf)；[序列对树](https://dl.acm.org/doi/10.1145/3716893)；[MaskPlace2.5D](https://www.sciencedirect.com/science/article/abs/pii/S0167926026001513)
- [DiffChip](https://arxiv.org/pdf/2502.16633)；[TACPAs](https://arxiv.org/pdf/2504.03808)；[TDPNavigator-Placer](https://arxiv.org/abs/2602.11187)；[FAPlace](https://arxiv.org/html/2607.02610)；[Chiplet3D](https://arxiv.org/abs/2607.09742)
- [STAMP-2.5D](https://arxiv.org/html/2504.21140v1)；[ATMPlace](https://arxiv.org/html/2511.17319v1)；[PlaceIT](https://arxiv.org/pdf/2502.01449)；[MFIT](https://arxiv.org/pdf/2410.09188)
- [PROWAVES, TCAD 2020](https://www.bu.edu/peaclab/files/2020/11/narayan_TCAD20_prowaves.pdf)；[BAT, Integration 2022](https://www.aminer.cn/pub/62d16b515aee126c0fd0cf1b/improving-the-thermal-reliability-of-photonic-chiplets-on-multicore-processors)；[LIBRA](https://www.engr.colostate.edu/~sudeep/wp-content/uploads/j52.pdf)；[CPO 综述](https://link.springer.com/article/10.1007/s12200-022-00055-y)；[CPO 热串扰综述](https://www.researching.cn/articles/OJdfcef54819a8d106)；[晶圆级光互连热调谐](https://arxiv.org/pdf/2608.24637)
- [Georgia Tech PDN 协同设计](https://gtcad.gatech.edu/www/papers/tcpmt21-a.pdf)；[热感知 DC-IR](https://scholarsmine.mst.edu/cgi/viewcontent.cgi?article=6181&context=ele_comeng_facwork)
- [Coskun DATE 2018](https://people.bu.edu/joshi/files/dark-silicon-date-2018.pdf)；[3D-ICE 4.0](https://www.researchgate.net/publication/398430926_3D-ICE_40_Accurate_and_efficient_thermal_modeling_for_25D3D_heterogeneous_chiplet_systems)；[芯粒 EDA 综述](https://arxiv.org/pdf/2411.04410)；[多尺度热建模综述](https://arxiv.org/pdf/2604.03290)
