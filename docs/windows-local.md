# Windows 本地运行与时序语义验收（2026-11-11）

本轮先成功 fetch，快进至 `38db063`，复现 v0.8，再新增独立时序语义实验。
代码保存在 `Documents/GitHub/chiplet_floorplanning`；环境与原始结果分别在
忽略的 `local/`、`.venv/`、`results/`。不需要 WSL、Docker 或管理员权限。

## 在已经配置好的本机继续运行

从项目根目录打开 PowerShell，先执行：

```powershell
git fetch --prune origin
git status --short
git log --oneline -3 origin/main
. ./tools/windows_env.ps1
```

若干净的 main 落后，先 `git merge --ff-only origin/main`。存在本地改动或分歧时，
先保存并核对，不能强制覆盖。每次研究开始和提交前均检查远端。

脚本只设置当前终端的 PATH、Tcl 运行库和单线程 BLAS；不改系统环境变量。
下面的输出目录须尚不存在；再次运行时换一个名称。

```powershell
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/my-slab
chiplet-floorplanning evaluate examples/layered_two_chiplets.json --output results/my-package
python tools/validate_sta_goldens.py --sta local/upstream/OpenSTA/app/sta.exe --output results/my-goldens
python tools/validate_timing_oracle.py --sta local/upstream/OpenSTA/app/sta.exe --output results/my-oracle
python tools/validate_prototype.py --sta local/upstream/OpenSTA/app/sta.exe --output results/my-prototype
python tools/validate_thermal_decomposition.py --output results/my-thermal-e1
```

真实 GPIO 库的联合热—时序 CLI：

```powershell
chiplet-floorplanning evaluate examples/low_speed_gpio.json `
  --sta local/upstream/OpenSTA/app/sta.exe `
  --sky-lib local/pdk/sky130_tt_1v8.lib `
  --gf-lib local/pdk-v03/gf_core_tt_3v3.lib `
  --sky-pad-lib local/pdk-v03/sky_io_tt_1v8_3v3.lib `
  --gf-pad-lib local/pdk-v03/gf_bi_t_tt_3v3_assembled.lib `
  --pad-direction gf180_to_sky130 --period-ns 20 `
  --output results/my-integrated
```

## 从干净环境复建

安装可用的 Python 3.10+ 与 micromamba，进入项目根目录：

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -e '.[validation]'
micromamba create -y -p ./local/toolchain -f tools/windows-toolchain.yml
& .venv/Scripts/python.exe tools/bootstrap_validation.py --build-sta --windows-toolchain local/toolchain --jobs 4
& .venv/Scripts/python.exe tools/prepare_characterization.py
. ./tools/windows_env.ps1
```

本机实际使用已有 Python 3.12.16 创建带 `--system-site-packages` 的 `.venv`，
复用 NumPy 2.5.4 / SciPy 1.18.1；独立新环境可按上面的标准安装步骤创建。
不要误用 Windows Store 的占位 `python.exe`。工具链直接版本固定在 YAML；
确切包构建及 SHA-256、OpenSTA 可执行文件和源码差异哈希写入
`local/build/opensta/build-receipt.json`，差异保存在同目录 `source-patches.diff`。

OpenSTA 固定上游 `02b129d48fbefb57d08f4bc412700ddfa24a159b`。除已有的现代
CMake/SWIG 适配外，Windows 适配包括：显式调用 Tcl 编码脚本；提前声明 size_t；
保留 MinGW 已有的 libc 实现，避免旧 MSVC 宏污染标准头（曾导致 `_stricmp`
递归和 Liberty 读取挂起）；启用 GNU 格式化函数；Tcl 文件参数先取列表元素再
转为本机路径。没有修改时序算法或 PDK 时序表。bootstrap 拒绝其他源码改动。

## 已执行的证据

