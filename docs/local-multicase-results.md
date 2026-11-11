# 本地多案例：真实库时序契约一致性（2026-11-11）

本轮开始成功 fetch，`origin/main` 与本地均为 `c124aa9`，没有新增远端提交。
用户要求仅在本机实验：本轮不 push、不触发远端 CI。实验在该基线加本地改动上
执行，不能将基线哈希误当作新验证代码的完整版本；压缩证据另存实际代码 SHA-256。

## 已完成的实验

| 内容 | 实际执行 | 结果及含义 |
| --- | --- | --- |
| 软件测试 | 85 项 | 全部通过，包括非对称手算约束表、轴交换、表外查询、负 hold、条件弧拒绝 |
| 两芯粒基础 CLI | `two_chiplets.json` | 3 W，峰温 34.1886°C；此基础例未运行时序 |
| 核心时序 | 33 个参数配置 | 25 个 SKY × GF 库组合、原 TT、冷热端点、均温、三个局部加热、热场采样 |
| GPIO 时序 | 9 个参数配置 | 4 个合格线长及 5 个时钟条件，逐一检查四种 setup/hold × rise/fall 路径 |
| 完整时序路径 | 42 配置 × 4 = 168 | 契约核对全部通过；41 个配置满足模型时序，1 个配置保留负 setup |
| 查询记录 | 核心 708、pad 144、接收约束 168 | 当前路径使用的查询全部在各自表域内；传播查询记录同时比较 delay 和 slew |
| 失败对照 | 2 个电气 + 5 个结构/约束 | 按预定条件拒绝；工具进程失败不计作负例通过 |
| 公开热输入 | 3 个 MFIT + 1 个 RapidChiplet | 数值对照/网格检查通过；物理校准仍未完成 |

42 个配置来自 **两类电路**，不能当作 42 个独立设计或统计独立样本。
原始结果在 `results/local-multicase/`；最终时序复核为 `bridge-reviewed/`，
汇总为 `summary.json`。`bridge-1/` 与 `bridge-final/` 保留早期诊断，不用于本轮最终结论。
可版本化压缩证据见 [local-multicase-validation.json](evidence/local-multicase-validation.json)。

## 时序：现在能够说明什么

OpenSTA 在这里求解的是显式给出的源同步寄存器路径：数据在上升沿发出，随路
时钟经接收反相器后采样。chiplet 边界本身不会自动提供封装、电压转换、PHY、
时钟关系或协议模型；这些必须由 netlist、Liberty、SPEF 与约束明确提供。
本轮只审核既有核心和低速 GPIO 测试电路，不扩展到异步链路、CDR 或完整 PHY。

三层证据需要分别理解：

1. 既有 [合成时序事件实验](timing-oracle-contract.md) 用预定固定弧和事件手算检查语义。
2. 本轮检查真实库电路的端点、完整 pin 顺序、边沿、弧身份、min/max、生成时钟、
   约束覆盖、required time 与 slack。传播账目使用 STA 的增量，不独立验证传播物理。
3. 直接查询实际加载的源 Liberty，检查核心/pad NLDM 和接收 setup/hold。
   输入 slew 与 Ceff 来自 STA，因此不构成独立 Ceff、RC 或晶体管仿真。

SKY 与 GF 接收约束模板的两个轴顺序不同，按模板声明解释，不能固定轴顺序。
GF 发射 FF 的 CLK→Q 弧未声明可选 `timing_sense`；记录为 null，并检查
`clocked_on=CLK`、`timing_type=rising_edge` 和实际输入边沿。没有补造该属性。
组合弧仍必须匹配所需的正/负单调性，GPIO 必须匹配固定使能条件。

预定容差保持 `1e-5 ns = 0.01 ps`。核心源表查值最大偏差
`4.8932716368e-7 ns`，路径/约束核对最大偏差 `2.3990000031e-6 ns`。
这些是数值一致性误差，不能解释为物理精度。

以 3 mm、20 ns、50% 占空比为基准，最小 setup/hold 为约
`8.705309 / 11.008113 ns`。固定其他输入后的定量检查如下：

| 诊断变化 | setup 预期变化 / ns | hold 预期变化 / ns |
| --- | ---: | ---: |
| 占空比 40% | -2 | +2 |
| 占空比 60% | +2 | -2 |
| 周期 40 ns | +10 | +10 |
| setup/hold uncertainty 0.1/0.05 ns | -0.1 | -0.05 |
| 周期 2 ns | -9 | -9 |

