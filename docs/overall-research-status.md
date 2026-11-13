# Overall：研究记录与逐项验收

目前已建立能运行的布局、热、互连和时序研究组件，**R3 接通的是简化稳态热模型
与中心距离代理；新的 Case1 小验收已接通源 pin 距离与热评估**。真实端口—走线—温度相关功耗/延迟—时序约束
尚未在这个优化实验中闭合。不能把组件测试通过或算法分数改善写成完整物理闭合。

用户在 2026-11-12 要求汇总全部记录并一点一点验收。本页是持续更新的总入口；
历史结果保留，通过的范围、失败和未完成项分别记录。验收用于定位下一项修改，
不重新扩大为制造签核或无止境精度校准。

## 当前验收表

| 顺序 | 要回答的问题 | 当前裁决 | 证据及下一步 |
| --- | --- | --- | --- |
| 1 案例 | 到底在优化什么系统，哪些是源数据、哪些是假设？ | 当前三例的尺寸、功率、需求与锁定配置逐项一致；限定来源验收通过 | [案例与物理验收](case-physical-acceptance.md)、[论文实验对照](paper-experiment-comparison.md)。论文默认 45 mm 与代码配置 50 mm 分开说明；ATPlace 案例是作者构造的公开基准。 |
| 2 热物理 | 布局变化是否真正改变材料/热源，热量是否有明确去路？ | 简化稳态边值问题与数值记账通过；真实封装有效性仍有限 | [FV 契约](tap-fv-contract.md)、[准入](tap-fv-admission.md)、[敏感度](tap-sensitivity-results.md)。固定功率、均质材料、明确 Robin 边界；同矩阵解一致不等于独立物理验证。 |
| 3 指标 | 所谓优化收益是否来自满足同一约束的实际布局？ | 指标迁移及独立 Chat 核算通过 | [定义](tap-r3-metrics.md)、[历史重算](tap-physical-metric-results.md)、[审核](tap-physical-metric-review.md)。主指标为共同距离预算下的配对降温，保留选中布局、约束满足情况与全部三档。 |
| 4 算法 | 改进算子是否提高布局质量，而不只是提高合法率？ | R3 执行与比较验收通过；稳定算法优势未通过，Chat 同意此裁决 | [正式结果](tap-online-r3-results.md)、[审核](tap-online-r3-review.md)：18 次全部完成并通过回放，复用 27 条旧基线。合法变异减少拒绝，但主指标收益 0 / +0.374 / +0.150 K，MultiGPU 反向距离指标中位数变差 9.962%。 |
| 5 扩展 | 在更多芯粒与实际 pin 位置下是否仍有效？ | Case1 链路和 pin 引导经 Chat 复核通过；新合法性交叉执行通过，但主指标改善未通过 | [pin 引导结果](atplace-case1-search-results.md)、[复核](atplace-case1-search-review.md)、[交叉结果](atplace-case1-crossover-results.md)：pin 引导先获得 1.406 K / 6.510% 收益；只换合法性交叉后，非法提议归零，固定距离下却变热 1.247 K，反向距离改善 17.708%。保留权衡与负结果，稳定收益和规模扩展待证。 |
| 6 耦合结论 | 是否证明真实热—时序耦合改变布局决策？ | 未证明 | [三布局晶体管/STA结果](xyce-three-layout-results.md)。需要明确接口、通道、工作点和约束后再回答；R3 不承担这个尚未接通的问题。 |

## 历史记录的含义

