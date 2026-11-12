"""Render completed checkpoints without implying unfinished grids have passed."""

import argparse
import base64
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--milestone-commit', action='append', default=[])
    args = ap.parse_args()
    report = json.loads((args.input/'report.json').read_text())
    common = set.intersection(*(set(g['levels']) for g in report['groups'].values())) if len(report['groups']) == 2 else set()
    if not common:
        raise ValueError('no completed paired material checkpoint to render')
    last = max(map(int, common))
    args.output.mkdir(parents=True, exist_ok=True)
    colors = {'U':'#7a8a92', 'C':'#277e96', 'P':'#bb7744'}
    labels = {'heatsink':'Natural cooling', 'heatsink_with_fan':'Fan cooling'}
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    geo, boundary = report['geometry'], report['boundary']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), constrained_layout=True)
    die_side = geo['die_side_um']/1000
    base_side = boundary['baseLength']*1000
    dlo = (base_side-die_side)/2
    pad_side = boundary['full_pad_side_m']*1000
    active = geo['active_silicon_um']/1000
    silicon = active+geo['bulk_silicon_um']/1000
    pad = geo['thermal_pad_um']/1000
    base_top = silicon+pad+boundary['baseHeight']*1000
    for ax in axes:
        ax.add_patch(Rectangle((dlo, 0), die_side, active, color='#ae4239', label='Active silicon'))
        ax.add_patch(Rectangle((dlo, active), die_side, silicon-active, color='#277e96', label='Bulk silicon'))
        ax.add_patch(Rectangle(((base_side-pad_side)/2, silicon), pad_side, pad, color='#d7ba60', label='27 mm pad'))
        ax.add_patch(Rectangle((0, silicon+pad), base_side, boundary['baseHeight']*1000, color='#b98053', label='Copper'))
        for center in (np.arange(int(boundary['baseCols']))+.5)*base_side/boundary['baseCols']:
            ax.add_patch(Rectangle((center-boundary['finThickness']*500, base_top),
                                  boundary['finThickness']*1000, boundary['finHeight']*1000, color='#b98053'))
        ax.set(xlabel='x (mm)', ylabel='z (mm)'); ax.grid(alpha=.12)
    axes[0].set(xlim=(-1, base_side+1), ylim=(-.8, base_top+boundary['finHeight']*1000+1),
                title='Full footprint: 23 copper fins along y')
    axes[1].set(xlim=(dlo-2, dlo+die_side+2), ylim=(-.05, 1.7), title='Die / pad interface detail (same physical units)')
    axes[1].legend(fontsize=8, loc='upper right')
    fig.suptitle('Source-defined geometry; fin x positions inferred from equal base strips\n'
                 'Axes show physical dimensions; x and z display scales differ. Materials remain uncalibrated.', fontsize=11)
    geometry_picture = args.output/'chiplet-ttc-package-geometry.png'
    fig.savefig(geometry_picture, dpi=170); plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    rows, times = [], []
    for col, (group, values) in enumerate(report['groups'].items()):
        levels = sorted(map(int, values['levels']))
        for contrast, color in [('C-U', colors['C']), ('P-C', colors['P'])]:
            points = [(level, values['levels'][str(level)]['contrasts'][contrast]) for level in levels if level > 0]
            if points:
                axes[0, col].semilogy([p[0] for p in points], [p[1]['last_spatial_refinement_change_k'] for p in points],
                                      'o-', label=contrast, color=color)
        axes[0, col].axhline(.02, color='#666', ls='--', label='Frozen 0.02 K screen')
        axes[0, col].set(xlabel='Completed refinement level', xticks=range(1, 4),
                          ylabel='Change in spatial boundary effect (K)', title=labels[group])
        axes[0, col].grid(alpha=.15); axes[0, col].legend(fontsize=8)
        current = values['levels'][str(last)]
        case_records = current['models']['U']['corrected']['cases']
        x = np.arange(len(case_records))
        for offset, model in [(-.26, 'U'), (0., 'C'), (.26, 'P')]:
            cases = current['models'][model]['corrected']['cases']
            axes[1, col].bar(x+offset, [c['rmse_k'] for c in cases], .25, color=colors[model], label=model)
            summary = current['models'][model]['corrected']['summary']['held_out_all']
            raw = current['models'][model]['raw']['summary']['held_out_all']
            assembly = current['models'][model]['receipt']['assembly']
            rows.append(f"<tr><td>{labels[group]}</td><td>{model}</td><td>{assembly['node_count']:,}</td>"
                        f"<td>{raw['spatial_rmse_k']:.4f}</td><td>{summary['spatial_rmse_k']:.4f}</td>"
                        f"<td>{summary['improved_patterns'] if model != 'U' else '—'}/9</td></tr>")
        tau = current['models']['P']['receipt']['assembly']['slowest_time_constant_lower_bound_s']
        times.append(dict(group=group, tau_lower_s=tau, cases=case_records))
        axes[1, col].set(xticks=x, xticklabels=[c['name']+('*' if c['role']=='calibration' else '') for c in case_records],
                          ylabel='Sensor-difference RMSE (K)', title='Exploratory corrected DC estimate | level '+str(last))
        axes[1, col].tick_params(axis='x', labelrotation=55); axes[1, col].grid(axis='y', alpha=.15)
        axes[1, col].legend(fontsize=8)
    fig.suptitle('Explicit pad / copper / fin boundary diagnostic | * = prior calibration\n'
                 'U: uniform top; C: cropped pad + copper/fins; P: full pad + copper/fins', fontsize=12)
    picture = args.output/'chiplet-ttc-package-boundary.png'
    fig.savefig(picture, dpi=170); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for ax, item in zip(axes, times):
        records = item['cases']
        ax.bar(range(len(records)), [r['elapsed_since_activation_s'] for r in records], color='#277e96')
        ax.axhline(item['tau_lower_s'], color='#bb7744', ls='--', label=f"Slowest relaxation >= {item['tau_lower_s']:.1f} s")
        ax.set(xticks=range(len(records)), xticklabels=[r['name'] for r in records], ylabel='Time (s)', title=labels[item['group']])
        ax.tick_params(axis='x', labelrotation=55); ax.legend(fontsize=8)
    fig.suptitle('Elapsed time at DC-window start vs a rigorous lower bound on the slowest model time constant\n'
                 'This comparison does not establish the actual initial state or transient equilibrium.', fontsize=11)
    slow_picture = args.output/'chiplet-ttc-package-timescales.png'
    fig.savefig(slow_picture, dpi=170); plt.close(fig)
    image_tag = lambda p: '<img src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode('ascii')+'">'
    status = '四级计算完成' if report['complete'] else f'计算进行中：两组材料均完成至第 {last} 级；计划至第 3 级'
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TTC 非均匀封装热边界</title><style>body{{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f3f6f7;color:#203039;margin:0}}
main{{max-width:1050px;margin:32px auto;background:white;padding:32px;border-radius:12px}}p,li{{line-height:1.75}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}td,th{{text-align:left;border-bottom:1px solid #dde3e7;padding:9px}}
img{{max-width:100%}}.notice{{background:#fff4e4;border-left:4px solid #bb7744;padding:18px}}.muted{{font-size:14px;color:#566873}}</style>
<main><p class="muted">本地研究 · 提交 {html.escape(', '.join(args.milestone_commit) or report['git']['commit'][:7])}</p>
<h1>真实尺寸接触垫、铜底座与鳍片：边界对照</h1><p class="notice">{status}。实测物理校准尚未完成。
误差下降仅属探索性证据，必须结合网格收敛和铜储热过程判断；不能因测试通过就宣布模型正确。</p>
<h2>模型与第一性原理</h2><p>10.24 mm 芯片、0.5 mm 接触垫、60×60×2.8 mm 铜底座，以及23片沿y方向的鳍片。
各材料共用对齐网格，界面热流按两侧半层热阻计算，并以相反符号进入两侧能量方程。鳍片两大侧面对固定空气温度换热；其余声明面绝热。</p>
{image_tag(geometry_picture)}<p>U保留芯片大小的接触垫，上表面等温；C加入铜底座和鳍片；P进一步恢复27×27 mm接触垫。
C−U包含边界条件和铜结构的共同变化，不能称为纯几何效应；P−C单独检验垫片外扩。</p>
{image_tag(picture)}<table><tr><th>组别</th><th>模型</th><th>节点数</th><th>原始FV留出RMSE K</th><th>校正估计留出RMSE K</th><th>较U改善图样</th></tr>{''.join(rows)}</table>
<p class="muted">校正估计 R*=R_U连续体+(R_C/P有限体积−R_U有限体积)，用于分开已知局部离散误差；它不是精确封装解或误差保证。
U与自身的浮点级差异不计作改善。训练/留出标签保持原样。</p>
<h2>关键物理限制：铜仍可能在储热</h2><p>对于被动热网络，常温向量的Rayleigh商给出
τ最慢 ≥ 总热容 / 总边界热导。它证明模型中存在慢过程，不给出实际初态，也不证明时间超过该值就已稳态。</p>
{image_tag(slow_picture)}<p>自然冷却许多测试在主通电几十至几百秒后就结束，不能仅凭9秒窗口内空间温差稳定，断言铜与鳍片已稳定。
实测自然组的传感器均温仍以约0.0025–0.536°C/s变化，空间差温平稳不能等同于整体温度平稳。
时间常数下界本身也不能证明某个模态被显著激发或确定其传感器误差。
后续必须用同一物理网络检查储热、排热和完整瞬态，再讨论实测归因。</p>
<h2>数据与范围</h2><p>固定此前26次测量的窗口、材料与功率，没有重新拟合。约47 W的sixteen属于原校准集，超出来源&lt;40 W边界适用域；
每组9个留出图样都低于40 W。初始设计交流中“域内8个留出”的说法为计数错误，计算始终按实际标签和功率筛选，未改变阈值或分组。</p>
<p>鳍片位置由来源条带中心推定；接触垫和换热系数含作者拟合成分。固定空气场、辐射省略、接触状态和传感器观测仍有物理不确定性。</p>
<p class="muted">来源：<a href="https://github.com/esl-epfl/3d-ice/blob/1ce8c0ad00b96acae52fc83508c61e3b4ad612df/heatsink_plugin/heatsinks/HS483/HS483.mo">HS483几何与换热参数</a>；
<a href="https://github.com/esl-epfl/3d-ice/blob/1ce8c0ad00b96acae52fc83508c61e3b4ad612df/heatsink_plugin/common/HeatsinkBlocks.mo">边界与风扇方程</a>。
公开源文件哈希、冻结代码与每个已完成求解的记录均保存在本地结果目录。</p></main></html>'''
    (args.output/'chiplet-ttc-package-boundary.html').write_text(text, encoding='utf-8')
    (args.output/'chiplet-ttc-package-boundary.json').write_text(json.dumps(dict(report=report,
        rendered_common_level=last, milestone_commits=args.milestone_commit), indent=2, allow_nan=False), encoding='utf-8')
    print(status)


if __name__ == '__main__':
    main()
