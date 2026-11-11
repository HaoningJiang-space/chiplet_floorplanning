# Chiplet Floorplanning

面向 2.5D chiplet 布局的 Power–Thermal–Timing 评估项目。当前版本 **v0.1.0**
实现固定布局的几何检查、空间功耗映射、简化稳态热求解和接口距离/假设 RC 汇总。
尚未接入真实 PDK、RTL 功耗、POSTsim、MFIT、OpenSTA 或布局搜索。

本项目遵循：**验证输入 → 验证评估器 → 验证布局差异 → 开始优化**。
示例中的功耗、材料和 RC 参数全部是合成假设，不代表已测量或已校准的器件。

## 快速开始

需要 Python 3.10+。使用独立环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
chiplet-floorplanning validate examples/two_chiplets.json
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/two_chiplets
python -m unittest discover -s tests -p '*_unittest.py' -v
```

每次评估使用一个新的输出目录，避免覆盖已有结果。输出为：

| 文件 | 内容 |
| --- | --- |
| `input.json` | 本次实际使用的输入快照；统一排序便于比较 |
| `grid.csv` | 单元中心坐标、功率 W、功率密度 W/mm²、温度 °C |
| `report.json` | 功率守恒、热平衡、温度统计、接口距离和 RC、验证状态、输入哈希及软件版本 |

报告在其他文件写入完成后生成。`timing.status` 固定为 `not_implemented`，slack 为
`null`，不会用线长或 RC 代理值填充时序结果。`thermal.calibration` 为 `not_calibrated`。
从源码目录运行时记录 Git commit 与 dirty 状态；从独立 wheel 运行时源码提交可能未知。

## 首版已经实现

- 严格 JSON 字段、有限数值、单位和来源文本检查；拒绝未知字段、重复键和无效端点。
- chiplet 越界、重叠检查；局部块范围检查；0/90/180/270° 旋转及接口变换。
- 将每个矩形块的均匀功率按面积交集分配到热网格；逐块检查功率守恒。
- 均匀薄板、绝热侧面、分布式对环境散热条件下的稳态有限体积求解。
- 分别输出 data 和 forwarded-clock 端点间的曼哈顿距离及用户给定系数下的 R/C。
- 解析解、独立两节点热网络、旋转、非网格对齐功耗、异常输入与 CLI 验证；GitHub Actions。

两芯粒示例总功率为 **3 W**，data/clock 的曼哈顿距离均为 **3 mm**。
距离是无障碍几何下界，没有走线层、拥塞、弯折规则、bump/pad 或串扰模型。
I/O 块功耗由用户给定，当前不另加 link power，以避免重复计数。

## 模型和验证边界

热求解器把整个封装区域当作一个具有统一导热参数的有效薄板。chiplet 位置影响热源位置，
并未改变材料堆叠。该模型适合验证坐标、功率守恒和数值求解接口，不能作为真实封装热分析的结论。
未建模多层材料、接触热阻、瞬态、温度相关漏电、PHY 波形或电压域兼容性。

详见 [输入格式与物理假设](docs/model.md)、[分阶段路线](docs/roadmap.md)
和 [验证记录](docs/validation.md)。公开仓库仅包含源代码、合成输入和文档；
运行结果放在忽略的 `results/`，本机配置放在忽略的 `local/`。

## 参考工具

- [HISIM](https://github.com/mec-UMN/HISIM)：适用架构的分析式模型参考；尚未集成。
- [MFIT](https://github.com/AlishKanani/MFIT)：分块功耗、几何与热求解接口参考；尚未集成。
- [OpenSTA](https://github.com/The-OpenROAD-Project/OpenSTA)：后续跨 die STA 引擎候选；尚未集成。
- [PULP serial_link](https://github.com/pulp-platform/serial_link)：后续源同步链路案例候选；尚未集成。

本仓库没有复制上述项目源码或分发 PDK。后续接入时分别记录上游版本、许可证和模型来源。