| 工作线 | 已得到的证据 | 不能据此推出的结论 |
| --- | --- | --- |
| Windows、OpenSTA 与多案例平台 | [本地入口](windows-local.md)、[42 组时序参数和四热输入](local-multicase-results.md)、[多 Lane](multilane-timing-results.md)、[共享路由](shared-routing-results.md) | 软件可运行和逐路径记账正确，不等于高速 chiplet PHY 或真实封装签核。 |
| Pad、通道与源模型 | [Pad 诊断](pad-diagnostic-results.md)、[来源审计](pad-provenance-results.md)、[被动通道](passive-channel-results.md)、[温度模型](local-temperature-capability.md) | 保留模型不一致与不可用工作点；未将失败的 Pad 模型自动准入。 |
| 公开测量与 TTC | [实测拟合](measured-calibration-results.md)、[观测算子](ttc-observation-results.md)、[空间对照](ttc-spatial-results.md)、[稳态数值](ttc-numerical-closure-results.md)、[瞬态](ttc-package-transient-results.md)、[边界](ttc-package-boundary-results.md) | 条件拟合、特定网格数值闭合不等于目标 chiplet 封装的材料/边界已被实测校准。 |
| 联合决策与晶体管对照 | [决策基准](integrated-decision-results.md)、[成对布局](paired-transistor-layouts.md)、[异温 Fabric](xyce-three-layout-results.md) | 有温度交互不等于最优排序反转；已测候选未证明真实联合优化优势。 |
| TAP 几何、路由与 IHP | [独立几何域](tap-geometry-domains.md)、[粗图路由](tap-global-routing-results.md)、[IHP 局部访问](tap-ihp-local-access-results.md) | 粗粒度可路由、局部 Pad 几何通过不等于完整详细布线、回流和电气约束通过。 |
| 热求解器与边界 | [原生 HotSpot 拒绝证据](tap-native-boundary-audit.md)、[当前 FV/HiTS](tap-fv-admission.md) | 原生配置曾存在边界污染内部系数；已明确拒绝。当前模型通过守恒，不宣称复现原生温度。 |
| 搜索结构与基线 | [有限域参考](tap-algorithm-reference-results.md)、[移动结构](tap-search-structure-results.md)、[45 次在线基线](tap-online-pilot-results.md) | 小域连通性和经验 Pareto 改善不证明大域全局最优或稳定优于成熟方法。 |
| 指标修正与监督 | [物理指标迁移](tap-physical-metric-results.md)、[R1](tap-online-r1-review.md)、[R2](tap-online-r2-review.md)、[指标审核](tap-physical-metric-review.md) | Chat 独立读代码/重算证据与本地实际运行分别记账；批准下一阶段不等于研究问题已解决。 |

完整受版本控制的记录索引见 [research-record-index.json](evidence/research-record-index.json)。
该索引包含历史计划、结果、审核、图和紧凑证据及其 Git blob 标识；索引完整不代表
本轮重新独立审核了每一条旧记录。本地原始查询/日志在忽略目录 `results/`，源码依赖
在 `local/`，不把受限模型、环境或大批中间文件提交到 GitHub。

## 接下来的修改顺序

冻结 R3 已完整收尾并经 Chat 审核，保留负结果，不追加种子或事后修改权重。Case1
pin—几何—热链已接通，四向布局状态与热缓存已分离；其三布局检查经 Chat 独立复核后，
已按[冻结协议](atplace-case1-search-protocol.md)完成[单种子小预算比较](atplace-case1-search-results.md)：
同一 NSGA-II 框架，仅比较合法变异与 pin 预算引导，每方法 16 个共同初始热查询加 32 个
在线新热查询，共 96 次。执行与回放通过，主指标及反向指标本次均有收益，但 pin 引导
多花约 5.28 s。332 项测试和两芯粒 CLI 通过；没有追加种子或改变阈值。
Chat 已读取完整代码、结果及相关 Git 历史，独立重算全部 99 行并验收当前有限正收益。
合法双亲交叉已按[冻结协议](atplace-case1-crossover-protocol.md)完成一次同种子、同初始化、
同成本上限的 48 热查询，复用冻结 B 基线；339 项本地测试、两芯粒 CLI 和完整结果回放通过。
[结果](atplace-case1-crossover-results.md)是主指标变热 1.247 K、反向距离改善 17.708%，
不能用零非法提议宣布总体改进。36 次交叉有 24 次退回父代，其中 19 次是不同布局没有
合法混合，下一项应针对具体机制而不是继续强调合法率。
已明确 h 作用面积为 200×200 mm，对流热阻是 0.009 K/W，不将它误称为 0.1 K/W 实测
封装边界；48 次热输入核对尺寸、逐芯粒功率、局部 pins、材料及边界均保持不变。
下一项先让 Chat 复核本阶段已推送的完整代码、记录及物理解释，再确定一个小步干预。
对影响布局决策的物理不确定性，用少量最终候选做独立同条件
对照或有界敏感度核查。需要真实时序结论时，再单独接通明确的接口/通道与时序约束。

每一项验收只记录：**问题、输入与版本、直接证据、通过范围、未完成项、下一项修改**。
保留负结果；默认开发一个种子、主比较最多三个。物理模型需要表达相关现象、满足
基本定律，精度要求应由决策差异决定。
