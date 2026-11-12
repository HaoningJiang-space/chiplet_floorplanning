"""Locate observed two-grid changes without fitting or estimating an error bound."""

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from validation.measured_sources import digest
from validation.sources import write_json


def location(values, power, first_raw_index, component):
    row, sensor = np.unravel_index(np.abs(values).argmax(), values.shape)
    return dict(component=component, max_abs_k=float(abs(values[row, sensor])),
                signed_change_k=float(values[row, sensor]), sample_index_zero_based=int(row),
                raw_index_zero_based=int(first_raw_index + row),
                model_interval_end_since_initialization_s=float((row + 1) * .1),
                sensor_index_zero_based=int(sensor) if component != 'common' else None,
                instantaneous_input_w=float(power[row].sum()))


def analyze(root, group, model):
    report_bytes = (root / 'report.json').read_bytes()
    report = json.loads(report_bytes)
    keys = [f'{group}_{model}_level{level}' for level in (0, 1)]
    models = [report['completed'][key] for key in keys]
    if not all(m['fixed_mesh_reduction_screen'] for m in models):
        raise ValueError('both meshes must first pass their frozen reduction screens')
    coarse_cases = {c['name']: c for c in models[0]['cases']}
    if set(coarse_cases) != {c['name'] for c in models[1]['cases']}:
        raise ValueError('mesh case sets differ')
    records, plot_data = [], {}
    for case in models[1]['cases']:
        old = coarse_cases[case['name']]
        for field in ('role', 'source_power_domain', 'first_raw_index', 'sample_count'):
            if old[field] != case[field]:
                raise ValueError('case metadata differs: ' + field)
        paths = [root / key / (case['name'] + '.npz') for key in keys]
        for path, receipt in zip(paths, (old, case)):
            if digest(path) != receipt['waveform_sha256']:
                raise ValueError('saved waveform changed: ' + str(path))
        with np.load(paths[0]) as coarse, np.load(paths[1]) as fine:
            for field in ('power_w', 'measured_c'):
                if not np.array_equal(coarse[field], fine[field]):
                    raise ValueError('input/observation changed: ' + field)
            for initial in ('conditional_gradient', 'uniform'):
                field = initial + '_order_2_c'
                d = fine[field] - coarse[field]
                if d.shape != (case['sample_count'], 16) or not np.isfinite(d).all():
                    raise ValueError('invalid temperature trace')
                common = d.mean(axis=1, keepdims=True)
                spatial = d - common
                raw_mse = float(np.mean(d * d))
                common_mse = float(np.mean(common * common))
                spatial_mse = float(np.mean(spatial * spatial))
                closure = abs(raw_mse - common_mse - spatial_mse)
                if closure > 1e-12 * max(1., raw_mse):
                    raise ValueError('orthogonal decomposition failed')
                extrema = {name: location(value, fine['power_w'], case['first_raw_index'], name)
                           for name, value in (('raw', d), ('common', common), ('spatial', spatial))}
                at = extrema['raw']['sample_index_zero_based']
                sensor = extrema['raw']['sensor_index_zero_based']
                extrema['raw']['common_at_same_sample_k'] = float(common[at, 0])
                extrema['raw']['spatial_at_same_sample_k'] = float(spatial[at, sensor])
                windows = [c['variants'][initial][-1]['dc_window'] for c in (old, case)]
                dynamic_change, static_change = [np.array(windows[1][field]) - np.array(windows[0][field])
                                                for field in ('dynamic_sensor_difference_k', 'static_sensor_difference_k')]
                record = dict(name=case['name'], initial=initial, role=case['role'],
                              source_power_domain=case['source_power_domain'], sample_count=len(d),
                              raw_mse_k2=raw_mse, common_mse_k2=common_mse, spatial_mse_k2=spatial_mse,
                              mse_closure_k2=closure, extrema=extrema,
                              waveform_sha256=[old['waveform_sha256'], case['waveform_sha256']],
                              diagnostic_window_max_dynamic_spatial_change_k=float(abs(dynamic_change).max()),
                              diagnostic_window_max_static_spatial_change_k=float(abs(static_change).max()),
                              diagnostic_window_max_dynamic_minus_static_grid_change_k=float(abs(dynamic_change-static_change).max()))
                records.append(record)
                plot_data[(case['name'], initial)] = (d[:, sensor], common[:, 0], spatial[:, sensor])
    aggregates = {}
    for initial in ('conditional_gradient', 'uniform'):
        for scope in ('all_records', 'eligible_held_out'):
            selected = [r for r in records if r['initial'] == initial and
                        (scope == 'all_records' or (r['role'] == 'held_out' and r['source_power_domain']))]
            if not selected:
                raise ValueError('empty comparison scope')
            weights = [r['sample_count'] for r in selected]
            mse = {name: float(np.average([r[name+'_mse_k2'] for r in selected], weights=weights))
                   for name in ('raw', 'common', 'spatial')}
            worst = max(selected, key=lambda r: r['extrema']['raw']['max_abs_k'])
            aggregates[initial + '/' + scope] = dict(
                cases=len(selected), samples_per_sensor=sum(weights),
                duration_weighted_rmse_k={k: float(np.sqrt(v)) for k, v in mse.items()},
                spatial_fraction_of_grid_change_mse=mse['spatial']/mse['raw'] if mse['raw'] else None,
                worst_case=worst['name'], worst_location=worst['extrema']['raw'])
    summary = dict(source_report_sha256=hashlib.sha256(report_bytes).hexdigest(), group=group, model=model,
                   levels=[0, 1], analysis='retrospective localization, no parameter changes',
                   model_sample_interval_s=.1, physical_model_qualified=False,
                   interpretation='Observed two-grid differences, not an error bound, convergence proof, or physical causal attribution.',
                   records=records, aggregates=aggregates)
    return summary, plot_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--group', default='heatsink', choices=('heatsink', 'heatsink_with_fan'))
    parser.add_argument('--model', default='C', choices=('C', 'P'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    summary, data = analyze(args.input, args.group, args.model)
    args.output.mkdir(parents=True, exist_ok=True)
    stem = 'chiplet-ttc-mesh-' + args.group + '-' + args.model
    initial = 'conditional_gradient'
    records = [r for r in summary['records'] if r['initial'] == initial]
    chosen = summary['aggregates'][initial+'/eligible_held_out']
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), constrained_layout=True)
    x = np.arange(len(records))
    axes[0].bar(x-.17, [r['extrema']['common']['max_abs_k'] for r in records], .34, label='Common component')
    axes[0].bar(x+.17, [r['extrema']['spatial']['max_abs_k'] for r in records], .34, label='Demeaned spatial component')
    axes[0].set(xticks=x, xticklabels=[r['name']+('*' if r['role']=='calibration' else '') for r in records],
                ylabel='Maximum observed grid change (K)', title='All 13 cases; component maxima may occur at different times')
    axes[0].tick_params(axis='x', labelrotation=55)
    wave = data[(chosen['worst_case'], initial)]
    t = (np.arange(len(wave[0])) + 1) * .1
    for value, label in zip(wave, ('Raw change', 'Common component', 'Spatial component')):
        axes[1].plot(t, value, label=label, lw=1.1)
    sensor = chosen['worst_location']['sensor_index_zero_based']
    axes[1].set(xlabel='Model interval end since initialization (s)', ylabel='Fine minus coarse (K)',
                title=f"Largest eligible held-out change: {chosen['worst_case']}, sensor index {sensor}")
    for ax in axes:
        ax.legend(fontsize=8); ax.grid(axis='y', alpha=.15)
    fig.suptitle(f'{args.group} / {args.model}, mesh 0 to 1, conditional-gradient initial state\n'
                 'Retrospective numerical diagnostic; not a physical error bound. * prior calibration.', fontsize=12)
    picture = args.output/(stem+'.png'); fig.savefig(picture, dpi=170); plt.close(fig)
    rows = []
    for name, entry in summary['aggregates'].items():
        rms = entry['duration_weighted_rmse_k']
        rows.append(f"<tr><td>{html.escape(name)}</td><td>{entry['cases']}</td><td>{rms['raw']:.6f}</td>"
                    f"<td>{rms['common']:.6f}</td><td>{rms['spatial']:.6f}</td>"
                    f"<td>{100*entry['spatial_fraction_of_grid_change_mse']:.2f}%</td></tr>")
    encoded = base64.b64encode(picture.read_bytes()).decode()
    page = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>热网格差异定位</title>