| 验证 | 本轮本机结果 | 证明范围 |
| --- | --- | --- |
| 单元测试 | 80 项通过 | 已覆盖的软件行为 |
| 两个基础 CLI | 峰温 34.1886 / 60.7473°C | 指定演示输入下的热计算 |
| v0.8 E1 | 1056 次独立求解，全部检查通过 | 线性热源分解、声明边界与 XY 网格检查 |
| 上游 STA | SDF 1、双角 Liberty 2、SPEF 1 条完整报告逐字一致 | 锁定上游回归兼容 |
| TT GPIO prototype | 全部 16 项检查通过 | 原有固定 TT 接口模型及失败对照 |
| GPIO 联合 CLI | 峰温 60.7473°C；setup 8.705309 ns，hold 11.008110 ns | 假设封装线下的既有模型复现 |
| 新增语义实验 | 10 场景 × 4 路径；560 数值字段；8 错误对照均拒绝 | 合成固定延迟和显式 early/late 模型的时序语义 |

语义比较最大绝对误差约 `2e-6 ns = 0.002 ps`，低于预定 `1e-5 ns = 0.01 ps`。
每条路径还检查实际极性、发射/接收对象、完整时钟路径、0.01 pF 负载和约束覆盖。
这不是物理精度数字。名义 setup rise/fall 为 3.3/3.05 ns，hold 为 6.35/6.5 ns；
early/late 组分别为 2.6/2.35 与 5.45/5.6 ns。故意的 setup 与 hold 违例保留为负值。

原始证据位于本机：`results/v08-local-e1/`、`results/v08-local-goldens-2/`、
`results/v08-local-prototype-2/`、`results/v08-local-integrated/`、
`results/timing-oracle-final/`。公开的压缩记录见
[本地验收证据](evidence/v08-local-timing-oracle.json)。新实验也加入 Linux CI；
本机通过与远端 CI 状态分别记录，不互相代替。

Linux CI 的 `--reference` 还要求与冻结的 Windows 输入哈希完全相同，并逐字段
比较全部报告路径的时刻、弧延迟、slew、cap，而不只比较 slack。时间差门槛仍为
1e-5 ns，电容差门槛为 1e-6 pF。在 CI 完成前，跨平台一致性保持待验证。

## 独立监督与未完成项

通过用户指定的 `codex-chatgpt-skill` 在现有 ChatGPT 会话进行只读监督。
第一轮审核发现原参数下正确/错误的 clock rise/fall 组合延迟意外相等，遂在正式
验收前将 inverter fall 由 0.6 改为 0.8 ns，并增加独立 early/late 与结构负例。
事件手算不依赖 STA 输出；规范见 [预定实验契约](timing-oracle-contract.md)。

第二轮监督复核了 early/late 手算，要求明确 oracle 与输入生成器只共享冻结参数，
不共享边沿或路径计算代码。两者现为独立模块，另有固定手算值单元测试。
负例也按证据范围区分：反相/FF 极性/弧交换/early-late 交换属于路径语义；
生成时钟缺失、理想化时钟、错误端点属于结构覆盖；缺少 output delay 属于 I/O
约束覆盖，不能把后者说成跨 die 路径语义的独立证明。Tcl 路径参数适配属于输入
语义修改，不能仅称编译开关；因此保留补丁和跨平台字段比较。

初次负例的 `unset_output_delay` 未指定相应时钟，没有实际删除约束；修正为直接
省略该声明后，STA 明确报告输出未约束并被拒绝。没有放宽验收阈值。
报告固定采用 OpenSTA 2.2 的显示规则：setup 发射 0、hold 发射 P，二者采样均在
fall；分别固定减去 0/P，只改变整体原点，不根据结果挑选周期。

本轮未在 Windows 重跑 ngspice/Verilator 验证。既有 v0.6 的 pad 波形与 Liberty
不一致、热模型未物理校准、pad 温度模型未准入，均保持未解决状态。
本次不能宣称真实 D2D 时序、全 PVT/PHY、温度反馈或联合优化必要性已验证。

下一里程碑先把已审计的边沿契约逐字段映射到真实库接口：独立提取 rise/fall
时钟传播、data arrival、setup/hold constraint、时钟关系及所有端点，保持电气和
查表范围门槛。同时确定决策误差预算及有来源的路由资源案例；若采用合成机制
案例，应明确其资源是假设，不称真实 benchmark。然后比较 thermal-only + 强路由
修复、sequential/alternating 与 joint，在相同预算下判断约束温度代价是否显著。
现有 v0.7 零温度代价对照继续保留，E2/E3/G4 均未关闭。
