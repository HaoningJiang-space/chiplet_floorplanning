# Case1：相对分离关系与可调空隙的布局表示（冻结协议 v1）

开始版本 `a99e9763275f559831554abb83a9ce24a8eea1da`，2026-11-12 成功 fetch，
本地与远端一致。承接已经 Chat 审核的 19 对父布局整体继承锁定问题。
假设：**继承可行相对关系，再重组归一化空隙，能越过绝对坐标混合的锁定，且在
同样热查询预算下改善受约束布局质量。** 几何新颖性和目标质量分别验收。

## 研究依据与物理含义

[Adya / Markov：Fixed-outline Floorplanning Through Better Local Search](https://vlsicad.eecs.umich.edu/BK/parquet/iccd_2001_floorplan.pdf)
研究固定外框与 floorplan slack；面积紧凑解并不一定是互连目标的最优解。
[Logan / Guthaus：Fast Thermal-Aware Floorplanning using White-Space Optimization](https://fuuu.be/polytech/ELECH541/2009_Fast%20Thermal-Aware%20Floorplanning%20using.pdf)
区别软块扩面积和硬块周边留白，并在热布局中研究空白分配。其方法采用 SA、sequence
pair、HotSpot 及自己的加权目标。本实验借鉴“相对约束和留白应分开”的思路，
不是上述论文的实现复现，也不借用其温度收益或边缘冷却结论。

我们的芯粒是固定矩形硬块。留白只改变刚体位置，不改变硅面积、功率密度、TIM 厚度、
导热率或边界；间隙仍由既有 underfill 模型描述。既不把空隙视为主动冷源，也不预设
“间距越大越冷”。实际热响应由同一个稳态方程 `G(x) theta=P` 求解，pin 距离由旋转
后的原始局部 pin 计算。相对关系图是几何约束，不是热导网络或电连接网络。

## 表示和确定性解码

芯粒身份顺序固定。输入为满足既有中心网格、外框及间隙的完整布局。

1. 每对芯粒，从父布局中选择一个已成立的 x 或 y 有向分离关系。网格单位距离要求
   `d_ij=ceil(((s_i+s_j)/2+gap)/grid)`，包含旋转后的真实尺寸。若两轴都满足，选
   `abs(c_j-c_i)-d_ij` 较大的轴，相等选 x。每对恰有一条约束。
2. 每个轴的边都沿父布局中心坐标严格递增，因而无环。源序号打破无关节点的排序
   平局。外框给出整数中心下界 `ceil(s_i/(2 grid))` 和上界
   `floor((outline-s_i/2)/grid)`。
3. 逆拓扑遍历计算最迟可行位置 `U_i=min(outline_upper_i, U_j-d_ij)`，为所有
   后继预留空间。前向遍历时，实际下界 `L_i=max(outline_lower_i, c_j+d_ji)`
   依赖已放置的前驱。
4. 编码每轴的相对空隙 `u_i=(c_i-L_i)/(U_i-L_i)`，保存精确整数分子/分母；
   区间退化时设为 0。解码位置为 `L_i+round_half_up(u_i*(U_i-L_i))`，乘回 grid。
   两轴独立解码，四分之一转方向属于拓扑部分。

合法性依据：前驱选定位置不超过其 U；逆向约束保证前驱位置加所需间距不超过当前 U。
因此每次前向选择的区间都非空，并保留后续的可行空间。每对至少有一轴满足所需分离，
外框也满足。不需要“先重叠再惩罚”，也不需要缩小或移动封装边界。自己的编码可精确
还原自己的网格坐标；每次仍调用原有完整几何检查作为实现核对。

## D 交叉算子及实验范围

新方法 D=`nsga2_pin_guided_slack`，直接对照已审查 C=`nsga2_pin_guided_compatible`。
保留 B=`nsga2_pin_guided` 的历史联合指标作为参考，避免只对较弱主指标的 C 报告收益。

- 沿用 C 的 tournament、0.9 交叉概率和每芯粒 1/6 原 pin-guided 变异。触发交叉时，
  编码 A/B 两个父布局，均匀选择一个父代的完整分离图和方向集合。
- 均匀抽取 `1..2^n-2` 的非纯亲掩码，每个芯粒的 x/y 空隙系数成对来自 A 或 B，
  在所选可行拓扑中重新解码。只有一个芯粒时掩码为 0。没有候选热预筛。
- 掩码混合不保证几何新颖。解码结果与两个完整父状态比较，分别记为
  novel_reconstruction / parent_reconstruction，不重抽直到“成功”。
  不交叉时复制 A，之后仍执行原变异。
- 当前改动保留一个父代的整套分离图与方向，并非任意混合两套图。拓扑改变和方向探索
  仍可由原变异及后续重新编码产生。本轮检验的是这个具体表示/重组算子组合，不声称
  已隔离“仅表示”与“仅交叉概率分布”的因果贡献。
- 种群仍存储实际物理布局；每次交叉重新编码，避免旧隐变量在变异后失效。热缓存、
  pin 评估、选择、档案均依据实际布局，新方向不被热等价吞掉。

每次完整交叉支付 3 次几何检查（双亲编码、子代解码），另报告两次 `n(n-1)/2` 拓扑
对检查。仅做有限图遍历和有理数运算，不枚举 `2^n` 候选，也不隐藏热/优化求解器调用。
几何计数记录的是调用次数，各算法单次工作的差别不能用这个数当作严格等效运行时间。
保存父行、编码、图、继承掩码、解码前后、新坐标数及完整代多样性，供确定性回放。

## 固定预算、指标与物理条件

Case1、seed `2026111200`、有序 16 个共同初始布局、population 16；中心网格与最小
间隙都是 1 mm。D 独立空热缓存，16 初始+32 在线新热求解，共 48；提议最多 512，
pin 调用最多 2048，几何检查最多 2,000,000。共同初始化的 21 次未保留提议和
559,192 次检查照计。C 历史基线只回放保存热响应，不重跑。

主指标：原 L0=73.840208806 m 以内的最低峰温。反向指标：原
T0=107.45047721858577 °C 以内的最短总 pin Manhattan 距离。两者都保留完整实际
联合点，不拼接不同布局的最小值。保留 16/32/48 检查点、未达约束、成本及负结果。
合法率/新颖率仅是机制诊断，不替代上述指标。只用这个种子，不因结果增加预算。

原场景签名完整沿用：42 mm 载板，固定芯粒尺寸与逐芯粒功率，共 780 W；100 mm
扩散板、200 mm 散热器；45 °C 环境、整片 0.04 m² 顶面
h=2777.777… W/(m² K)，其他外表面绝热。顶面对流热阻 0.009 K/W、守恒推导面积平均
表面温度 52.02 °C。不是实测封装热阻；不调整冷却条件以制造算法收益。
每次实际热输入核对除刚体姿态外的完整设计签名，沿用守恒、被动导热、温升和求解准入。
具体共形网格会随位置变化。Pin Manhattan 仍是几何代理，本轮没有真实 RC/STA 闭合。

## 执行与验收

freeze 时绑定已审查 C commit `3cb5769af9a91d768276737d858fee8f55f6aef4`、源输入、
历史证据/清单、所有执行代码和本协议。复用其物理签名、预算、阈值和初始布局。
先完整测试与 two-chiplet CLI、commit/push 后再只在本地运行 D 一次。结果用保存响应
回放所有事件、实际热输入、布局/pin 指标、成本和多样性，核对 16 初始行完全一致。
输出 capped/failed 原因，不将失败伪装成高温。结果与 Overall 及时推送后交 Chat 审核。

```powershell
. ./tools/windows_env.ps1
python tools/run_atplace_slack.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-slack-plan-v1.json --freeze
python tools/run_atplace_slack.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-slack-plan-v1.json --hits ../HiTS --output results/atplace-case1-slack-v1
python tools/run_atplace_slack.py --input results/physical-calibration/atplace-import-v1/Case1.json --plan docs/evidence/atplace-case1-slack-plan-v1.json --report results/atplace-case1-slack-v1/result.json --output docs/evidence/atplace-case1-slack-v1.json
```
