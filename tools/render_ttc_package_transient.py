"""Render package transient evidence with independent numerical/physical gates."""

import argparse
import base64
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from validation.measured_sources import digest
from validation.sources import write_json


def summarize(root):
    source = root/'report.json'
    report = json.loads(source.read_text())
    summary = dict(source_report_sha256=digest(source), git=report['git'],
                   computation_complete=bool(report.get('complete')), physical_model_qualified=False,
                   models={}, mesh_changes=[])
    for key, model in report['completed'].items():
        cases = model['cases']
        held = [c for c in cases if c['role'] == 'held_out' and c['source_power_domain']]
        # Preserve native duration weighting explicitly; this is not a mean of
        # per-case RMSEs and the reused holdouts are not a blind validation set.
        scores = {}
        for initial in ('conditional_gradient', 'uniform'):
            selected = [c['variants'][initial][-1] for c in held]
            weight = np.array([c['sample_count'] for c in held])
            scores[initial] = {name:float(np.sqrt(np.average([v['scores'][name]**2 for v in selected], weights=weight)))
                               for name in ('common_rmse_k', 'spatial_rmse_k')}
            scores[initial]['raw_rmse_k'] = float(np.sqrt(sum(x*x for x in scores[initial].values())))
            scores[initial]['held_out_cases'] = len(held)
            scores[initial]['samples_per_sensor'] = int(weight.sum())
        sensitivity = []
        for case in cases:
            path = root/key/(case['name']+'.npz')
            if digest(path) != case['waveform_sha256']:
                raise ValueError('waveform changed: '+str(path))
            with np.load(path) as wave:
                sensitivity.append(float(abs(wave['uniform_order_2_c']-wave['conditional_gradient_order_2_c']).max()))
        summary['models'][key] = dict(group=model['group'], model=model['model'], level=model['level'],
            full_nodes=model['geometry']['node_count'],
            fixed_mesh_reduction_screen=model['fixed_mesh_reduction_screen'],
            max_native_trace_order_change_k=model['max_native_trace_order_change_k'],
            numerical_controls=model['numerical_controls'], held_out_duration_weighted_scores=scores,
            max_initial_state_sensitivity_k=max(sensitivity),
            max_normalized_heat_error=max(v[-1]['heat_ledger']['normalized_energy_error'] for c in cases for v in c['variants'].values()),
            cases=[dict(name=c['name'], role=c['role'], source_power_domain=c['source_power_domain'],
                        initial_state_sensitivity_k=sensitivity[i],
                        windows={k:v[-1]['dc_window'] for k,v in c['variants'].items()}) for i,c in enumerate(cases)])
    for key, model in report['completed'].items():
        if model['level'] != 1:
            continue
        coarse = model['group']+'_'+model['model']+'_level0'
        if coarse not in report['completed']:
            continue
        changes = []
        for case in model['cases']:
            with np.load(root/key/(case['name']+'.npz')) as fine, np.load(root/coarse/(case['name']+'.npz')) as old:
                if not np.array_equal(fine['power_w'], old['power_w']) or not np.array_equal(fine['measured_c'], old['measured_c']):
                    raise ValueError('mesh comparison changed observations or power')
                for initial in ('conditional_gradient', 'uniform'):
                    d = fine[initial+'_order_2_c']-old[initial+'_order_2_c']
                    common = d.mean(axis=1, keepdims=True)
                    changes.append(dict(name=case['name'], initial=initial, max_abs_k=float(abs(d).max()),
                                        max_spatial_k=float(abs(d-common).max()), raw_rmse_k=float(np.sqrt(np.mean(d*d)))))
        summary['mesh_changes'].append(dict(group=model['group'], model=model['model'], coarse_level=0, fine_level=1,
            max_native_absolute_change_k=max(c['max_abs_k'] for c in changes),
            max_native_spatial_change_k=max(c['max_spatial_k'] for c in changes), cases=changes,
            interpretation='Observed two-grid change; not an error bound or established spatial convergence.'))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    summary = summarize(args.input)
    if not summary['models']:
        raise ValueError('no completed model')
    args.output.mkdir(parents=True, exist_ok=True)
    labels = {'heatsink':'Natural cooling', 'heatsink_with_fan':'Fan cooling'}
    common_levels = set.intersection(*[set(m['level'] for m in summary['models'].values() if m['group']==g and m['model']==p)
                                      for g in labels for p in ('C', 'P')])
    if not common_levels:
        raise ValueError('wait for a complete paired mesh checkpoint')
    level = max(common_levels)
    summary['plotted_paired_level'] = level
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), constrained_layout=True)
    fig2, axes2 = plt.subplots(2, 2, figsize=(14, 8), constrained_layout=True)
    rows = []
    for col, group in enumerate(labels):
        for row, model in enumerate(('C', 'P')):
            item = summary['models'][group+'_'+model+'_level'+str(level)]
            cases = item['cases']; windows = [c['windows']['conditional_gradient'] for c in cases]
            x = np.arange(len(cases)); names = [c['name']+('*' if c['role']=='calibration' else '') for c in cases]
            ax = axes[row, col]
            stored = np.array([w['storage_rate_w'] for w in windows])
            removed = np.array([w['boundary_heat_loss_w'] for w in windows])
            ax.bar(x, removed, color='#277e96', label='Heat removed to air')
            ax.bar(x, stored, bottom=removed, color='#bd8151', label='Heat stored in all bodies')
            ax.plot(x, [w['power_w'] for w in windows], 'k_', ms=11, label='Input power')
            ax.set(xticks=x, xticklabels=names, ylabel='Window-average power (W)', title=labels[group]+' / '+model)
            ax.tick_params(axis='x', labelrotation=55); ax.grid(axis='y', alpha=.15)
            ax.legend(fontsize=8)
            ax = axes2[row, col]
            ax.bar(x-.18, [w['static_spatial_rmse_k'] for w in windows], .36, color='#99a3ab', label='Static raw FV')
            ax.bar(x+.18, [w['dynamic_spatial_rmse_k'] for w in windows], .36, color='#277e96', label='Transient raw FV')
            ax.set(xticks=x, xticklabels=names, ylabel='Sensor-difference RMSE (K)', title=labels[group]+' / '+model)
            ax.tick_params(axis='x', labelrotation=55); ax.grid(axis='y', alpha=.15); ax.legend(fontsize=8)
    for key, item in summary['models'].items():
        score = item['held_out_duration_weighted_scores']['conditional_gradient']
        numerical = item['numerical_controls']['orders']['2']
        rows.append(f"<tr><td>{html.escape(key)}</td><td>{item['full_nodes']:,}</td>"
            f"<td>{'通过' if item['fixed_mesh_reduction_screen'] else '未通过'}</td>"
            f"<td>{max(numerical['withheld_frequency_max_error_k']):.6g}</td>"
            f"<td>{item['max_native_trace_order_change_k']:.6g}</td>"
            f"<td>{score['common_rmse_k']:.4f}</td><td>{score['spatial_rmse_k']:.4f}</td></tr>")
    fig.suptitle(f'Package heat balance | paired mesh level {level} | conditional initial state\n'
                 '* prior calibration; sixteen ~47 W exceeds the source <40 W domain. Model predictions, not measured body heat.', fontsize=12)
    fig2.suptitle(f'Raw transient vs raw static spatial prediction | paired mesh level {level}\n'
                  'Same 9 s measured windows. No steady continuum correction applied. Physical calibration remains open.', fontsize=12)
    pictures = []
    for figure, stem in ((fig, 'storage'), (fig2, 'spatial')):
        path = args.output/('chiplet-ttc-transient-'+stem+'.png')
        figure.savefig(path, dpi=170); plt.close(figure); pictures.append(path)
    write_json(args.output/'chiplet-ttc-package-transient.json', summary)
    images = ''.join('<img src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()+'">' for p in pictures)
    mesh_rows = ''.join(f"<tr><td>{r['group']} / {r['model']}</td><td>{r['max_native_absolute_change_k']:.4f}</td><td>{r['max_native_spatial_change_k']:.4f}</td></tr>" for r in summary['mesh_changes'])
    page = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>封装瞬态与储热证据</title>
<style>body{{max-width:1200px;margin:36px auto;padding:0 20px;font:16px/1.65 system-ui;color:#253440;background:#fafbfc}}h1{{font-size:29px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:8px;border-bottom:1px solid #dce1e5;text-align:left}}img{{width:100%;margin-top:25px}}.note{{background:#fff1d8;padding:16px;border-radius:7px}}code{{overflow-wrap:anywhere}}</style>
<h1>封装瞬态与储热：计算证据</h1>
<p class="note">已完成 {len(summary['models'])}/8 个模型与网格组合；全计划计算{'已完成' if summary['computation_complete'] else '仍在进行'}。数值降阶、空间网格和实物校准是三个独立门槛，真实热模型目前未获准。</p>
<p>第一性原理：输入功率 = 各实体储热速率 + 向环境散热。显式计算硅、接触垫、铜底座和 23 片鳍片；使用原始材料、热边界及 26 个实测记录，不重新拟合参数。C 为芯片范围的接触垫，P 为 27 mm 接触垫。</p>
<p>下表误差单位均为 K。原生波形的中阶到高阶变化检验降阶精度；实测误差采用每组 9 个既有留出案例按记录时长加权。它们是重复使用的案例，不是新的盲测。所列实测误差采用条件梯度初态；JSON 同时保留均匀初态结果。</p>
<table><tr><th>模型</th><th>完整节点</th><th>降阶检查</th><th>频域误差</th><th>阶数变化</th><th>实测共模 RMSE</th><th>实测差模 RMSE</th></tr>{''.join(rows)}</table>
{images}
<h2>网格改变带来的差异</h2><p>以下为两级网格的实际变化，不是误差上界；两级结果接近也不足以单独确立空间收敛。</p>
<table><tr><th>模型</th><th>原生温度最大变化 / K</th><th>差模最大变化 / K</th></tr>{mesh_rows or '<tr><td colspan="3">等待同一模型的第二级结果</td></tr>'}</table>
<h2>仍需解决</h2><p>源材料包含作者拟合值；真实初始铜温、记录器相位与平均方式、空气升温、辐射和接触条件尚缺独立证据。有限数值控制通过不能替代真实 Pad、封装或 chiplet 热边界校准，也不构成温度时序耦合或 SOTA 结论。</p>
<p>全部实验在本地。输入报告 SHA-256：<code>{summary['source_report_sha256']}</code>。</p></html>'''
    (args.output/'chiplet-ttc-package-transient.html').write_text(page, encoding='utf-8')
    print('rendered', len(summary['models']), 'models; paired level', level)


if __name__ == '__main__':
    main()
