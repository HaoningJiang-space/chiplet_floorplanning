# Pad 模型不一致的本地诊断（2026-11-11）

本轮从本地 `2dbd03b` 继续，开始成功 fetch，远端仍为 `c124aa9`。
全部实验在本机运行，不 push、不触发远端 CI。
预先声明的变量、门槛和结论边界见 [实验契约](pad-diagnostic-plan.md)。

## 实验与复现位置

正式 pad 实验使用锁定的 MSYS2 ngspice 42-1，模型源文件保持 v0.6 哈希不变。
旧 14 个瞬态案例复现后，再执行 17 个新配置的 5/2.5 ps 步长对照：
GF 12 个 slew/load 矩阵点、GF/SKY 各两个实际 STA 锚点、一个 SKY 原名义点。
这些是两个 pad 单元的参数配置，不是独立芯片样本。

原始输入、波形、测量和日志在 `results/pad-diagnostic/`：

正式 **48 次 pad 瞬态运行全部完成**；新增 17 组半步长检查通过，最大指标变化
0.1354 ps；90 项软件测试通过。主映射下 17 个新配置均在表域内，但 **0/17**
满足预定的四指标 nominal 一致性门槛。运行通过与模型准入分别报告。

- `baseline42/`：旧 14 点本机复现。
- `matrix/`：新矩阵和锚点；`frozen-inputs.json` 在模拟前保存参数与哈希。
- `capability-isolated/`：无 PDK 的工具执行对照。
- `baseline/`：ngspice 47 初次尝试；保留运行失败，不能计作物理模型失败。
- `source-docs/`、`gf180-tree.json`：本轮检查的固定版本上游资料。
- `summary.json`：主/竞争负载映射、逐配置指标和逐对差分。

## 测量定义没有解释现有不一致

从实际原始库头提取 ns、pF、输入/输出 50% 延迟阈值、GF 10–90% 和 SKY
20–80% slew、`slew_derate_from_library=1`。GF 必须读原 IO 库头，不能从
cell-only Liberty 假定单位。控制引脚的供电域继续使用原有源库检查。
对每份原始波形按照源定义重新测量，并与既有代码比较。

新单元测试采用不对称输入 25% / 输出 75% 阈值的手算波形，防止实现忽略
阈值配置却仍在名义 50% 点通过。错误单位、非单位 derate、表外负载均拒绝。
目前只支持这两套库的显式单位和 derate，不能推广为通用 Liberty 测量器。

这能检查已声明的单位、阈值和 slew 定义，不能排除未知原表征激励波形、
寄生提取、器件参数设置、表征工具或网表版本的差异。

## 两种负载解释和差分响应

GF 主假设 A：`C_axis = C_external + 2.977816 pF`；竞争假设 B：
`C_axis = C_external`。SPICE 都只接外部电容，未重复添加内在电容。
A 保持既有 STA 解释，B 不因个别数值更接近就升级为真实表征定义。
B 在 1/2 pF 点低于源表下界，明确拒绝外推。

GF 12 个矩阵点及两个锚点，在主映射下 delay 差异约 **17.55%–19.05%**。
竞争映射可在域内比较的六个矩阵点，也没有通过完整四指标一致性门槛。
不能用更换负载轴解释关闭 nominal mismatch。

不先减去 offset，直接比较相邻配置的有限差分：

| 变量变化 | rise delay 最大残差 / ps | fall delay 最大残差 / ps |
| --- | ---: | ---: |
| 外部负载每次 +1 pF | 3.8175 | 11.1376 |
| 相邻输入 slew | 11.2673 | 11.1195 |

逐对报告 `(SPICE_B − SPICE_A) − (Liberty_B − Liberty_A)`，以及两个端点的
实测步长变化之和。它是经验数值筛查，不是严格误差界；源表的插值/表征误差
没有被独立量化。不对接近零的变化计算夸大的相对准确率。
即使某一差分接近，也不能修复绝对失配或直接授权 floorplanning 排序。
这些孤立 pad 差异也不是完整 D2D lane slack 的误差上下界。

四个锚点固定取自上一轮 3 mm GPIO 的 `tx_data_pad` / `rx_data_pad`、max 模式、
rise/fall 实际使用弧。冻结 input slew、Ceff、条件和原报告哈希，用集中电容
复现表格工作区域；没有独立验证分布通道或 Ceff 的求解。

