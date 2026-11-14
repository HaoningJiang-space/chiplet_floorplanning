# 代码精简与历史结果复现

2026-11-13 按用户要求重构并删除不再使用的代码。删除前最后一个包含全部代码的提交是
`f1df9fdd1bf69b714ce83a103cdeaef346d9abfe`（其父提交 `bd1e12b` 为全部 ATPlace Case1 阶段的最后结果）。

## 为什么改复现方式

旧冻结计划把源文件 SHA-256 写入计划，`check_plan` 又逐级调用上一阶段检查
（step_size → tight_budget → temperature_feedback → orientation → routing_boundary →
constrained_selection → slack_guided → slack → crossover → search）。修改任意旧文件都会让下游
全部 `--verify` 失败，于是每个新想法只能新增一层文件，代码与实验都被迫逐步叠加。

现在复现绑定 Git 提交：`tools/replay_at_commit.py` 在证据文件最后一次被修改的提交上建立
detached worktree，只共享 `results/physical-calibration` 中的导入输入（由被复现命令自己核对哈希），
再运行原命令。HEAD 代码因此可以自由重构；冻结证据与原计划文件不变。

## 已验证

2026-11-13 在 eex005（conda 环境 `chiplet-fp`）上，四个带 `--verify` 的阶段均在各自提交通过：

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

CI 工作流文件的同步删除尚未推送：当前 GitHub 令牌缺少 `workflow` 权限。远端 `.github/workflows/ci.yml`
在此之前仍调用已删除的脚本，若被触发会失败；所有提交均带 `[skip ci]`，这不代表远端工作流可用。

删除 281 个文件（约 3.3 万行）：TTC/实测拟合、Pad/SPICE、OpenSTA 时序与温度插值、Xyce Fabric、
共享路由、TAP/HiTS 在线搜索、ATPlace Case1 逐阶段搜索及其测试和锁文件；CLI 不再提供
`--sta` 等时序选项（报告仍明确 `timing.status=not_run`）。`docs/` 中指向已删除脚本的链接
是历史记录，按上面的提交查看。
