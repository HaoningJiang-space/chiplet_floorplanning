# Case1：热等价朝向修复的单项局部消融

依据 [Chat 复核](atplace-case1-routing-boundary-review.md)，只改一个算子。
协议和候选池在任何新热查询前冻结并推送；全部求解在本地执行。

## 不变的物理和指标

沿用原 ATPlace Case1 源 pins、尺寸、逐芯粒功率（总 780 W）、42×42 mm 载体、
1 mm 最小间隔和中心网格、64 分辨率几何共形 FV、原层叠和名义边界、锁定 HiTS。
主指标 min Tpeak subject to L≤73.840208806 m；反向指标 min L subject to
Tpeak≤107.45047721858577°C。L 是全部实际源 pin 的两端 Manhattan 下界。
保留实际完整联合布局；温度采用现有稳态均匀功耗模型，未接入时序或详细布线。

## 算子和零热验收

按源 chiplet 顺序扫描一次；正方形尝试四个方向，矩形只试当前及加 180°。
固定中心和逐芯粒物理边界，比较精确 Decimal pin 总长度。平局保留当前方向；
其他方向按角度递增，严格更短才替换。一次初始 pin 计算加 12 次替代试验，合计 13。
不重复扫描到收敛，不枚举 512 个组合。保留每次试验、最终朝向和成本。
最终方向通过必要容量检查后才允许热缓存/求解。该规则仅用于此均匀功率、各向同性
材料适配器；非均匀功率图和方向性材料不能使用相同的等价判定。

## 固定候选与公平比较

- 原始 B row 38、D row 45 分别沿每个芯粒 x/y 轴 ±2000 µm 移动一次。
  48 次几何尝试，保留全部合法候选，不依据温度、修复效果筛选或添加候选。
  `random.Random(2026111200).shuffle` 生成两组共用顺序。
- 两组共同热启动档案：原始 B、修复 B、原始 D、修复 D。原始热响应通过精确输入
  身份和已有数值准入核对；修复只复用同一物理边界下的响应。共用成本单列。
- 控制组每个候选保持原朝向；修复组每个候选做一次上述扫描。两组均先计算整个
  固定池的 pins 和必要布线，再按共同顺序取布线通过且 L≤L0 的候选。
  各最多 16 次新热查询；缓存不跨组共享；池不足则停止，不补采样。
- 共享起点避免把处理组独享更好初始点误报为候选生成收益。所有预计算 pin 成本
  （包括预算外候选）计入各组；共同起点的生成成本单列。测试/回放成本另列，
  不混作算法成本。不宣称等 wall time；两组只有新热查询额度相同。
- 固定源、设计签名和边界限定缓存作用域，逐芯粒命名边界作热身份。朝向完整状态
  独立保存；改变位置必须重新求解。每个实际查询记录输入 hash、数值准入及响应。

## 验收与停止

先核对两个锚点修复的边界不变、pins 实际缩短和重新布线准入；冻结候选与代码后
执行两组小实验。保存完整候选记录、热查询和联合点，使用保存响应回放而不新增热查询。
按同 L0 下的峰温与同 T0 下的距离报告，另列共同热启动到最终点的变化。
若没有进一步降温，接受有限负结果；不加种子、移动步长、算子或热校准。
这是 B/D 热启动局部候选生成消融，不是历史冷启动搜索的公平算法排名。

## 本地复现

先加载 `tools/windows_env.ps1`，使用新的输出路径：

```powershell
python tools/run_atplace_orientation.py --freeze --output docs/evidence/atplace-case1-orientation-zero-heat-v1.json
python tools/run_atplace_orientation.py --execute --hits ../HiTS --output results/atplace-case1-orientation-v1
python tools/run_atplace_orientation.py --verify --result results/atplace-case1-orientation-v1/result.json --output docs/evidence/atplace-case1-orientation-replay-v1.json
```

冻结和结果验证也会重新计算 pins，属于零热验收/回放开销，不属于热预算。
正式执行中共同起点需要 2×(1+13)=28 次 pin 计算；候选控制组 25 次、修复组
25×13=325 次，两组都检查全部固定池，即使后面因热预算不再评估某候选。
