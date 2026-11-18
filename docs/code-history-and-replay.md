# 代码精简与历史结果复现

2026-11-13 按用户要求重构并删除不再使用的代码。删除前最后一个包含全部代码的提交是
`f1df9fdd1bf69b714ce83a103cdeaef346d9abfe`（其父提交 `bd1e12b` 为全部 ATPlace Case1 阶段的最后结果）。

## 2026-11-15 第二次精简

按用户要求删除已结束研究线的代码，并去掉只写进输出的源文件/摘要 SHA-256（保留"案例与冻结前沿一致"和"冻结计划未被改动"这两类输入身份核对）。
删除前最后一个包含这些代码的提交是 `b88d869`，复现时在该提交运行原命令（`tools/replay_at_commit.py` 同样适用）：

| 删除的代码 | 对应结果 |
| --- | --- |
| `tools/receiver_constraints.py`、`tools/characterize_receiver.py` | [接收端 setup/hold 扣除](receiver-constraint-plan.md) |
| `tools/interface_margin.py`、`thermal.pin_temperatures_c` | [按实际温度计时](interface-margin-plan.md) |
| `tools/package_leverage.py`、`thermal_case_data` 的 TIM/盖厚/h 倍数参数 | [封装杠杆](package-leverage-plan.md) |
| `tools/throughput_knob.py` | [逐芯粒功耗旋钮](coupling-search-plan.md) |
| `tools/bound_routing_screen.py` | [布线筛查下界](routing-screen-bounds.md) |
| `tools/diagnose_superposition.py`、`placement/surrogate.py` | 单芯粒叠加代理（只用于筛查，当前工作不用） |
| `Layout.to_placements`、`import_atplace_cases.rotate_offset` | 无调用者 |
| `tools/cold_plate_tradeoff.py`（在 `4c47cef` 复现） | [冷板取舍](cold-plate-tradeoff-plan.md)；流量拟合函数移入 `tools/cold_plate_joint.py` |
| `tools/workload_search.py`（在 `9f56049` 复现） | [负载直接搜索](coupling-search-plan.md)；其保存的布局由 `tools/robust_modes.py` 读入 |
| `tools/sku_floorplan.py`（以下均在 `46ecef8` 复现） | [多 SKU 布局](sku-floorplan-plan.md) |
| `tools/workload_leverage.py`、`tools/robust_modes.py` | [负载杠杆](coupling-search-plan.md)、[鲁棒模式](robust-modes-plan.md) |
| `tools/boost_headroom.py`、`tools/self_mutual_split.py` | [b_max](boost-headroom-plan.md)、[自热/互热分解](overall-research-status.md) |
| `tools/cold_plate_joint.py`、`tools/cold_plate_air_control.py`、`thermal.solve_cold_plate`、`thermal_case_data` 的冷板参数、`Evaluator` 的 `cold_plate` 参数 | [冷板联合设计](cold-plate-joint-plan.md) |

空气散热器的默认配方未变：加入冷板时固定输入下峰温与之前逐位相同（固定值 48.38459530567995 °C）；删除冷板时再次核对，`placement_core_unittest` 的合成例峰温删除前后同为 116.01412369595657 °C。

## 2026-11-17 第三次精简

按用户要求（"后续不用的代码可以删掉"）删除已被取代或已出结论的代码。删除前最后一个包含它们的提交是 `33ad191`，复现时在该提交运行原命令：

| 删除的代码 | 对应结果 |
| --- | --- |
| `placement/cosize.py` 的联合尺寸 MILP（`cosize`、`sized_milp` 等）、`cost.max_height`、`lp.milp_relations` sizing 的高度上限/最小面积/高度下限三项 | [cosize v1/v2](cosize-plan.md)，由 [v3.1](cosize-v3-plan.md) 取代 |
| `placement/superpose.py`、`tools/superpose_check.py`、`thermal_case_data` 的 `spreader_mm` | [单芯粒场叠加](superposition-model-plan.md)（判定不采用） |
| `tools/envelope_check.py`、`tools/polygon_check.py`、`tools/polygon_milp_check.py` | [多方向投影](polygon-distance-plan.md)（判定采用 K=8，已并入 cosize） |
| 上述代码的单元测试，及 `research_regressions` 中针对它们的控制 | [复核证据](evidence/research-fixes-af855d2.json) |

