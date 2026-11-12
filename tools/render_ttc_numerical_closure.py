"""Export the frozen steady numerical closure, without refitting or rerunning."""

import argparse
import base64
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--milestone-commit', action='append', default=[])
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = json.loads((args.input/'report.json').read_text())
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    rows, summaries, decomposition = [], [], {}
    labels = {'heatsink': 'Natural cooling', 'heatsink_with_fan': 'Fan cooling'}
    for col, (group, data) in enumerate(report['groups'].items()):
        ax = axes[0, col]
        for sequence, label, color in [('coupled', 'Refine xy and z', '#146f82'),
                                        ('lateral_only', 'Refine xy only', '#c78134'),
                                        ('depth_only', 'Refine z only', '#8a5487')]:
            values = [entry['error_to_continuum']['max_absolute_error_k'] for entry in data['sequences'][sequence]]
            ax.semilogy(range(5), values, 'o-', label=label, color=color)
        ax.axhline(.1, color='#555', ls='--', label='Frozen 0.1 K screen')
        ax.set(xticks=range(5), xlabel='Frozen refinement level', ylabel='Max sensor difference (K)', title=labels[group])
        ax.grid(alpha=.15); ax.legend(fontsize=8)
        final = data['sequences']['coupled'][-1]
        per_pattern = final['error_to_continuum']['per_pattern_max_absolute_error_k']
        ax = axes[1, col]
        ax.bar(range(13), list(per_pattern.values()), color='#146f82')
        ax.set(xticks=range(13), xticklabels=list(per_pattern), ylabel='Max sensor difference (K)',
               title='Final grid: 31.25 um / 16-32-32 cells', ylim=(0, .023))
        ax.tick_params(axis='x', labelrotation=55); ax.grid(axis='y', alpha=.15)
        for level, entry in enumerate(data['sequences']['coupled']):
            rows.append(f"<tr><td>{labels[group]}</td><td>{level}</td><td>{entry['configuration']['pitch_um']:g}</td>"
                        f"<td>{entry['error_to_continuum']['max_absolute_error_k']:.6f}</td>"
                        f"<td>{entry.get('last_refinement_max_change_k', 0):.6f}</td></tr>")
        summaries.append(f"{labels[group]}：最大差 {final['error_to_continuum']['max_absolute_error_k']:.6f} K；"
                         f"最后加密变化 {final['last_refinement_max_change_k']:.6f} K。")
        arrays = np.load(args.input/(group+'.npz'))
        decomposition[group] = {}
        for level in (0, 4):
            total = arrays[f'coupled_{level}'] - arrays['continuum']
            depth = arrays[f'coupled_{level}'] - arrays[f'coupled_{level}_continuous_z']
            lateral = arrays[f'coupled_{level}_continuous_z'] - arrays['continuum']
            sensor, pattern = np.unravel_index(np.argmax(abs(total)), total.shape)
            decomposition[group][level] = dict(sensor_index=int(sensor), pattern_index=int(pattern),
                total_signed_k=float(total[sensor, pattern]), depth_signed_k=float(depth[sensor, pattern]),
                lateral_signed_k=float(lateral[sensor, pattern]),
                additive_identity_error_k=float(np.max(abs(total-depth-lateral))))
    fig.suptitle('Same physical stack, all discrete modes retained | 13 nominal power patterns per group\n'
                 'Steady numerical consistency only; no hardware calibration or transient qualification', fontsize=12)
    image_path = args.output/'chiplet-ttc-numerical-closure.png'
    fig.savefig(image_path, dpi=170); plt.close(fig)
    encoded = base64.b64encode(image_path.read_bytes()).decode('ascii')
    commits = ', '.join(args.milestone_commit) or report['git']['commit'][:7]
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chiplet 热模型：稳态数值一致性</title>
<style>body{{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f4f6f7;color:#203039;margin:0}}
main{{max-width:1000px;margin:32px auto;padding:32px;background:white;border-radius:12px}}
h1{{font-size:28px}}h2{{margin-top:32px;font-size:21px}}p,li{{line-height:1.75}}.lead{{padding:20px;background:#eaf4f4;border-left:5px solid #146f82}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}td,th{{text-align:left;border-bottom:1px solid #dbe2e5;padding:9px}}
img{{max-width:100%}}.muted{{color:#5a6870;font-size:14px}}code{{background:#eef2f4;padding:2px 5px}}</style>
<main><p class="muted">本地研究阶段报告 · 实现提交 708fb42 · 阶段提交 {html.escape(commits)}</p>
<h1>约 1.7°C 的稳态数值差异已降至约 0.02°C</h1>
<p class="lead">固定材料、热源、传感器坐标和散热边界，联合加密横向与厚度方向，通过预先设定的稳态数值门槛。
这是同一物理模型两种解法的一致性检验，真实封装与 Pad 的物理校准仍未完成。</p>
<h2>为什么要先做这一步</h2><p>热流必须守恒，但守恒本身不保证温度算得足够准确。
上一轮粗网格和连续体参考相差约 1.7 K；直接调整材料去匹配测量，会把数值误差吸收到材料参数中。
本轮保留全部空间模式，对同一热网络做更高效的稳态求解，再逐步加密网格。</p>
<p>同一原始网格下，新解法与独立三维稀疏求解的最大传感器差小于 9.27×10⁻¹¹ K。
全部 140 项测试通过，两芯粒演示仍为 3 W、参考峰温 34.188607°C，明确标为未校准。</p>
<h2>多案例对照结果</h2><p>13 种固定功率图样 × 两组材料，每组 13 种不同网格配置，共 338 个图样/网格组合。
这些是数值控制实验，没有新增实测数据，也没有用实测温度选择网格。</p>
<p>{'<br>'.join(summaries)}</p><img alt="横向与厚度联合加密，以及13种图样的最终误差" src="data:image/png;base64,{encoded}">
<table><thead><tr><th>冷却材料组</th><th>联合级别</th><th>最大横向网格 μm</th><th>对连续体最大差 K</th><th>相邻加密最大变化 K</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table><p class="muted">第0级没有前一级，变化列记0。数值温差 1 K = 1°C。
参考为固定1024阶连续体谱解，其最后变化为0.001291 K，并非严格误差上界。</p>
<h2>误差从哪里来</h2><p>只加密横向，仍残留约0.73–0.76 K；只加密厚度，仍残留约0.96 K。
两方向都需要加密。通过“离散横向 + 连续厚度”的中间对照，可逐点分解误差；不能把各自最大误差直接相加。
最细配置相当于871万个三维节点，保留108896个横向模式。</p>
<h2>已通过与仍未证明的内容</h2><ul><li>通过：同网格代数一致性、热量守恒、源与观测映射、预定0.1 K参考差及0.05 K加密变化门槛。</li>
<li>裕量：最后加密变化约0.049 K，接近门槛；0.020 K是相对当前参考的差异，不是对真实芯片的误差保证。</li>
<li>未证明：原粗网格瞬态有效、真实材料已校准、铜/空气边界正确、完整Pad/封装电气与温度时序耦合。</li></ul>
<h2>下一步物理对照</h2><p>引入来源可追溯的有限铜底座、鳍片及接触垫边界，固定此前的26次实测空间温差诊断窗口与材料参数。
空间非均匀界面会耦合横向模式，必须验证完整耦合算子，不能直接套用本轮逐模态独立求解。</p>
<p>ChatGPT 已审核实验设计与结果，反馈落实于功率单位、观测点定义、条件数检查、误差分解和适用范围。
审核不替代独立计算。GitHub检查成功，远端仍为c124aa9；没有推送或远端计算。</p></main></html>'''
    (args.output/'chiplet-ttc-numerical-closure.html').write_text(body, encoding='utf-8')
    (args.output/'chiplet-ttc-numerical-closure.json').write_text(json.dumps(
        dict(report=report, signed_decomposition=decomposition, milestone_commits=args.milestone_commit),
        indent=2, allow_nan=False), encoding='utf-8')
    print(image_path)


if __name__ == '__main__':
    main()
