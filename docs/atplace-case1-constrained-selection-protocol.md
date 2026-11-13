# Case1：使选择规则对齐固定距离预算下的降温目标（冻结协议 v1）

2026-11-13 开始，成功 fetch；本地/远端同为
`b6f3955367bc416e32261de5c375df9b576bcbb8`，工作区干净。用户明确要求只改选择规则，
先单种子、小预算对照，关注物理合理性，仅本地运行并及时 push。

## 问题、直接基线与唯一干预

原 E 用无约束的 `(T,L)` NSGA-II 排名/crowding 选择父代和生存者，但报告主指标是
`min T subject to L≤L0`。温度很低、距离明显超预算的布局可以占据原种群。
本轮问题：**将选择优先级直接对齐主指标，是否在同热查询额度下改善可行最低峰温？**

直接基线 E=`nsga2_pin_guided_slack_pool`，绑定上述 commit 的
`docs/evidence/atplace-case1-guided-slack-v1.json` 及其冻结计划。冻结前核对 Git 字节、
源码/输入哈希并回放保存响应，不重跑 E 热计算。B/C/D 仅作为保留的历史联合指标参考，
不因对照 E 较弱就宣布新方法优于所有方法。

新方法 F=`ga_length_constrained_slack_pool`，是以主约束目标选择的精英遗传搜索，
不将它称为原无约束 NSGA-II。只改变父代 tournament 与每代生存者选择的同一优先级；
交叉调用 E 的原函数、原四候选 pin 预筛、原变异/概率、原图/slack 表示及解码均不变。
这轮检验两处一致使用该选择策略的整体作用，不分解父代/生存者各自的贡献。

## 选择优先级的精确定义

所有行都用已完成且通过准入的实际 `(T,L)`。L0 沿用冻结原值，含等号，无额外容差。
排序键越小越优：

- 可行 `L≤L0`：`(0, T, L)`。可行性优先；可行布局中温度优先，温度完全相同时才选短 L。
- 不可行 `L>L0`：`(1, L-L0, T)`。先减少超预算量，完全相同时才选低 T。
- 两个键完全相同时，父代仍使用原随机平局规则；生存者仍使用原随机 tie 值。

字典序比较不把米和摄氏度相加，不引入惩罚权重或虚构温度。共同加上 273.15 改用
开尔文不会改变顺序。两个候选都超预算时并未被当作热失败，它们的真实响应仍保留。

初始种群不筛掉不可行布局，保留与 E 相同的有序 16 行（其中 4 行满足 L0），保证公平。
生存者从父代与本代完整子代中按上述键选择 16 行，不再按 Pareto rank/crowding 排序。
新增日志保存父行的选择键、每完整代的选择键和距离可行数、完整/热状态多样性。
策略可能减少无约束前沿的多样性，也可能舍弃有用的暂时不可行探索点；这是本轮要
观察的代价，不预先添加保留比例、温度分箱或额外局部搜索。

## 预算、档案与指标

Case1，seed `2026111200`，population 16，共同有序 16 初始布局；F 独立空热缓存，
16 初始+32 在线新热查询，共 48。中心网格和间隙 1 mm。提议上限 512、pin 调用上限
2048、几何候选检查上限 2,000,000；共同初始化 21 次未保留提议和 559,192 次检查照计。
交叉概率 0.9，每芯粒变异概率 1/6，E 的 4 候选池及去重/计费方式原样沿用。

主指标为 `L≤73.840208806 m` 的最低峰温；反向指标为
`T≤107.45047721858577 °C` 的最短 pin Manhattan 总距离。前者指导新种群选择，
后者继续作为重要代价指标，不声称两个方向都得到同等选择压力。
全部已评估的完整布局都留在全局记录中：即使未进入下一代，仍参与最终两个约束指标、
16/32/48 检查点和无约束 Pareto 档案计算。绝不只从最终种群挑选结果或拼接极值。

报告真实联合赢家、约束满足情况、候选池/变异/评估的 pin 分账、几何/热成本、
重复/非法/热缓存、每代可行数及多样性。保存 capped/failed，不补预算，不把热失败
转换成高温惩罚。只运行一个固定种子；若结果不好或逆向指标退化，完整保留。

## 物理条件

选择策略只决定哪一套合法刚体布局被继续探索，不修改实际热计算或物理参数。
固定芯粒尺寸、各芯粒功率共 780 W、真实源局部 pins 及其刚体旋转、声明的 underfill、
层厚与导热率、载板/扩散板/散热器、环境和冷却边界。继承 E 的完整非姿态设计签名；
具体共形网格仍随实际布局变化。

温度继续由同一 `G(x) theta=P` 模型计算并通过守恒、被动导热、非负温升、原方程
残差等原准入。顶面对流热阻仍为 0.009 K/W，780 W 下表面均温的守恒推导为
52.02 °C。不会把更低的目标分数当作更低功率或更强冷却；求解检查不等于实测校准。
距离预算是本实验冻结的几何目标约束，不是已验证的走线容量或 RC/STA 时序约束。

## 执行顺序与审核状态

完整测试及 two-chiplet CLI 通过后，冻结本协议、执行源码、基线、输入/场景、预算和
阈值；先 commit/push 并核对远端，再仅本地运行 F 一次。随后保存响应回放事件、
选择键/代记录、实际热输入、pin/布局和全部成本，确认与 E 的 16 初始行完全一致。
结果、图、Overall 及时 push。按用户先前决定保留 Chat 待审核，不发起新的审核请求。

```powershell
. ./tools/windows_env.ps1
python tools/run_atplace_constrained_selection.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-constrained-selection-plan-v1.json --freeze
python tools/run_atplace_constrained_selection.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-constrained-selection-plan-v1.json --hits ../HiTS --output results/atplace-case1-constrained-selection-v1
python tools/run_atplace_constrained_selection.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-constrained-selection-plan-v1.json --report results/atplace-case1-constrained-selection-v1/result.json --output docs/evidence/atplace-case1-constrained-selection-v1.json
```