`lp.milp_relations` 的 sizing 基本形式（宽度档、面积上限、排除档）仍由 `tools/run_sizing.py` 使用，保留。

## 2026-11-17 第四次精简

sizing-v1（联合尺寸 MILP 对"先定尺寸再布局"）已跑完，并已被 cosize v3/v4 取代；它的结果没有保存布局，只作探索性标量记录（[处置](sizing-placement-plan.md)）。
删除前最后一个包含下列代码的提交是 `cfbd9dc`：

| 删除的代码 | 对应结果 |
| --- | --- |
| `tools/run_sizing.py`（`shapes`、`width_levels`、CLI）、`tools/sizing_compare.py` 及其测试 | [sizing-placement 计划](sizing-placement-plan.md)、[修订](sizing-plan-revisions.md) |
| `lp.milp_relations` 的 `sizing` 参数（宽度档、面积上限、排除档） | 同上 |

`run_sizing.run_front` 仍被 cosize 基线使用，移入 `placement/methods.relation_front`，行为不变；成本参数扫描 `SWEEP` 移入 `tools/cosize_compare.py`。

## cosize 主流程

`tools/run_cosize.py` 默认使用 `cosize_rect`。它复核参考布局后，保留关键链翻转、最小线长 MILP、映射修复和 relation_space 的级联，以及剩余预算下的联合尺寸 MILP。在每个固定目标上，先将父布局居中平移，只要几何合法就尝试一次 FV。这样也能利用小载板上原本空着的边缘。

原始锚点和级联新认证的布局都可触发矩形查询。固定父布局的旋转和分离关系，依次试固定高、固定宽。每次用 LP 求满足引脚曼哈顿总长预算的最小另一边，包括芯粒内部连接的常数。候选按 0.1 mm 网格向上取整，长短边比至多 3。对成本可能更低的候选重新求最短线长布局、取整、核对几何，再执行原有 SLP 和 FV 认证。两个方向共享全局预算。矩形查询失败只影响该次尝试，原比例的搜索仍可继续。

v4 连续缩放、v5a 先筛后搜、v6 逐轮淘汰和 v7 原级联均未通过各自冻结的准入试跑，已移除这四个运行入口和专用测试。联合尺寸 MILP 从 v6 模块移入当前调度器。历史 JSON 仍由 `tools/cosize_compare.py` 读取。默认方法以 `method=cosize_rect` 单独记账，沿用 v8 的认证协议。比较器只在出现其结果时增加探索性统计。

清理前最后同时包含四个入口的提交为 `64d899e`。查阅旧入口可以运行

```bash
python tools/replay_at_commit.py --commit 64d899e -- python tools/run_cosize.py --help
```

逐次复现使用各计划记录的实际运行提交、输入和资源。冻结 v8 的运行提交为 `76173f3`。[v4](cosize-v4-plan.md) · [v5a](cosize-v5-plan.md) · [v6](cosize-v6-plan.md) · [v7](cosize-v7-plan.md) · [v8](cosize-v8-plan.md)

从记录格式 `cosize-v8.1` 起，所有方法都将芯粒间距写入 `gap_um`。配对要求间距一致，并逐文件检查实际运行的案例、参照和方法。冻结 v8 的旧记录未保存间距，重放时应使用原命令中的设置。若锚点违反几何要求，结果会列出越界芯粒和间距冲突，FV 计数为零。

