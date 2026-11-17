# 中介层成本、良率与光罩数据（2026-11-16，子代理收集）

验证等级：A = 读过一手源码或原文；B = 二手报道或搜索摘要转引；C = 分析机构估算或低可信来源。

| 量 | 值 | 来源 | 等级 |
| --- | --- | --- | --- |
| 硅中介层晶圆成本（Chiplet Actuary） | $1,937 / 300 mm 晶圆（约 0.029 $/mm²）；数值即 CSET 表中的 65 nm 代工价，仓库误标为 55 nm | [DAC2022 repo](https://github.com/Yinxiao-Feng/DAC2022)（42dd5de）；[CSET 2020 表 9](https://cset.georgetown.edu/publication/ai-chips-what-they-are-and-why-they-matter/) | A |
| 中介层缺陷密度与聚集参数（Chiplet Actuary） | D0 = 0.06 /cm²，c = 6；中介层面积 = 1.1 × 芯粒总面积（导出量，不是变量） | 同上 | A |
| 良率公式 | Y = (1 + D0·A/c)^(−c)（负二项） | [arXiv 2203.12268](https://arxiv.org/html/2203.12268v4) | A |
| 键合良率 | 芯粒→中介层 y2 = 0.95（每片相乘），中介层→基板 y3 = 0.99；chip-last 成本 C_int·(1/(y1·y2ⁿ·y3) − 1) | Chiplet Actuary | A |
| 有机基板 | 0.005 $/mm² × {1, 1.5, 1.75, 2}（按尺寸分档）；C4 0.005、微凸点 0.01 $/mm² | Chiplet Actuary | A |
| Floorplet 参数 | 7 nm D0 = 0.09 /cm²，α = 10；封装成本公式同 Chiplet Actuary | [arXiv 2308.01672](https://arxiv.org/pdf/2308.01672) | A |
| CATCH（UCLA）硅中介层 | 0.0219 $/mm²，D0 = 0.001 /cm²，α = 2，拼接良率 1.0（代码中拼接项未启用）；注释承认多处参数为编造 | [cost_model_chiplets](https://github.com/nanocad-lab/cost_model_chiplets) | A（数值无出处） |
| 无源中介层良率表（Kannan MICRO'15） | 24 × 36 mm：D0 0.05–0.25 /cm² 对应良率 98.5–92.7%（作者注明 D0 仅示意） | [MICRO'15](https://www.eecg.utoronto.ca/~enright/Kannan_MICRO48.pdf) | A |
| 中介层晶圆成本（2012） | $500–650 / 晶圆（约 0.007–0.009 $/mm²） | Semiconductor Digest 2012 | A（较老） |
| CoWoS 全流程晶圆 | $10,000–12,000 / 晶圆（约 0.14–0.17 $/mm²）；中介层良率 60–70% | Silicon Analysts 转引 JPMorgan | C |
| 每芯片 CoWoS 成本 | CoWoS-S 约 $750（H100），CoWoS-L $1,000–1,100（B200） | 同上 | C |
| 标准光罩 | 26 × 33 = 858 mm²（TSMC 论文常用约 830 mm²） | CATCH；Tom's Hardware | B |
| CoWoS-S 最大中介层 | 3.3 × 光罩 ≈ 2,700 mm²，超过建议用 CoWoS-L/R | TSMC 3DFabric 页（搜索摘要转引） | B |
| 拼接 | 2 × 光罩约 1,700 mm²（2020，掩模拼接）；第 5 代约 2,500 mm²；ECTC 2023：超过 4 次拼接有吞吐与良率问题。**没有公开的拼接良率数值** | Guru3D/TSMC；ECTC 2023（403） | B |
| CoWoS-L 路线 | 3.5×（2024）、5.5× = 4,719 mm²、9.5× = 7,885 mm²（2027）、14×（2028–29）；各年口径不一 | TechSpot；TrendForce；Tom's Hardware | B |
| 真实产品 | H100 中介层约 2,500 mm²（C）；MI300X "3.5×" CoWoS-S，封装 76.8 × 72.0 mm（B/C）；B200 基板约 102 × 75 mm，中介层面积未公开（C） | 见各源 | B/C |

## 采用建议（子代理）与需要注意的地方

- 成本结构用 Chiplet Actuary（Floorplet 同），中介层面积从"导出量"改为决策变量正是可写的贡献。
- 默认参数：晶圆 $1,937（写明是 65 nm 代工价），D0 = 0.06 /cm²，c = 6，y2 = 0.95，y3 = 0.99。
- **良率参数文献间相差两个数量级**：按 Chiplet Actuary 参数，2,500 mm² 中介层良率约 0.26（858 mm² 约 0.61）；按 CATCH 约 0.99；Kannan 864 mm² 为 93–98%。至少扫 D0 ∈ {0.01, 0.06} /cm²，单价扫 0.007–0.029 $/mm²（0.15 只作数量级检查）。
- 光罩：单光罩 26 × 33 mm；硅中介层 ≤ 2,700 mm²，超过换 CoWoS-L/EMIB 类另算成本；拼接按曝光场数 k，每条缝乘良率 y_s^(k−1)，**y_s 没有公开数值，只能声明为假设并扫描**（如 1.0、0.99、0.95）。
- 新颖性：Floorplet 的模型里有平面区域 W、H 和成本项，是否为决策变量、成本是否随 W·H 变化，需对照其 TCAD 正式版表 I 与式 (18)。
