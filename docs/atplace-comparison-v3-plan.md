# 与 ATPlace2.5D 的正式比较 v3：补全 Case8–10 的热感知基线（计划，运行前冻结，2026-11-17）

依据：[v2 计划与结果](atplace-comparison-v2-plan.md)。v2 只有 Case1–7 完整（两种热模型下各胜 6、负 0），Case8–10 的 ATPlace
热模型训练失败，各只有线长模式 1 个点，所以 10 例的正式判定是 incomplete。要声称超过 SOTA，必须在全部 10 例上和它的热感知布局比。

## 失败原因（已查明）

ATPlace 训练热模型时，每个训练布局先随机抽取各芯粒的四分之一转角和目标位置，再用整数规划找最近的合法布局
（`src/thermal/training.py: sample_layout`）。在密集的 Case8–10，有些抽样在时限内找不到合法布局：
- Case8：前 3 个样本成功，第 4 个失败（600 s 时限）；
- Case9、10：第 1 个样本就失败（600 s 时限）。

这些例子存在合法布局（ATPlace 自己的线长模式和我们的方法都能产出），失败来自单次随机抽样的朝向组合，不是例子无解。

## 适配（最小改动）

`tools/atplace_train_retry.py`：某次抽样失败时，用同一个随机数发生器重新抽取转角和目标位置，最多 20 次。
运行仍然确定；抽样器、ATSim 标签、模型和训练都用 ATPlace 自己的代码，不改其仓库。
这改变的只是训练布局的分布：只保留能找到合法布局的抽样。该适配如实报告。

## 运行

- **ATPlace**：Case8–10，`atplace_sweep.py --sampling-attempts 20 --training-sampling-s 120 --threads 16 --parallel 3`。
  - 120 s 时限与 Case5、6 的补跑相同；
  - 其余参数与 v1 相同：线长模式 1 次，热感知模式 5 个权重倍数；
  - moe-server，ATPlace 提交 `fe3dbfd`。
- **Case1–7**：沿用 v1 的 ATPlace 结果，不重跑。
- **我们**：v2 的指定方法 relation_space（rs-grb-v4，种子 2），不重跑；已导出的 16 个布局及其 ATSim 分数沿用。

## 判定（与 v2 相同，运行前写定）

- 每例：带裕量支配（凉 ≥ 1 K 且线长不更长，或短 ≥ 10% 且温度不更高）。
  - 我方胜：D_ours ≥ 0.5 且 D_atp ≤ 0.1；ATPlace 胜：D_atp ≥ 0.25 且 D_ours < 0.5。
- 方法有优势：两种热模型（我们的 FV、ATSim）下都至少 7 例我方胜。
- 无优势：任一模型下至少 5 例 ATPlace 胜，或两种模型下我方胜都不超过 3 例。
- 如果 20 次重抽后仍失败，该例记为 ATPlace 运行失败，10 例判定仍为 incomplete，不把失败计为我方胜。

## 补充（事先声明，次要）

proxy_space v2（px-v2）若在其冻结主比较中判为"改进"，再用同一规则与 ATPlace 比较一次，作为次要结果。
不在多个方法中事后挑选最好的一个作为正式结果。

## 墙钟

本次运行与其他实验共享 moe-server，Case8–10 的 ATPlace 墙钟不作速度比较。

## 运行前估计

Case8–10 的 ATPlace 热感知布局应比它的线长点更凉。v2 中我们在 Case9、10 比该线长点低 9.6 / 8.9 K，Case8 持平。
预测 Case9、10 仍为我方胜，Case8 持平或我方胜，10 例判定为"有优势"（两种模型各 ≥ 7 胜）。

## 结果（2026-11-17，[证据](evidence/atplace-compare-rsg4-v3.json)）：incomplete（8/10 例完整：7 胜 1 平 0 负）

- **ATPlace 运行：**
  - Case8 的训练第 20 次重抽内成功，6 个点全部合法并完成 FV 评分；
  - Case9、10 重抽 20 次后训练仍失败，按冻结规则记为 ATPlace 运行失败。
- **完整的 8 例（Case1–8）：** FV 与 ATSim 两种热模型下都是我方 7 胜、Case2 平、0 负。
  - Case8：两种模型下都是我方胜（D_ours = 0.83，D_atp = 0）。
  - Case9、10 只有线长点，作为描述性结果，两种模型下都是我方胜，不计入判定。
- **10 例判定为 `incomplete`。** 按冻结规则，不把 ATPlace 的失败计为我方胜。
  若只看完整的 8 例，7 胜已达到"有优势"门槛（≥ 7），但正式判定仍以 10 例为准。
- **Case8 的一个现象：** ATPlace 的线长模式（84.26 °C，7.65 m）比它 5 个热感知模式（84.63–86.07 °C，9.4–10.8 m）都凉，所以在这一例上热感知训练没有带来降温。
- **处理方式：**
  - FV 评分在 moe 上完成，代码 `5d0495c`，输出 `compare/atplace-fv-v3.json`；
  - Case1–7、9、10 沿用 v1 的评分；Case8 换成 v3 补跑的全部 6 个点；合并后的布局目录为 `compare/merged-v3`。
- **追加 Case8 atp_cool：** 按 [cosize-v3.2](cosize-v3-plan.md) 第 9 节同一协议追加到正式运行。参照为 thermal_x100（84.63 °C，10.05 m）。
