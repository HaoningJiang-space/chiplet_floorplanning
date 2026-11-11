"""Render the public-measurement local milestone and preserve its limits."""

import argparse
import base64
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from calibrate_measured_transient import case_data
from validation.measured_pad import read_mdm
from validation.measured_transient import simulate
from validation.sources import write_json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--milestone-commit', action='append', default=[])
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.root
    thermal = json.loads((root / 'thermal-transient-v1/report.json').read_text())
    admission = json.loads((root / 'thermal-fit-v2/report.json').read_text())
    pad = json.loads((root / 'pad-primitive-v1/report.json').read_text())
    audit = json.loads((root / 'transient-audit-v1/report.json').read_text())
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    colors = ['#286b9a', '#cc6b27']
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), constrained_layout=True)
    for ax, (group, data), color in zip(axes, thermal['groups'].items(), colors):
        rows = data['cases']
        x = np.arange(len(rows))
        ax.bar(x, [c['rmse_k'] for c in rows], color=[color if c['role'] == 'held_out' else '#9ca7b3' for c in rows])
        ax.set_xticks(x, [c['name'] for c in rows], rotation=30, ha='right')
        ax.set_ylabel('Temperature RMSE (K)')
        ax.set_title(group + ' | gray = calibration; colored = held out')
        ax.grid(axis='y', alpha=.15)
    fig.suptitle('Measured TTC: conditional transient prediction, not target-package calibration')
    fig.savefig(args.output / 'chiplet-measured-errors.png', dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(12, 7), constrained_layout=True)
    selections = [('one', 'sixteen', 'hotspot_3'), ('one', 'nine', 'hotspot_2')]
    for row, ((group, _), names) in enumerate(zip(thermal['groups'].items(), selections)):
        for ax, name in zip(axes[row], names):
            data = np.load(root / 'thermal-transient-v1' / group / (name + '.npz'))
            time = data['time_s'] / 60
            ax.plot(time, data['measured_c'].max(axis=1), color='#222', lw=1.5, label='Measured max of 16 sensors')
            ax.plot(time, data['predicted_c'].max(axis=1), color=colors[row], lw=1.3, ls='--', label='Model max of 16 nodes')
            ax.set(title=group + '\n' + name, xlabel='Time from selected start (min)', ylabel='Temperature (C)')
            ax.grid(alpha=.15)
    axes[0, 0].legend(fontsize=7)
    fig.suptitle('Actual power histories include shutdown: no constant-power safety claim')
    fig.savefig(args.output / 'chiplet-measured-transients.png', dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for ax, (group, fitted), color in zip(axes, thermal['groups'].items(), colors):
        worst = max((c for c in audit['groups'][group]['cases'] if c['role'] == 'held_out'),
                    key=lambda c: c['native_metrics']['max_abs_error_k'])
        record = next(c for c in admission['groups'][group]['cases'] if c['name'] == worst['name'])
        c = case_data(root, group, record)
        params = np.log([fitted['fit']['parameters'][key] for key in
                         ['g_xy_w_per_k', 'g_z_w_per_k', 'g_a_w_per_k', 'c_cell_j_per_k', 'c_bath_j_per_k']])
        prediction, _ = simulate(params, c['power_w'], c['initial_cells_k'])
        event = worst['worst_residual_location']
        times = np.arange(len(prediction)) * .1 - event['time_from_start_s']
        selected = np.abs(times) <= 1.01
        sensor = event['sensor_index']
        ax.plot(times[selected], c['temperature_rise_k'][selected, sensor] + c['ambient_c'],
                'o-', color='#222', ms=3, label='Measured 0.1 s samples')
        ax.plot(times[selected], prediction[selected, sensor] + c['ambient_c'],
                's--', color=color, ms=3, label='Model with sampled input ZOH')
        ax.set(title=f'{group}: {c["name"]}, sensor {sensor}',
               xlabel='Time relative to worst residual (s)', ylabel='Temperature (C)')
        ax.grid(alpha=.15)
        ax.legend(fontsize=8)
    fig.suptitle('Post-fit event diagnostic: timestamp/averaging convention remains unresolved')
    fig.savefig(args.output / 'chiplet-measured-event-audit.png', dpi=170)
    plt.close(fig)

    pad_summary = []
    for device in ['nfet_g5v0d10v5', 'pfet_g5v0d10v5']:
        for temp in [20, 25, 30]:
            errors, measured = [], []
            for batch in pad['cases']:
                if batch['device'] != device or batch['assumed_temperature_c'] != temp:
                    continue
                for index, curve in enumerate(read_mdm(Path(batch['source']))):
                    a = np.loadtxt(root / 'pad-primitive-v1' / batch['name'] / f'curve-{index:02d}.txt', skiprows=1)
                    y = curve['columns']['ID']
                    on = np.abs(y) >= 1e-5
                    errors.extend((-a[:, 1] - y)[on])
                    measured.extend(y[on])
            err, y = np.array(errors), np.array(measured)
            pad_summary.append(dict(device=device, assumed_temperature_c=temp, on_points=len(err),
                                    on_id_rmse_ua=float(np.sqrt(np.mean(err**2)) * 1e6),
                                    on_id_relative_l2=float(np.linalg.norm(err) / np.linalg.norm(y))))
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    for row, device in enumerate(['nfet_g5v0d10v5', 'pfet_g5v0d10v5']):
        sign = 1 if row == 0 else -1
        for col, sweep in enumerate(['IDVG', 'IDVD']):
            ax = axes[row, col]
            batch = next(b for b in pad['cases'] if b['device'] == device and sweep in b['name'] and b['assumed_temperature_c'] == 25)
            curves = read_mdm(Path(batch['source']))
            index = next(i for i, c in enumerate(curves) if c['fixed']['VB'] == 0 and
                         c['fixed'].get('VD' if sweep == 'IDVG' else 'VG') == sign * (5 if sweep == 'IDVG' else 3))
            c = curves[index]
            x = c['columns'][c['sweep']] * sign
            ax.scatter(x[::4], sign * c['columns']['ID'][::4] * 1e3, color='#222', s=12, label='Measured (temperature unknown)')
            for temp, color in zip([20, 25, 30], ['#80b5ce', '#286b9a', '#cc6b27']):
                name = batch['name'].replace('-25C', f'-{temp}C')
                a = np.loadtxt(root / 'pad-primitive-v1' / name / f'curve-{index:02d}.txt', skiprows=1)
                ax.plot(x, -sign * a[:, 1] * 1e3, color=color, lw=1, label=f'TT assumed {temp} C')
            ax.set(title=device + ' | ' + sweep, xlabel='|Gate voltage| (V)' if col == 0 else '|Drain voltage| (V)', ylabel='|Drain current| (mA)')
            ax.grid(alpha=.15)
    axes[0, 0].legend(fontsize=7)
    fig.suptitle('Measured HV primitives, W=7 um / L=0.5 um: no model fitting')
    fig.savefig(args.output / 'chiplet-measured-pad.png', dpi=170)
    plt.close(fig)

    summary = dict(physical_model_qualified=False, local_milestone_commits=['c5fc0a6', *args.milestone_commit],
                   github_checked_commit='c124aa982eb97f49a7f4be907554c94436ace2d2',
                   thermal_steady_admission={g: dict(status=v['status'], eligible_calibration=v['calibration_names']) for g, v in admission['groups'].items()},
                   thermal_transient=thermal['groups'], post_fit_audit=audit['groups'],
                   pad_on_state_summary=pad_summary,
                   pad_curve_comparisons=pad['curve_comparisons'], pad_all_numerical_screens=pad['all_numerical_screens_passed'],
                   source_doi='10.5281/zenodo.3345878',
                   chat_review_url='https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865')
    write_json(args.output / 'chiplet-measured-calibration.json', summary)
    def embedded(name):
        data = base64.b64encode((args.output / name).read_bytes()).decode()
        return f'<img src="data:image/png;base64,{data}" alt="{html.escape(name)}">'
    rows = ''
    for group, data in thermal['groups'].items():
        for case in data['cases']:
            rows += f'<tr><td>{group}</td><td>{case["name"]}</td><td>{"校准" if case["role"]=="calibration" else "留出"}</td><td>{case["rmse_k"]:.3f}</td><td>{case["max_abs_error_k"]:.3f}</td><td>{case["measured_sensor_peak_c"]:.2f}</td></tr>'
    padrows = ''.join(f'<tr><td>{p["device"]}</td><td>{p["assumed_temperature_c"]}</td><td>{p["on_points"]}</td><td>{p["on_id_rmse_ua"]:.2f}</td><td>{100*p["on_id_relative_l2"]:.2f}%</td></tr>' for p in pad_summary)
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chiplet 公开实测校准研究</title><style>body{{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f3f5f7;color:#203045}}main{{max-width:1100px;margin:auto;padding:36px}}h1{{font-size:30px}}h2{{font-size:22px;margin-top:36px}}.card{{padding:22px;background:white;border-radius:12px;margin:18px 0}}.notice{{border-left:5px solid #cc6b27}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border-bottom:1px solid #dde4eb;padding:8px;text-align:left}}code{{background:#eaf0f4;padding:3px}}a{{color:#216b9a}}.small{{font-size:14px;color:#526575}}</style><main>
<p class="small">2026-11-11 · 本地实验 · 公开实测 · 不向 GitHub 推送</p><h1>先检验守恒，再检验测量能否识别参数</h1>
<div class="card notice"><b>已建立真实测量对照；目标 chiplet 的物理校准仍未通过。</b><p>稳态准入拒绝了样本不足的拟合。随后完成 26 组含储热的实测响应对照（8 组校准、18 组留出）及 108 组高压晶体管曲线对照。风扇组热容触及数值下限，局部温差和采样时间歧义仍明显。</p></div>
<h2>从物理方程判断数据用途</h2><div class="card"><p><code>C dT/dt + G T = P + 边界项</code>：热输入一部分改变储热，一部分流向环境。温度仍上升时，不能把末温代入稳态热阻公式。电气对照从四端口电流与功率守恒开始，保留测量电流的符号。</p>
<p>39 组 TTC 数据中，13 组为 1 kHz 快速瞬态，本轮仅登记；另外 26 组为 10 Hz 长时实验。12 组自然对流和 1 组风扇实验在约 100°C 提前停止高功率输入，符合保护切断特征，但报警字段尚未确认。只有实测功率历史被用于求解。</p>
<p>预声明稳态规则要求至少 3 个校准案例合格；实际自然对流仅 1 个、风扇仅 2 个，均保留 <code>not_fitted</code>。未改阈值、未挑选温度窗口。</p></div>
<h2>瞬态模型：可以预测哪些量，哪些量还不可辨识</h2><div class="card"><p>使用 16 个测点节点加一个公共散热节点；所有热导与热容均为正。每种冷却条件只拟合 5 个等效参数，4 个固定起点，按完整实验划分校准与留出。留出数据此前做过端点审计，属于未参与拟合的预测检验，并非盲测。</p>
<p>自然对流／风扇留出 RMSE 为 <b>1.645 / 2.768 K</b>，最大误差 <b>26.961 / 27.997 K</b>。切换前后 ±1 秒以外仍有 <b>6.766 / 6.594 K</b> 最大误差；这些分区结果不替换原始全区间误差。</p>
<p>积分能量残差最大约 7.43×10⁻¹¹（相对输入能量）；这验证求解守恒，不验证材料参数真实。风扇 C_cell 到达 10⁻⁴ J/K 下限，敏感度条件数约 3.82×10⁵，不能报告为已测得的热容。</p>
<p>将功率时间移动一个 0.1 秒采样间隔，风扇留出预测最大变化可达 32.07 K。这证明事件附近敏感，不能证明原始误差由时间错位造成；远离事件的残差也不能全部归因于结构。需恢复采样平均、时间戳及切断记录的定义。环境每组只有一个读数；恒定环境是假设，无法证明漂移可忽略。初始散热节点也未直接测量。</p></div>
{embedded('chiplet-measured-errors.png')}{embedded('chiplet-measured-transients.png')}{embedded('chiplet-measured-event-audit.png')}
<h2>Pad：实测晶体管对照已完成，完整接口仍有缺口</h2><div class="card"><p>Google/CoolCAD 的实际硅测量覆盖 n/p 高压器件，W=7 µm、L=0.5 µm。保持 TT 模型不变，计算全部 36 条偏置曲线 × 20/25/30°C 三种假设。测量文件未给出温度、lot 与完整探针不确定度，三个温度不是实测置信区间。</p>
<p>108 组数值守恒检查通过，最大四端口 KCL 残差约 1.05×10⁻¹⁶ A。在假定 25°C 且 |I_D|≥10 µA 的导通样本中，n/p 电流相对 L2 误差为 3.21% / 4.68%。低电流区保留带符号噪声，不用接近零的分母制造误差比例。此结果尚不包含真实 GPIO 瞬态、PEX 或封装互连。</p>
<table><tr><th>器件</th><th>假设温度 °C</th><th>导通点数</th><th>RMSE µA</th><th>相对 L2</th></tr>{padrows}</table></div>{embedded('chiplet-measured-pad.png')}
<h2>全部长时案例结果</h2><p class="small">误差针对每秒采样的 16 个传感器对应节点；峰值为测点峰值，不是未经观测的硅片最高温度。温差 K 与 °C 的数值相同。</p><div class="card"><table><tr><th>冷却条件</th><th>案例</th><th>用途</th><th>RMSE K</th><th>最大误差 K</th><th>实测测点峰值 °C</th></tr>{rows}</table></div>
<h2>下一步科学问题与准入条件</h2><div class="card"><p><b>科学问题：</b>在传感器、输入时标和散热边界存在不确定性时，哪些实验激励足以约束影响布局优劣的热耦合响应？应先证明预测或布局排序稳健，再讨论优化器改进。</p><ol>
<li>恢复 TTC 记录器时间戳、平均方式和保护策略，匹配 1 kHz 数据的冷却安装条件，才能辨识快速热容。</li>
<li>取得同一封装的几何、TIM、PCB 和传感器定义。增加散热器或板侧测温，区分并行热路径；单个公共节点不能给出唯一 k/TIM/h。</li>
<li>补足 Pad 的温度与测量夹具信息，再校验完整 GPIO 的动态负载、PEX 和电荷；晶体管直流一致不等于传播延迟正确。</li>
<li>封装电气仍需同一载体、明确参考平面及去嵌入的原始测量；理想 RC/RLC 数值检查不替代这一步。暂不放行真实热时序联合优化。</li></ol></div>
<p class="small">来源：<a href="https://zenodo.org/records/3345878">Terraneo 等，公开 TTC 数据 v2，CC-BY</a>；<a href="https://re.public.polimi.it/handle/11311/1099255">作者论文</a>；<a href="https://github.com/google/skywater-pdk-sky130-raw-data/tree/1f7214f2f81a0629303947a07e1ec00a28ae8a33">SKY130 原始实测数据，固定提交</a>。通过 <a href="https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865">ChatGPT 审核对话</a>监督测量算子、可辨识性和结论边界。审阅意见不是新的实验依据。</p>
</main></html>'''
    (args.output / 'chiplet-measured-calibration.html').write_text(text, encoding='utf-8')
    print(args.output / 'chiplet-measured-calibration.html')


if __name__ == '__main__':
    main()