负载归属另由锚点日志确认：data net 的 pin C=4.095031261 pF、wire C=
1.035940051 pF、总 C=5.130970955 pF；其中 TX PAD 的 inout C=
2.977816105 pF。锁定 OpenSTA 的 `ReduceToPi::pinCapacitance()` 将库 pin C
加入未内含 pin cap 的 RC 网络。故这里的 Ceff 来自含 TX 自身 pin C 的网络。
减去 2.977816 pF 只定义本次集中负载测试，仍不是原始物理表征负载的恢复。

旧 14 点跨构建的最大变化 2.3955 ps 出现在 SKY；GF 自身最大变化仅约
0.000000171 ps，不能把 SKY 的跨构建变化直接作为 GF 差分的数值误差。
GF 17 对的 delay 残差均超过各自端点步长变化之和；这只支持当前采样点和
数值筛查下的非恒定残差，不给未采样点或真实通道提供误差界。

## 工具执行问题与模型问题分开

所测 MSYS2 ngspice 47 构建在 GF 行为电容展开后产生 `unknown parameter (e9)`。
无 PDK 的最小电容实验，在隔离初始化下比较线性/行为电容和 m=1/4：
ngspice 42 四组均执行；47 线性两组执行、行为两组失败。它复现了相同执行
错误，不能被当作 GF 物理模型不准确的证据，也不能推广到未经测试的所有构建。
正式实验使用 42，没有删除器件或修改 PDK 来绕过该问题。

来源是 [MSYS2 软件包目录](https://repo.msys2.org/mingw/ucrt64/)；归档及其运行库
URL、SHA-256 固定在 `tools/ngspice-windows.lock.json`，安装收据保存在本地。
bootstrap 只提取本地运行文件和许可证，不执行包安装脚本、不改变系统环境。
Windows 的 deck/log 记录改为按同一 UTF-8 字节写入和计算哈希；矩阵逐份复核。

SKY 的空 `condiode` / `com_pad` 和器件/收敛警告仍未消除。数值吻合也不能代替
结构完整性。此前的“热 pad 链路未准入”结论保持不变。

## 上游资料核查与下一步

本次读取 [固定 GF 源树](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_io/tree/2aeec51ea2824b6cc0b396acfc39f4535f40b23a)
的完整 536 个条目，树未截断；检查 bi_t 目录、相关规格及库头。找到 CDL、
多金属层 GDS/LEF、Liberty 和规格，未在检查范围内恢复原始 characterization
deck 或独立 PEX 网表。这不是对所有公开来源均不存在这些文件的证明。
[输出延迟规格页](https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_io/blob/2aeec51ea2824b6cc0b396acfc39f4535f40b23a/docs/delay_output.rst)
标明 4.5–5.5 V 范围，不能直接当作当前 3.3 V TT 点的测量真值。

下一步应恢复原始激励、负载定义、器件设置和提取网表，或明确改用独立验证的
抽象接口开展机制研究。没有来源证据时，不继续靠 offset、频率或散热参数调优
来“修复”模型。不从当前孤立 pad 结果生成温度 derate。

本轮通过 `codex-chatgpt-skill` 的已有 ChatGPT 会话进行只读监督；采用了竞争
假说、源定义重测、实际 STA 锚点和差分误差单独报告等要求。监督审核未代替
本机执行或原始证据。

## 本机复现

先 fetch 检查远端，保留本地更改。输出目录必须是新的。

```powershell
git fetch --prune origin
git status --short
. ./tools/windows_env.ps1
$env:PYTHONUTF8='1'
python tools/bootstrap_pad_spice.py
python tools/bootstrap_windows_ngspice.py
python tools/validate_pad_spice.py --ngspice local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe --output results/my-pad/baseline42
python tools/validate_pad_diagnostics.py --ngspice local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe --anchor results/local-multicase/bridge-reviewed/gpio_length_3mm/bridge.json --output results/my-pad/matrix
python tools/summarize_pad_diagnostics.py --root results/my-pad
```

锚点需先按 [多案例说明](local-multicase-results.md) 运行同一 GPIO，不能用其他
电路的工作点冒充该锚点。紧凑证据见
[本轮记录](evidence/local-pad-diagnostics.json)。