全部符合预定容差，同时确认实际 pin/cell/transition 相同，传播增量和 slew
未发生超过容差的变化。2 ns 案例的最小 setup 为 `-0.294691 ns`，正确报告
`valid_timing_violation`。这些周期是诊断输入，不是有来源的工作负载需求。
0.1–6 mm 匹配线长的 setup 差异小于当前数值门槛，不能据此宣称细微排序可靠。

12 mm 和原 SKY→GF 方向在 STA 成功执行后出现明确电气限值违规，记录为
`electrical_rejected`，不输出合格 slack。五个错误对照分别为反相关系、生成时钟、
接收端点、输出约束、不确定度。后两类覆盖问题不能冒充独立通道物理验证。
结果区分 `valid_timing_pass`、`valid_timing_violation`、`electrical_rejected`、
`table_domain_rejected`、`semantic_mismatch` 与 `tool_execution_failure`。

## 热：正确性边界与高温结果

| 输入 | chiplets | 功率 / W | 模型峰温 / °C | 末级峰温网格变化 / K |
| --- | ---: | ---: | ---: | ---: |
| MFIT uniform | 4 | 6.024 | 80.106352 | 0.026459 |
| MFIT nonuniform | 4 | 9.897057 | 115.821999 | 0.033757 |
| MFIT heterogeneous | 3 | 6.2878 | 81.470236 | 0.020203 |
| RapidChiplet original | 16 | 328 | 285.587241 | 0.000453 |

三组 MFIT 是相同热网络的数值参考，最大温度差约 `1.83e-11 K`。
四组能量平衡残差绝对值不超过 `1.35e-10 W`，末级网格变化低于预定 0.1 K。
这些证明指定方程、离散和输入的数值一致性，并不确定实际封装材料与散热边界。

尤其是 328 W 的 16-chiplet 输入，在假设堆叠和边界下得到 **285.587°C**。
收敛通过不代表硬件可以工作；此案例不能作为合格热设计。没有为降低该温度而
调整散热参数，也没有给它制造 STA 结果。不同案例的功率、堆叠和几何不同，
四个温度不能直接用于布局优劣排名。

## 本机复现

在已配置的 Windows 环境进入工程根目录。先 fetch 核对新提交，保留本地改动；
以下演示使用尚不存在的 `results/my-multicase`，重复运行时更换输出目录。

```powershell
git fetch --prune origin
git status --short
git log --oneline -3 origin/main
. ./tools/windows_env.ps1
python tools/bootstrap_validation.py
python tools/prepare_characterization.py
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/my-multicase/basic-cli
python tools/validate_characterization.py --sta local/upstream/OpenSTA/app/sta.exe --output results/my-multicase/characterization
python tools/validate_open_thermal.py --output results/my-multicase/open-thermal
python tools/validate_interface_bridge.py --sta local/upstream/OpenSTA/app/sta.exe --characterization results/my-multicase/characterization --output results/my-multicase/bridge-reviewed
python tools/summarize_local_multicase.py --root results/my-multicase
```

缺失工具链时先按 [Windows 环境说明](windows-local.md) 配置。原始 PDK、环境、
完整实验日志仍留在忽略目录，不复制到版本控制。汇总保留源报告、可执行文件、
输入和加载库的哈希链，压缩证据记录验证代码哈希与本地测试结果。

## 研究监督与下一步科学问题

通过用户指定的 `codex-chatgpt-skill` 在既有 ChatGPT 会话只读审核。监督意见要求
限制“独立验证”的表述、绑定实际使用弧、增加定量时钟控制、分离失败类别；本轮
已实现上述检查。实验由本机运行，监督对话没有触发远端实验。

当前里程碑是 **真实库时序契约一致性**。pad SPICE–Liberty 的既有不一致、
pad 温度模型、跨电压核心实验的物理接口、热物理校准仍未关闭。
接下来先核对 pad 表征条件与独立 SPICE/IBIS 响应，补有来源的时序需求、
路由资源及散热边界，建立决策误差预算。

随后才检验科学问题：在固定资源和相同计算预算下，热优布局经强路由修复后
是否仍不能满足可信的时序约束，以及联合方法的温度收益是否超过模型/离散误差。
比较 thermal-only + routing repair、sequential/alternating 和 joint；保留已有的
零温度代价对照。当前实验不证明联合优化必要，不据此启动无依据的优化器竞赛。
