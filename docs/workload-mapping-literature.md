# 负载驱动的芯粒布局与映射：全文核查（2026-11-16）

用户的目标是投 ICCAD，问"负载驱动的芯粒布图规划加映射"是否可做。以下 5 篇都读了全文的相关章节。

| 工作 | 布局怎么表示 | 是否优化映射 | 温度 | 链路代价 | 负载 |
| --- | --- | --- | --- | --- | --- |
| Floorplet（Chen、Yu、Sangiovanni-Vincentelli 等，arXiv 2308.01672） | 真实几何：尺寸、位置、旋转，另含翘曲、凸点应力、成本，用数学规划求解 | **否**：映射固定，用 gem5 测芯粒间数据搬运频率，作为线长权重；线长按 6 档映射到延迟权重 | 否（只在背景中提到） | 半周长线长按档位换成延迟 | 并行矩阵乘、ResNet、MobileNet |
| CarbonPATH（Chhabria 组，arXiv 2603.03878） | 二分切割布图，只用来估算面积 | 是：映射、架构、封装（2D、2.5D、3D）、碳足迹，用模拟退火求解 | 否 | 延迟 = 数据量 / min(两端带宽)，带宽由凸点数与协议决定，与几何长度无关 | AI 负载 |
| MOHaM（TC 2024，arXiv 2210.14657） | 二维网格 NoP 的槽位，XY 路由数跳数 | 是：选子加速器、定槽位、层的时空映射，用遗传算法求解 | 否（只在引言中提到） | 跳数 × 每比特能耗 0.82 pJ | 多 DNN |
| Compass（arXiv 2512.06093） | 网格槽位，XY 路由跳数 | 是：异构芯粒库，映射与硬件联合探索 | 否 | 跳数 | LLM 服务（预填充与解码，Orca、Chunked Prefill） |
| ThermoDSE（arXiv 2607.07096） | 同构计算芯粒网格，统一的芯粒间距，HotSpot 布图 | 是：任务编排与映射，加贪心的热感知映射（把热任务放到离中心远的核心） | **是** | NoP 网格 | DNN |

此前只读了摘要的：Gemini（HPCA'24，映射与架构）、TESA（芯粒尺寸与间距、热）、3D-CIMlet（DAC'25，热感知映射）、HYDRA（LLM 服务的芯粒组成、位置与调度）、INDM。

## 结论

1. "负载驱动的布局加映射"本身已经很拥挤，不能直接作为新问题。
2. 现有工作分成两类，彼此没有接上：
   - **架构类**（MOHaM、Compass、Gemini、CarbonPATH、ThermoDSE）：布局是网格槽位或同构阵列加统一间距，链路代价只按跳数或带宽计算；
   - **物理布局类**（Floorplet、TAP-2.5D、ATPlace）：有真实几何，但映射固定，Floorplet 没有温度。
   - 没有找到"异构芯粒、真实几何的自由布局、映射、温度"四者同时联合的工作。
3. 风险：
   - 我们在热这一侧多次测到耦合偏弱：负载模式、鲁棒模式、b_max 的增益都 ≤ 0.025，冷板只有 1–2 K。映射主要通过"热任务放到哪颗芯粒"影响温度，这与已测的闲置模式实验在物理上相近，所以热这一侧的增益可能仍然小；
   - 通信这一侧（数据量 × 距离、可达距离）的耦合强，但 Floorplet 已在真实几何上用负载流量加权，Coskun TCAD'20 已做了可达长度；
   - 所以"把两类接上"更可能是一篇扎实的方法或评估论文，而不是全新的问题。可以检验的论点是：**网格抽象选出的映射和布局，换成真实几何与热模型后，排序会变吗？**

## 更正（同日）：空白已被覆盖

Sharma、Doppa、Ogras、Pande 的 **"Designing High-Performance and Thermally Feasible Multi-Chiplet Architectures enabled by Non-bendable Glass Interposer"**（arXiv 2507.18040，ACM 2025；已读相关章节）：
- 外层用贝叶斯优化选择异构芯粒组成；
- 内层联合优化芯粒在中介层上的布局与 DNN 层到芯粒的映射，同时满足温度与翘曲约束，目标是 EDP；
- 用 BookSim2 模拟互连层（NoI），对象是 PIM 芯粒。
同组还有：
- Floret（TECS 2023）：用空间填充曲线排布芯粒，按数据流做映射；
- 缺陷感知的互连层（TCAD 2024）；
- THERMOS（arXiv 2508.10691）：热感知调度；
- CHIPSIM（arXiv 2510.25958）：开源协同仿真器，输出每颗芯粒微秒级的功率与温度，流量用 BookSim 模拟。

所以"异构芯粒 + 布局 + 映射 + 温度"已经有人做了，上面第 2 条结论不成立。剩下的差别只在细节上：他们的布局是否为自由几何、链路是否按长度计价、热模型的精度。按"不能增量"的标准，这些都不够。

可用的开源仿真器（如果仍做负载相关的工作）：CHIPSIM、Gemini（github.com/SET-Scheduling-Project/GEMINI-HPCA2024）、MOHaM（github.com/Haimrich/moham）、HISIM（github.com/mec-UMN/HISIM，含热与 NoP）、RapidChiplet（github.com/spcl/rapidchiplet）。