`cosize_rect_crop` 与 `fixed_aspect_crop` 分别在矩形搜索和固定比例搜索后尝试一次紧裁。总预算至少为 2 次 FV 时，两者都预留最后一次。主搜索返回后，取其最低有限成本的认证布局。若只复核了锚点且搜索没有有限成本解，则尝试裁锚点。固定芯粒朝向和相对位置，将占用跨度向上取到 0.1 mm 网格，再满足 3:1 的长短边比。整体平移尽量保持芯粒在封装中的位置。只有几何合法、两边均可容纳于原载板、能严格降价且仍有时间的候选才进入热认证。比较器既能纵向比较同一方法启用和关闭紧裁的结果，也能比较两边都启用的结果。候选尺寸、平移量、父布局成本、认证状态和求解次数记入 `history` 末项。

## 为什么改复现方式

旧冻结计划把源文件 SHA-256 写入计划，`check_plan` 又逐级调用上一阶段检查
（step_size → tight_budget → temperature_feedback → orientation → routing_boundary →
constrained_selection → slack_guided → slack → crossover → search）。修改任意旧文件都会让下游
全部 `--verify` 失败，于是每个新想法只能新增一层文件，代码与实验都被迫逐步叠加。

现在复现绑定 Git 提交：`tools/replay_at_commit.py` 在证据文件最后一次被修改的提交上建立
detached worktree，只共享 `results/physical-calibration` 中的导入输入（由被复现命令自己核对哈希），
再运行原命令。HEAD 代码因此可以自由重构；冻结证据与原计划文件不变。

## 已验证

2026-11-13 在 eex005（conda 环境 `chiplet-fp`，2026-11-16 改名为 `sizing_algorithm`）上，四个带 `--verify` 的阶段均在各自提交通过：

| 阶段 | 提交 | 结果 |
| --- | --- | --- |
| step-size | `bd1e12b` | 两条完整搜索轨迹与收费/实际求解账本通过，无新热求解 |
| tight-budget | `ec6b829` | 两组各 16 个保存响应回放通过 |
| temperature-feedback | `499cf42` | 两组各 16 个保存响应回放通过 |
| orientation | `50185da` | 回放通过 |

更早阶段（search、crossover、slack、slack_guided、constrained_selection、routing_boundary）
没有独立 `--verify` 模式。它们的审核状态各不相同，以[总记录](overall-research-status.md)和各阶段原文为准：
B（search）与 C（crossover）已经 Chat 审核；D（slack）、E（slack_guided）、F（constrained_selection）
只有本地执行与回放通过，**仍待独立审核**；routing_boundary 的 Chat 复核限定于必要条件与边界，
明确未覆盖 D/E/F 的完整算法历史。本地回放通过不等于独立审核完成。

```bash
python tools/replay_at_commit.py --anchor docs/evidence/atplace-case1-step-size-v1.json -- \
    python tools/run_atplace_step_size.py --verify \
    --result docs/evidence/atplace-case1-step-size-v1.json --output results/replay/step-size.json
```

## 新核心与旧实现的等价性

`chiplet_floorplanning.placement` 取代 `tools/atplace_pin_geometry.py` 等文件。删除前在 eex005
上对证据中全部 519 个不同 Case1 布局重算：峰温最大差 1.6e-8 K，pin 长度最大差 2.8e-14 m，
能量守恒误差约 1e-10 W；合成案例上组装出的热矩阵与旧配方逐项完全相等。
新核心不调用 HiTS，直接用 scipy 求解；HiTS 曾只作为数值求解后端，结果与 scipy 参考解一致。

## 删除范围

CI 工作流的同步清理在 `2d2227a` 推送：HTTPS 推送使用的 gh OAuth 令牌没有 `workflow` 权限，
改动工作流文件需经 SSH 推送。此前远端工作流仍调用已删除脚本；现在只运行单元测试和两个示例 CLI。

删除 281 个文件（约 3.3 万行）：TTC/实测拟合、Pad/SPICE、OpenSTA 时序与温度插值、Xyce Fabric、
共享路由、TAP/HiTS 在线搜索、ATPlace Case1 逐阶段搜索及其测试和锁文件；CLI 不再提供
`--sta` 等时序选项（报告仍明确 `timing.status=not_run`）。`docs/` 中指向已删除脚本的链接
是历史记录，按上面的提交查看。
