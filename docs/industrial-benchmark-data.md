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
