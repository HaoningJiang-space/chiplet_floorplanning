"""Render the frozen TTC observation experiment without altering its metrics."""

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

from calibrate_measured_transient import case_data
from validation.ttc_observation import simulate, PARAMETERS


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--report', type=Path, default=Path('results/physical-calibration/ttc-observation-v2/report.json'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--milestone-commit', action='append', default=[])
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = json.loads(args.report.read_text())
    admission = json.loads((args.root/'thermal-fit-v2/report.json').read_text())
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    colors = ['#64748b', '#2878a8', '#a87528', '#b43e46']
    labels = ['Old parameters / begin', 'Old parameters / end',
              'Old parameters / average', 'Refitted / end']
    figures = []
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), constrained_layout=True)
    for j, (group, g) in enumerate(data['groups'].items()):
        versions = [g['fixed'][op] for op in ('begin', 'end', 'average')]+[g['end_refit']]
        for k, v in enumerate(versions):
            m = v['metrics']['held_out_all']['native']
            for ax, key in zip(axes, ['equal_run_mae_k', 'equal_run_rmse_k', 'max_abs_error_k']):
                ax.bar(j+(k-1.5)*.18, m[key], width=.17, color=colors[k], label=labels[k] if j == 0 else None)
    for ax, title in zip(axes, ['Equal-run MAE', 'Equal-run RMSE', 'Maximum absolute error']):
        ax.set(xticks=[0, 1], xticklabels=['Natural convection', 'Fan'], ylabel='Temperature error (K)', title=title)
        ax.grid(axis='y', alpha=.15)
    axes[0].legend(fontsize=7)
    fig.suptitle('All nine held-out patterns per group | native 0.1 s grid | no residual smoothing')
    path = args.output/'chiplet-ttc-observation-errors.png'; fig.savefig(path, dpi=170); plt.close(fig); figures.append(path)

    fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), constrained_layout=True)
    for row, (group, g) in enumerate(data['groups'].items()):
        worst = max((c for c in g['end_refit']['cases'] if c['role']=='held_out'), key=lambda c:c['native']['max_abs_error_k'])
        rec = next(c for c in admission['groups'][group]['cases'] if c['name']==worst['name'])
        case = case_data(args.root, group, rec)
        oldp = np.log([g['fixed_parameters'][key] for key in PARAMETERS])
        newp = np.log([g['end_refit']['fit']['parameters'][key] for key in PARAMETERS])
        time = np.arange(len(case['power_w']))*.1
        event = worst['worst']['nominal_row_time_s']
        selected = np.abs(time-event) <= 1.01
        sensor = worst['worst']['sensor_index']
        ax, spatial = axes[row]
        ax.plot(time[selected]-event, case['temperature_rise_k'][selected, sensor]+case['ambient_c'],
                'ko-', ms=3, lw=1.5, label='Measured native samples')
        for params, op, label, color in [(oldp,'begin',labels[0],colors[0]), (oldp,'end',labels[1],colors[1]),
                                        (oldp,'average',labels[2],colors[2]), (newp,'end',labels[3],colors[3])]:
            theta, _ = simulate(params, case['power_w'], case['initial_cells_k'], op)
            ax.plot(time[selected]-event, theta[selected, sensor]+case['ambient_c'], '--', color=color, label=label)
        ax.set(title=f'{group}: {case["name"]}, sensor {sensor}', xlabel='Row time relative to worst residual (s)', ylabel='Temperature (C)')
        ax.grid(alpha=.15)
        entries = g['end_refit']['cases']
        x = np.arange(len(entries))
        spatial.bar(x, [c['native']['rmse_k'] for c in entries], color=[colors[row+1] if c['role']=='held_out' else '#aab2bb' for c in entries])
        spatial.set(xticks=x, xticklabels=[c['name'] for c in entries], ylabel='Native RMSE (K)', title='End refit: every case (gray = calibration)')
        spatial.tick_params(axis='x', labelrotation=45)
        spatial.grid(axis='y', alpha=.15)
    axes[0, 0].legend(fontsize=7)
    fig.suptitle('Residual peaks persist; row coordinates do not establish hardware timestamps')
    path = args.output/'chiplet-ttc-observation-events.png'; fig.savefig(path, dpi=170); plt.close(fig); figures.append(path)

    geo = data['geometry']
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.3), constrained_layout=True)
    ax = axes[0]
    for h in geo['heaters']:
        ax.add_patch(Rectangle((h['x_um']/1000, h['y_um']/1000), h['width_um']/1000,
                               h['height_um']/1000, facecolor='#eea55b', edgecolor='white'))
    sensors = np.array(geo['sensors_xy_um'])/1000
    ax.scatter(*sensors.T, color='#234f76', s=18, label='Sensor location')
    for index, xy in enumerate(sensors):
        ax.annotate('ABCD'[index//4]+str(index%4+1), xy, xytext=(3, 3), textcoords='offset points', fontsize=8)
    ax.set(xlim=(0, 10.24), ylim=(0, 10.24), aspect='equal', xlabel='x (mm)', ylabel='y (mm)', title='Author geometry: 32 heaters / 16 sensors')
    ax.legend(loc='lower left', fontsize=8)
    cap = geo['capacities']
    values = [cap['silicon_per_cell_j_per_k'], *[g['end_refit']['fit']['parameters']['c_cell_j_per_k'] for g in data['groups'].values()], cap['modeled_pad_j_per_k']/16]
    axes[1].bar(np.arange(4), values, color=['#64748b', colors[1], colors[3], '#bba169'])
    axes[1].set(xticks=np.arange(4), xticklabels=['Si per cell\nfrom source', 'Natural\neffective fit', 'Fan\neffective fit', 'Pad per cell\nsource fitted Cv'], ylabel='Capacity (J/K)', title='Different physical meanings: not interchangeable')
    axes[1].grid(axis='y', alpha=.15)
    path = args.output/'chiplet-ttc-observation-geometry.png'; fig.savefig(path, dpi=170); plt.close(fig); figures.append(path)

    rows = []
    for group, g in data['groups'].items():
        for label, v in zip(labels, [g['fixed'][op] for op in ('begin','end','average')]+[g['end_refit']]):
            m = v['metrics']['held_out_all']['native']
            rows.append(f'<tr><td>{group}</td><td>{label}</td><td>{m["equal_run_mae_k"]:.4f}</td><td>{m["equal_run_rmse_k"]:.4f}</td><td>{m["max_abs_error_k"]:.4f}</td></tr>')
    case_rows=[]
    for group,g in data['groups'].items():
        for c in g['end_refit']['cases']:
            m=c['native']
            case_rows.append(f'<tr><td>{group}</td><td>{c["name"]}</td><td>{c["role"]}</td><td>{m["mae_k"]:.4f}</td><td>{m["rmse_k"]:.4f}</td><td>{m["max_abs_error_k"]:.4f}</td></tr>')
    image_html=''.join('<img alt="TTC observation audit figure" src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()+'">' for p in figures)
    decomposition_rows=[]
    max_interval=0.
    for group,g in data['groups'].items():
        cases=[c for c in g['end_refit']['cases'] if c['role']=='held_out']
        common=np.sqrt(np.mean([c['residual_decomposition']['common_rmse_k']**2 for c in cases]))
        spatial=np.sqrt(np.mean([c['residual_decomposition']['spatial_rmse_k']**2 for c in cases]))
        fraction=common**2/(common**2+spatial**2)
        decomposition_rows.append(f'<tr><td>{group}</td><td>{common:.4f}</td><td>{spatial:.4f}</td><td>{fraction:.1%}</td></tr>')
        max_interval=max(max_interval,max(c['ledger']['max_interval_energy_error_j'] for c in g['end_refit']['cases']))
    body=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>TTC 实测观测审计</title>
<style>body{{max-width:1180px;margin:40px auto;padding:0 22px;font:17px/1.7 system-ui;color:#1c2e42;background:#f7f9fc}}h1,h2{{line-height:1.3}}table{{border-collapse:collapse;width:100%;font-size:14px;background:white}}td,th{{padding:8px;border-bottom:1px solid #dce3eb;text-align:left}}img{{width:100%;margin:24px 0}}.note{{background:#fff3d9;padding:18px;border-left:4px solid #b58124}}a{{color:#1766a1}}code{{font-size:14px}}</style>
<h1>TTC：读数定义改变尖峰，尚未解决物理偏差</h1>
<p>26 组公开实测功率/温度记录，8 组校准、18 组既定留出；留出数据在前轮已经看过，因此不称盲测。本地运行，无推送。代码提交：{html.escape(', '.join(args.milestone_commit))}。</p>
<p class="note">physical_model_qualified = false。本轮验证作者软件的区间结束比较约定，未恢复硬件记录器时间戳、采样平均或传感器延迟。生产热模型和真实 Pad/封装资格状态保持未校准。</p>
<h2>先看固定参数对照</h2><p>仅把读数从区间开始改为区间结束，留出最大误差由自然对流 26.96 K、风冷 28.00 K 降到 15.38 K、15.85 K。平均误差基本不变。随后仅用原训练案例按来源选定的区间结束约定重拟合，最大误差仍为 18.13 K、13.29 K；自然对流最大误差甚至比固定参数的结束读数更高。没有根据留出结果选择算子或最佳参数。</p>
<table><tr><th>条件</th><th>算子与参数</th><th>MAE / K</th><th>RMSE / K</th><th>最大绝对误差 / K</th></tr>{''.join(rows)}</table>
<p>上表为原始 0.1 s 网格，MAE 为逐 run MAE 等权平均，RMSE 为逐 run MSE 等权后开方。详细 JSON 另保留 1 s 网格、剔除首个条件化秒、24-run 来源功率范围子集；主结果保留全部案例与全部尖峰。两个 sixteen 属于训练案例，次级范围统计并不等于在范围内重新训练。</p>
{image_html}
<h2>第一性原理解释及边界</h2>
<p>热网络满足 C·dθ/dt + G·θ = P。三种读数共用同一连续动力学：区间开始 θₙ、区间结束 θₙ₊₁、区间内温度积分除以 Δt。精确指数传播、积分与全部 N 个功率区间的储热/散热账本，避免把时间离散误差伪装成热容。</p>
<p>重拟合 Ccell：自然 0.01635 J/K，风冷 0.01011 J/K；风冷已离开旧的 0.0001 J/K 下界。但最快模态约 29.6 / 16.7 ms，小于 100 ms 记录间隔。拟合快热容仍与空间简化、记录时序混淆，不能称为唯一材料识别。实际测点在两块加热器之间，相同区域热源平均温度与点式传感温度不能直接等同。</p>
<p>逐时刻将16个残差分成共同均值与去均值的空间部分，均方误差严格相加。下表显示约89%–91%的均方误差位于共同分量。它可能关联环境温度、边界、初始状态、校准偏置等，不能直接解释为某一种原因。仅细化空间模型未必改善整体误差。</p>
<table><tr><th>条件</th><th>共同分量 RMSE / K</th><th>空间差异 RMSE / K</th><th>共同分量占 MSE</th></tr>{''.join(decomposition_rows)}</table>
<p>全26个重拟合预测的逐区间最大能量残差 {max_interval:.3g} J，独立标量解析解和增广矩阵指数对照通过；125项测试通过，基础双芯粒案例运行成功。这些属于数值验证。</p>
<p>作者模型：610+15 μm 硅，总热容 0.10719 J/K；500 μm 硅橡胶接触垫，模型热容 0.52429 J/K；铜底座和鳍片合计 80.38866 J/K。这里的 thermal pad 是导热垫，不是电气 I/O Pad。作者硅导热率 88 W/(m·K)、垫层 14.3/20 W/(m·K) 以及垫层热容包含拟合；不可当作新测得的材料真值。散热器降阶拟合 Cbath 为 82.15/66.70 J/K，同一硬件不同条件所得不同，再次提示模型约化及边界混淆。</p>
<h2>为什么不直接与论文的平均误差比较</h2>
<p>锁定作者 3D-ICE 3.0 的验证代码，确认其下载的是同一个 Zenodo 数据集、以区间结束温度对齐同一行，并排除两组约 48 W 的 sixteen 案例（散热器模型声明 &lt;40 W）。作者比较脚本还用相邻残差替换一部分尖峰，再报告平均绝对误差和最大误差。本轮不采用该平滑操作，也不声称复现了完整 3D-ICE 模拟。可追溯来源与代码实现合同不能替代真实记录器元数据。</p>
<p>来源：<a href="https://github.com/esl-epfl/3d-ice/tree/1ce8c0ad00b96acae52fc83508c61e3b4ad612df">固定版本 3D-ICE 3.0</a> · <a href="https://zenodo.org/records/3345878">原始 TTC 实测数据</a> · <a href="https://re.public.polimi.it/retrieve/handle/11311/1169759/613752/CR_early_tcad_3d.pdf">作者论文（含 100°C 保护切断说明）</a></p>
<h2>全部案例：区间结束重拟合</h2><table><tr><th>条件</th><th>案例</th><th>角色</th><th>MAE / K</th><th>RMSE / K</th><th>最大误差 / K</th></tr>{''.join(case_rows)}</table>
<h2>下一步证据</h2><p>冻结真实加热器/测点、双硅层和接触垫的空间模型，先检查守恒、解析极限及网格收敛，再用原数据检验空间差温及事件残差。硬件时标缺失保持显式，不通过自由平移曲线获得“校准”。更好的联合优化排名必须大于热/电模型的不确定度；数值测试数目不作为 SOTA 或物理精度的替代指标。</p></html>'''
    body=body.replace('</html>', '<p>已通过用户授权的 codex-chatgpt-skill 完成两轮 <a href="https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865">ChatGPT 方法与结果审核</a>。采纳：不把离开下界当作材料识别、不把24-run统计当作范围内重新训练、补逐区间能量和共同/空间残差分解；下一轮用固定参数空间预测做可否证对照。审核是方法建议，不是物理认证。</p></html>')
    (args.output/'chiplet-ttc-observation-audit.html').write_text(body, encoding='utf-8')
    exported=dict(data, milestone_commits=args.milestone_commit)
    (args.output/'chiplet-ttc-observation-audit.json').write_text(json.dumps(exported,indent=2,allow_nan=False)+'\n')
    print(args.output/'chiplet-ttc-observation-audit.html')


if __name__ == '__main__':
    main()
