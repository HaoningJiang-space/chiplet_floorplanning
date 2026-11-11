from pathlib import Path
import argparse
import base64
import html
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

parser = argparse.ArgumentParser(description='Render the fixed passive-channel milestone as standalone HTML and scientific figures.')
parser.add_argument('--input', type=Path, required=True)
parser.add_argument('--summary', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
out, root = args.output.resolve(), args.input.resolve()
out.mkdir(parents=True, exist_ok=True)
summary = json.loads(args.summary.read_text())
effects = summary['channel_effects']
counts, maxima = summary['counts'], summary['maxima']
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                     'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), layout='constrained')
colors = ['#176b91', '#2c9477', '#ca6726', '#8d5ba6']
for color, (driver, slew) in zip(colors, [(25, 100), (25, 600), (100, 100), (100, 600)]):
    rows = sorted([e for e in effects if e['channel']['driver_ohm'] == driver and e['channel']['slew_10_90_ps'] == slew], key=lambda e: e['channel']['length_mm'])
    x = [e['channel']['length_mm'] for e in rows]
    for axis, key in zip(axes, ['rlc_minus_rc_delay_ps', 'rlc_minus_rc_skew_ps']):
        axis.plot(x, [e[key]['rise'] for e in rows], 'o-', color=color, label=f'{driver} ohm, {slew} ps slew')
        axis.axhline(0, color='#aab3bb', lw=.8, zorder=-1)
        axis.set_xticks([1, 3, 6])
        axis.set_xlabel('Wire length (mm)')
        axis.set_ylabel('RLC minus RC (ps)')
        axis.grid(alpha=.15)
axes[0].set_title('Rise 50% channel delay')
axes[1].set_title('Rise skew relative to a 3 mm clock')
axes[0].legend(fontsize=8)
fig.suptitle('Declared ideal geometry | 32 sections, finest recorded step per case', fontsize=13)
fig.savefig(out / 'chiplet-channel-effects.png', dpi=170)
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), layout='constrained')
for model, color in [('RC', '#176b91'), ('RLC', '#ca6726')]:
    data = np.load(root / f'l6_r25_s100_{model}_n32_dt0.0625/endpoints.npz')
    t = data['time_s']*1e9
    for axis, bounds in zip(axes, [(1., 1.7), (4., 4.7)]):
        mask = (t >= bounds[0]) & (t <= bounds[1])
        axis.plot(t[mask], data['far_v'][mask], color=color, label=f'{model} receiver', lw=1.8)
        if model == 'RC':
            axis.plot(t[mask], data['source_v'][mask], '--', color='#777777', label='Ideal source', lw=1)
        axis.axhline(1.65, color='#aab3bb', lw=.8)
        axis.set_xlabel('Time (ns)')
        axis.set_ylabel('Voltage (V)')
        axis.grid(alpha=.15)
axes[0].set_title('Rise')
axes[1].set_title('Fall')
axes[0].legend(fontsize=9)
fig.suptitle('6 mm, 25 ohm, 100 ps source slew | same source and load', fontsize=13)
fig.savefig(out / 'chiplet-channel-waveforms.png', dpi=170)
plt.close(fig)

summary['software_tests_passed'] = 108
summary['basic_cli'] = {'power_w': 3., 'peak_c': 34.1886068, 'timing': 'not_run', 'thermal_calibrated': False}
summary['repository'] = str(repo)
summary['review_url'] = 'https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865'
summary['earlier_attempts'] = {
    'trap': json.loads((root.parent / 'matrix/attempt-status.json').read_text()),
    'gear_original': json.loads((root.parent / 'gear-summary.json').read_text())['counts'],
    'step_refined': json.loads((root.parent / 'refined-summary.json').read_text())['counts'],
    'strict_interrupted': json.loads((root.parent / 'matrix-precision/attempt-status.json').read_text()),
}
completed_unique = (summary['earlier_attempts']['trap']['completed_runs']
                    + summary['earlier_attempts']['gear_original']['completed']
                    + summary['earlier_attempts']['step_refined']['completed']
                    - summary['earlier_attempts']['step_refined']['reused_runs']
                    + counts['completed'] - counts['reused_runs'])
