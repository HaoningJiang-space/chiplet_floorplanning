# Case1：空隙重组的距离预算引导（冻结协议 v1）

2026-11-13 开始，成功 fetch；本地/远端同为
`5c7ba81eb334ec0322e07142dc644820f8a09116`，工作区干净。
用户已选择本轮先保留 Chat 待审核，随后要求继续。本轮继续本地算法实验，不启动
新的 Chat 请求，也不把尚未审核的 D 写成已获独立认可。

## 一个问题

D 的相对分离图/空隙表示已能生成新的合法坐标，但 48 行中仅 17 行满足原主指标
的距离约束，主指标仍不及历史 B。**在空隙交叉中用原距离预算筛选小候选池，是否能
提高同样 48 热查询下的受约束温度质量？** 候选可行率只是机制指标，不能代替温度。
这不是对随机性影响的因果分解；新策略会消耗不同 RNG 序列。

直接基线为 D=`nsga2_pin_guided_slack`，证据固定为 commit
`f373006f1c1705974eda84ba88746056c2a696f1` 的完整记录与计划。冻结前核对 Git 字节，
并用保存响应回放 D，不追加基线热计算。C/B 只保留历史联合指标参考。
新方法 E=`nsga2_pin_guided_slack_pool`。

## 唯一搜索改动

沿用 D 的 tournament、NSGA-II 生存者选择、0.9 交叉概率和原 pin-guided 变异。
仅将一次随机空隙重构，换成最多四个重构候选的距离预算筛选：

1. 与 D 相同，编码两个父布局；均匀选择一个父代的整套几何分离图和方向。
2. 从 `1..2^n-2` 的非纯亲掩码中，不放回均匀抽取最多四个。只有一个芯粒时
   使用唯一掩码 0。每个掩码按 D 的方式继承逐芯粒两个空隙系数并解码。
3. 每次解码后执行完整几何检查，按完整位置/方向去重；同一物理布局只计算一次
   pin 指标，首次出现的掩码作代表。不按热等价键去重，不为了凑齐四个不同布局补抽。
4. 对去重后的候选逐个计算原源 pin Manhattan 总距离。若有 `L≤L0` 的候选，
   在这些候选中均匀选一个；否则在最短 L 的候选中均匀选一个，不放宽 L0。
5. 不提前跳过后续候选。若几何或 pin 上限在候选池完成前耗尽，记录 capped，
   不能从已检查的前缀选择。未被选中的候选不做热求解。
6. 接着执行完全不变的逐芯粒变异和实际布局提交。原变异并不保证保留已有距离
   可行性，所以记录交叉选中点是否满足 L0，以及变异后的结果是否仍满足。
   这轮不同时改变变异，以免混淆干预来源。

不交叉时仍复制第一个父代。图、方向、slack 定义、整数舍入、几何可行域、热键、
完整布局键、指标和约束均未更改。交叉保留一个父代的图，不声称直接混合图拓扑。

每次六芯粒完整交叉支付 2 次双亲编码几何检查、4 次子代几何检查和 30 次拓扑对检查；
实际 pin 筛选次数为去重后的候选数（1–4）。被否决、重复的掩码仍计几何成本。
pin 总账含交叉预筛、原变异预筛、实际新完整布局评估；三项分别报告。
不得把四个便宜候选记为四个热查询，也不得隐藏候选池额外计算。

## 预算和质量指标

与 D 同一 Case1、seed `2026111200`、相同有序 16 初始布局、population 16。
中心网格/间隙 1 mm，E 自己的空热缓存，16 初始+32 在线新热求解，共 48。
上限：512 提议、2048 pin 计算、2,000,000 几何检查；包括共同初始化的 21 次未保留
提议和 559,192 次检查。额外候选池由上述 pin/几何额度支付，不扩大热预算。

主指标仍为 `L≤73.840208806 m` 的最低峰温；反向指标为
`T≤107.45047721858577 °C` 的最短 pin 总距离。保存每个选中真实联合点、未达状态、
16/32/48 检查点及全部 Pareto 行。辅助报告提议、候选池、pin、热查询、几何成本、
重复、非法、种群多样性及墙钟时间。历史墙钟负载不受控，不作速度因果结论。
只运行一次固定种子，不因结果改变阈值、追加种子或扩大预算。

## 物理合理性

预筛使用同一个源 pin 距离，而非新温度代理。候选选择不改变任何材料或冷却参数。
所有实际候选仍由原模型 `G(x) theta=P` 得到温度：固定尺寸硬块、固定逐芯粒功率
共 780 W，原局部 pins 随刚体方向旋转，空隙保持声明的 underfill 材料。
载板/封装尺寸、网格规则、层厚/导热率、环境和 Robin 边界完全复用 D 的物理签名。
顶面 h 作用于 0.04 m²，原对流热阻仍为 0.009 K/W。

候选距离短不代表它一定低温；两项目标的冲突由实际热查询及联合指标检验。
原有守恒、被动导热、非负温升与求解准入全部沿用。Pin Manhattan 是几何下界代理，
不是详细走线或 RC/STA 约束。本轮不引入实物精度或真实热—时序闭合结论。

## 本地执行及记录

完整测试和 two-chiplet CLI 通过后，冻结清单、源码和协议先 commit/push；核实远端
后才本地运行 E 一次。之后保存响应回放全部事件、候选池/预筛、实际热输入、完整
布局指标、成本和代记录，核对与 D 的 16 行初始联合状态完全一致。失败不伪装成高温。
阶段性及时推送，更新 Overall，保留用户指定的 Chat 待审核状态。

```powershell
. ./tools/windows_env.ps1
python tools/run_atplace_slack_guided.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-guided-slack-plan-v1.json --freeze
python tools/run_atplace_slack_guided.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-guided-slack-plan-v1.json --hits ../HiTS --output results/atplace-case1-guided-slack-v1
python tools/run_atplace_slack_guided.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-guided-slack-plan-v1.json --report results/atplace-case1-guided-slack-v1/result.json --output docs/evidence/atplace-case1-guided-slack-v1.json
```