<style>body{{max-width:1200px;margin:30px auto;padding:0 20px;font:16px/1.7 system-ui;color:#263743}}img{{width:100%}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:8px;border-bottom:1px solid #ddd}}.note{{background:#fff1d8;padding:16px}}</style>
<h1>热网格差异：整体升温与局部温差</h1><p class="note">同一模型 {args.group}/{args.model} 的两级网格比较；材料、功率、实测记录和边界不变。两级都通过各自的降阶数值检查，但这不证明空间收敛或物理校准。</p>
<p>逐时刻把温度变化分成传感器均值和去均值空间分量，两者的均方和等于原变化的均方。下面的比例是<strong>数值网格变化</strong>的分解，不是实测误差归因。所有时间来自模型的 0.1 s 区间端点约定，记录器硬件相位仍未验证。</p>
<img src="data:image/png;base64,{encoded}"><table><tr><th>初态/案例范围</th><th>案例数</th><th>总 RMSE/K</th><th>共模 RMSE/K</th><th>空间 RMSE/K</th><th>空间均方占比</th></tr>{''.join(rows)}</table>
<p>all_records 包含全部 13 个记录；eligible_held_out 仅包含原来标记为留出且处于源功率域的 9 个记录。结果按原生记录长度加权，包含启动和冷却；既有留出集已被多次使用，不是新盲测。uniform 为均匀初态，conditional_gradient 为既定条件梯度初态。</p>
<p>JSON 保存各工况峰值、原记录行号、传感器序号、波形哈希及固定诊断窗口对照。两网格变化不是误差上界，也不能直接归因于接触热阻或对流；仍需完成更细网格和物理边界验证。</p></html>'''
    (args.output/(stem+'.html')).write_text(page, encoding='utf-8')
    write_json(args.output/(stem+'.json'), summary)
    print(json.dumps(summary['aggregates'], indent=2))


if __name__ == '__main__':
    main()