summary['storage_control'] = json.loads((root.parent / 'binary-control/comparison.json').read_text())
summary['cost_control'] = json.loads((root.parent / 'precision-cost-control/report.json').read_text())
(out / 'chiplet-passive-channel.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
def image(name):
    encoded = base64.b64encode((out / name).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{encoded}" alt="{html.escape(name)}">'
def number(value):
    return '交越有歧义' if value is None else f'{value:+.4f}'
rows = ''.join(f'''<tr><td>{e['channel']['length_mm']} mm</td><td>{e['channel']['driver_ohm']} Ω / {e['channel']['slew_10_90_ps']} ps</td>
<td>{number(e['rlc_minus_rc_delay_ps']['rise'])}</td><td>{number(e['rlc_minus_rc_delay_ps']['fall'])}</td>
<td>{number(e['rlc_minus_rc_skew_ps']['rise'])}</td><td>{number(e['rlc_minus_rc_skew_ps']['fall'])}</td></tr>''' for e in effects)
controls = ''.join(f'<li><code>{html.escape(name)}</code>：{"已检出" if value["detected"] else "未检出"}</li>' for name, value in summary['negative_controls'].items())
checks = [
    ('仿真完成 / 已校验完整波形', f'{counts["completed"]}/96 · {counts["waveform_archives_verified"]}/96'),
    ('守恒与独立瞬态核对', f'{counts["numerical_gates_passed"]}/96'),
    ('缩小步长 / 增加线段数', f'{counts["temporal_passed"]}/24 · {counts["spatial_passed"]}/24'),
    ('矩阵方程与独立级联频响', f'{counts["frequency_cascade_passed"]}/72'),
    ('32 段与连续线模型：五个指定频点', f'{counts["fine_frequency_sampled_passed"]}/24'),
    ('细网格唯一阈值交越', f'{counts["fine_scalar_unambiguous"]}/24'),
    ('故意破坏账本的反例', f'{counts["negative_controls_detected"]}/5'),
]
checkrows = ''.join(f'<tr><td>{a}</td><td>{b}</td></tr>' for a,b in checks)
body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chiplet 理想通道 RC/RLC 物理审计</title><style>
body{{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#21303d;background:#f3f6f8;margin:0}}
main{{max-width:1120px;margin:auto;padding:38px 30px 64px}}h1{{font-size:31px;line-height:1.35;margin:8px 0 20px}}
h2{{font-size:23px;margin-top:32px}}.kicker{{font-size:13px;color:#47687c;letter-spacing:.1em}}
.lead{{font-size:18px}}.panel{{padding:22px 28px;border:1px solid #d5e0e6;border-radius:12px;background:white;margin:20px 0}}
.boundary{{border-left:5px solid #bb7c24;background:#fff8ec;padding:18px 24px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px 12px;text-align:right;border-bottom:1px solid #dae3e8}}
th:first-child,td:first-child{{text-align:left}}th{{background:#edf3f6}}img{{width:100%;height:auto}}code{{font-size:13px;overflow-wrap:anywhere}}
.small{{font-size:13px;color:#526575}}a{{color:#176b91}}.scroll{{overflow-x:auto}}
</style><main><div class="kicker">LOCAL RESEARCH · 2026-11-11 · IDEAL PASSIVE CHANNEL</div>
<h1>先核对电荷和能量，再讨论时序</h1>
<p class="lead">完成 12 组条件的 RC/RLC 对照。最终分析使用 {counts['completed']} 条完成记录（{counts['new_runs']} 次新运行＋{counts['reused_runs']} 条核验后复用）。四轮主要矩阵累计完成 {completed_unique} 次仿真，另保留高精度诊断和存储对照；2 次超时、1 次主动中断均有记录。固定几何、驱动与负载，核对每个时刻的守恒。</p>
<div class="boundary"><strong>研究边界：</strong>这是理想结构下的机制对照。真实 Pad、封装电磁参数及原始表征尚未校准，<code>physical_model_qualified=false</code>。热反馈和完整 PHY 时序仍未获准。</div>
<div class="panel"><h2>本轮发现</h2><p>在本组假设下，RC 与 RLC 的 50% 传播延迟最大相差 <strong>{maxima['rlc_minus_rc_delay_absolute_ps']:.4f} ps</strong>；数据线相对固定 3 mm 时钟线的偏斜，最大相差 <strong>{maxima['rlc_minus_rc_skew_absolute_ps']:.4f} ps</strong>。差异依赖长度、驱动阻抗和输入边沿；理想飞行时间不能作为统一常数加到 STA。</p>
<p>相同 3 mm 数据与时钟通道提供公共延迟抵消对照。这里固定“上升对上升、下降对下降”的源事件配对，没有设置人为时钟周期来制造接口通过或失败。</p>
{image('chiplet-channel-effects.png')}</div>
<div class="panel"><h2>检查结果</h2><table>{checkrows}</table>
<p>最大归一化电荷残差 {maxima['charge']:.3g}，逐节点残差 {maxima['local_charge']:.3g}，能量残差 {maxima['energy']:.3g}。独立方程与 SPICE 的端点波形最大差 {maxima['oracle_endpoint_error_v']*1e3:.4f} mV，阈值交越最大差 {maxima['oracle_crossing_error_ps']:.5f} ps。</p>
<p>减半步长后，延迟或 slew 最大变化 {maxima['temporal_metric_change_ps']:.5f} ps；16→32 段最大变化 {maxima['spatial_metric_change_ps']:.5f} ps。五个指定频点的连续线复数传递函数最大绝对误差 {maxima['fine_frequency_absolute_error']:.6g}。</p>
<p class="small">预声明门槛：总电荷 1e-5、逐节点电荷 1e-3、能量 5e-4；波形 0.33 mV、交越 0.1 ps；加密变化 max(0.1 ps, 0.25%)。频响绝对差 5e-4。快边沿最大步长 0.125/0.0625 ps，慢边沿 0.5/0.25 ps。有限加密差不是严格误差界，五个频点不证明整个带宽。108 项软件测试和基础 CLI 通过。</p></div>
<div class="panel"><h2>失败记录仍然有效</h2><p>原梯形积分轮完成 37 次后，一例超过 180 秒上限，旧程序没有保存该超时的终止日志；原轮保留为未完成。后续 Gear 全矩阵完成 96 次，仅 69 次通过：部分短 RC 电荷残差超限，快 RLC 的端点波形不一致。仅缩小最大步长也未清除全部问题。</p>
<p>步长加密轮为 83/96 通过。更严格的诊断设置完成两例后，又出现一次进程超时；随后的一例主动中断，保留部分文件。最终统一采用经单例对照检查的数值设置，并保存原生二进制波形，避免多 GB 文本导出。它保留每个原始采样点，与同次仿真的文本对照最大差仅 {summary['storage_control']['max_absolute_difference']:.3g}。</p>
<p>物理参数与验收门槛始终不变。最终快 RLC 使用 reltol=1e-8、abstol=1e-14 A、vntol=1e-9 V、chgtol=1e-18 C、trtol=1、Gear maxord=2。结果须同时通过独立波形、阈值、守恒与加密检查；不把数值阻尼当作真实通道损耗，也不将多项数值设置变化归因于某一个参数。</p></div>
<div class="panel"><h2>波形与物理账本</h2>{image('chiplet-channel-waveforms.png')}
<p>每个节点均核对 ΔQ=∫I dt；每个记录时刻核对源供能＝电场储能变化＋磁场储能变化＋源电阻发热＋线电阻发热。电流探针不储能、不耗能；允许能量返回电源，保留结束时刻的残余储能。</p>
<ul>{controls}</ul><p class="small">这些反例检验错误能否被发现；被动电路的守恒性质仍是模型自洽的必要条件，不能代替真实硬件验证。</p></div>
<div class="panel"><h2>逐案例结果（RLC − RC，单位 ps）</h2><div class="scroll"><table><thead><tr><th>长度</th><th>驱动 / 源 slew</th><th>上升延迟</th><th>下降延迟</th><th>上升偏斜</th><th>下降偏斜</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small">偏斜＝数据通道延迟−同参数 3 mm 时钟通道延迟。仅在其他时序项及事件配对固定时，setup 贡献变化＝−偏斜变化，hold 贡献变化＝＋偏斜变化。不能据此判定真实寄存器 setup/hold。</p></div>
<div class="panel"><h2>假设与下一步</h2><p>10 μm 线宽、1 μm 厚度、距理想连续回流平面 1 μm，εr=3.9、ρ=1.68e-8 Ωm。接收端使用声明的 1.117215037 pF 常量；源为 3.3 V 的线性边沿和 25/100 Ω 戴维南电阻。两模型唯一差异是是否保留外部电感。</p>
<p>回流电阻、内部电感、趋肤/邻近效应、介质损耗、边缘场、bump、耦合与非线性 IO 尚未建模。接下来应取得与目标接口匹配的通道参数及接收判据，再预先设定允许的时序误差，检验简化模型是否改变可行性判断。继续保持原始 Pad 表征和热边界校准缺口可见。</p></div>
<p class="small">工程位置：<code>{html.escape(str(repo))}</code><br>最终记录：<code>results/passive-channel/matrix-balanced</code>，完整波形以无损 gzip 保存（该记录集约 {summary['waveform_archive_bytes']/1e6:.1f} MB）。较早各轮保留在相邻目录。<br>分析起点 dd4aac8；启动及里程碑前已 fetch，远端 c124aa9 未变化。工具已本地提交 dc0c5bf。全部运行在本机，未推送。<br>
<a href="chiplet-passive-channel.json">完整汇总与证据哈希</a> · <a href="{summary['review_url']}">ChatGPT 研究审核</a>（方案/结论审阅，不是独立复现）</p>
</main></html>'''
(out / 'chiplet-passive-channel.html').write_text(body, encoding='utf-8')
print(out / 'chiplet-passive-channel.html')
