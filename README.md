# Chiplet Floorplanning

面向 2.5D chiplet 的热与互连感知布局研究。当前主线：在 ATPlace2.5D 公开案例
（Case1–10，6–61 个芯粒）上比较布局算法，**主指标是相同互连预算下的峰值温度**，
反向指标是相同温度上限下的互连代价。互连代价是源 pin 两端 Manhattan 长度下界，
不是实际布线长度或时序；热模型是声明材料的稳态有限体积模型，未经实测校准。

- 研究记录总入口：[overall-research-status](docs/overall-research-status.md)
- 当前联合移动布局实验用 `tools/compare_successors.py` 运行，结果用 `tools/audit_successors.py` 复核。[案例、预算与本地复现命令](docs/successor-placement.md#本地复现)
- 指标定义：[tap-r3-metrics](docs/tap-r3-metrics.md)；物理准入：[physical-admission-contract](docs/physical-admission-contract.md)
- 代码精简与历史结果复现：[code-history-and-replay](docs/code-history-and-replay.md)

## 快速开始

需要 Python 3.10+。

```bash
python -m pip install -e .
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning validate examples/two_chiplets.json
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two_chiplets
```

导入 ATPlace 案例（固定源提交 `fe3dbfd`）：

```bash
git clone https://github.com/PKU-IDEA/ATPlace_pub ../ATPlace_pub
python tools/import_atplace_cases.py --source ../ATPlace_pub --output results/physical-calibration/atplace-import-v1
```

载板尺寸与布局联合优化默认使用 `cosize_rect`。以下命令需要与参考证据匹配的锚点布局。将 `ANCHORS` 替换为包含 `Case1/wl/layout.json` 的目录。

```bash
python tools/run_cosize.py --case results/physical-calibration/atplace-import-v1/Case1.json \
    --reference atp_wl --anchor-dir ANCHORS --output results/case1-atp_wl-cosize_rect.json
```

同资源基线使用 `--method fixed_aspect`。冻结的 v8 正式实验按提交 `76173f3` 复现。[方法与历史入口](docs/code-history-and-replay.md#cosize-主流程)

## 代码结构

| 位置 | 内容 |
| --- | --- |
| `src/chiplet_floorplanning/placement/` | 布局核心：数组化案例与布局、合法性、源 pin 距离、ATPlace 案例的 FV 封装热评估 |
| `src/chiplet_floorplanning/{model,mesh,power,package,thermal}.py` | 严格 JSON 输入、贴合网格、功率栅格化、分层封装热网络组装与求解 |
| `src/chiplet_floorplanning/cli.py` | 固定布局评估：`input.json`、`grid.csv`、`report.json`；时序明确记为 `not_run` |
| `tools/import_atplace_cases.py` | ATPlace 原始案例的严格导入 |
| `tools/replay_at_commit.py` | 在历史提交的 worktree 中复现冻结实验 |

`evaluate` 的输出目录必须是新的。报告包含功率守恒、热平衡、温度统计与输入哈希；
`thermal_external_validation` 为 `not_run`，`timing.status` 为 `not_run`。
JSON 长度单位为 mm，功率 W，温度 °C；输入契约见 [model](docs/model.md)。

早期工作线（TTC 实测拟合、Pad/SPICE、OpenSTA 时序、Xyce Fabric、TAP/HiTS 在线搜索、
ATPlace Case1 逐阶段搜索）的代码已从 HEAD 删除，结论与证据保留在 `docs/`，
代码可按 [复现说明](docs/code-history-and-replay.md) 在原提交中运行。
