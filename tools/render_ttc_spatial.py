"""Render negative spatial-model evidence and independent continuum checks."""

import argparse
import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path('results/physical-calibration'))
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--milestone-commit',action='append',default=[])
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    spatial=json.loads((args.root/'ttc-spatial-v1/report.json').read_text())
    spectral=json.loads((args.root/'ttc-spectral-v2/report.json').read_text())
    dc=json.loads((args.root/'ttc-spatial-dc-v1/report.json').read_text())
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    pictures=[]
    fig,axes=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
    for row,(group,g) in enumerate(spatial['groups'].items()):
        entries=g['cases'];x=np.arange(len(entries))
        for column,field in enumerate(('spatial_rmse_k','raw')):
            ax=axes[row,column]
            for offset,key,label,color in [(-.18,'baseline','17-node baseline','#46799e'),(.18,'spatial','Source geometry / uniform bath','#c66a42')]:
                values=[c[key][field] if field!='raw' else c[key]['raw']['rmse_k'] for c in entries]
                ax.bar(x+offset,values,.35,label=label,color=color)
            ax.set(xticks=x,xticklabels=[c['name']+('*' if c['role']=='calibration' else '') for c in entries],
                   ylabel='RMSE (K)',title=group+' | '+('Spatial differences' if column==0 else 'All sensor temperatures'))
            ax.tick_params(axis='x',labelrotation=45);ax.grid(axis='y',alpha=.15)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Fixed-parameter hybrid model fails the spatial-improvement screen | * = prior calibration')
    path=args.output/'chiplet-ttc-spatial-errors.png';fig.savefig(path,dpi=170);plt.close(fig);pictures.append(path)

    fig,axes=plt.subplots(1,2,figsize=(11,4.8),constrained_layout=True)
    for group,color in [('heatsink','#46799e'),('heatsink_with_fan','#c66a42')]:
        g=spectral['groups'][group]
        change=g['series_max_change_k']
        axes[0].loglog([int(k) for k in change],list(change.values()),'o-',label=group,color=color)
        keys=['coarse','primary','xy_refined','z_refined']
        axes[1].plot(np.arange(4),[g['fv_error_to_continuum_k'][key] for key in keys],'o-',label=group,color=color)
    axes[0].axhline(.01,color='#666',ls='--',label='0.01 K series-change screen')
    axes[0].set(xlabel='Maximum cosine mode per axis',ylabel='Change from preceding series (K)',title='Independent continuum series convergence')
    axes[1].axhline(.1,color='#666',ls='--',label='0.1 K FV screen')
    axes[1].set(xticks=np.arange(4),xticklabels=['1000 um','500 um\nprimary','250 um\nxy refined','500 um\nz refined'],ylabel='Max sensor difference from continuum (K)',title='13 nominal source patterns; steady numerical controls')
    for ax in axes:ax.legend(fontsize=7);ax.grid(alpha=.15)
    path=args.output/'chiplet-ttc-spatial-convergence.png';fig.savefig(path,dpi=170);plt.close(fig);pictures.append(path)

    fig,axes=plt.subplots(1,2,figsize=(12,4.8),constrained_layout=True)
    for ax,(group,g) in zip(axes,dc['groups'].items()):
        x=np.arange(len(g['cases']))
        for offset,key,label,color in [(-.18,'baseline_error','17-node static','#46799e'),(.18,'continuum_error','Converged continuum','#a04b65')]:
            ax.bar(x+offset,[c[key]['rmse_k'] for c in g['cases']],.35,label=label,color=color)
        ax.set(xticks=x,xticklabels=[c['name'] for c in g['cases']],ylabel='Sensor-difference RMSE (K)',title=group+' | secondary DC window')
        ax.tick_params(axis='x',labelrotation=45);ax.legend(fontsize=8);ax.grid(axis='y',alpha=.15)
    fig.suptitle('Same uniform-bath hypothesis still misses measured spatial differences | no new fit')
    path=args.output/'chiplet-ttc-spatial-dc.png';fig.savefig(path,dpi=170);plt.close(fig);pictures.append(path)

    rows=[];numerical_rows=[];dc_rows=[]
    for group,g in spatial['groups'].items():
        for key in ('baseline','spatial','baseline_uniform','spatial_uniform'):
            v=g['summary'][key]['held_out']
            rows.append(f'<tr><td>{group}</td><td>{key}</td><td>{v["rmse_k"]:.4f}</td><td>{v["common_rmse_k"]:.4f}</td><td>{v["spatial_rmse_k"]:.4f}</td><td>{v["max_error_k"]:.4f}</td></tr>')
        s=spectral['groups'][group]
        numerical_rows.append(f'<tr><td>{group}</td><td>{g["numerics"]["steady_sensor_difference_k"]["xy_refined"]:.4f}</td><td>{g["numerics"]["steady_sensor_difference_k"]["z_refined"]:.4f}</td><td>{s["fv_error_to_continuum_k"]["primary"]:.4f}</td><td>{s["series_max_change_k"]["1024"]:.6f}</td></tr>')
        d=dc['groups'][group]['summary']['held_out']
        dc_rows.append(f'<tr><td>{group}</td><td>{d["baseline_spatial_rmse_k"]:.4f}</td><td>{d["continuum_spatial_rmse_k"]:.4f}</td><td>{d["improved_patterns"]}/9</td></tr>')
    images=''.join('<img alt="TTC spatial diagnostic" src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()+'">' for p in pictures)
    body=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>TTC 空间模型证伪</title>
<style>body{{max-width:1180px;margin:40px auto;padding:0 22px;font:17px/1.7 system-ui;color:#1f3145;background:#f8fafc}}table{{width:100%;border-collapse:collapse;background:white;font-size:14px}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #dbe3eb}}img{{width:100%;margin:22px 0}}.note{{padding:18px;background:#fff1db;border-left:4px solid #bc7c27}}a{{color:#276c99}}</style>
<h1>真实几何没有自动带来更准确的热预测</h1>
<p>本地提交：{', '.join(args.milestone_commit)}。26组公开实测记录，固定所有参数，无新增拟合；135项测试通过，包含独立谱解验证。物理校准状态始终为 false。</p>
<p class="note">本轮保留了负结果：空间温差改善门槛未通过，主网格收敛也未通过。不能据此否定空间传热的作用，也不能把风冷总RMSE下降称为模型已正确。当前真正被拒绝的是这一组具体的“来源材料 + 均匀动态散热节点 + 主网格”模型。</p>
<h2>实验改变了什么</h2><p>内部从16个等效节点替换为真实32块加热器、16个测点，以及15 μm主动硅、610 μm厚硅、500 μm导热垫。主网格3361节点；散热节点仍采用前轮固定的G_a与C_b，是空间均匀、随时间变化的温度。没有模拟铜底座的空间传热或鳍片气流。层序由作者解析代码确认。材料数据含作者拟合，不能当作独立实测真值。</p>
<p>新旧模型都使用首次功率的静态内部梯度，再加共同偏移匹配首帧测点平均值；偏移后全系统并非稳态，这是明确的条件初始状态。另用全体节点同温的初态对照。所有模态均保留，按0.1 s功率区间精确传播；原数据和尖峰不平滑、不删除。</p>
<h2>完整留出结果（每种冷却9个既定案例）</h2><table><tr><th>冷却</th><th>模型/初态</th><th>总RMSE K</th><th>共同分量 K</th><th>空间分量 K</th><th>最大误差 K</th></tr>{''.join(rows)}</table>
<p>预先要求两组空间RMSE各下降至少20%，且各至少7/9案例改善；实际均只有1/9改善。风冷总RMSE下降主要来自共同分量，空间差温反而变差。既定留出数据已经在前轮看过，不是盲测。</p>
{images}
<h2>为什么必须区分数值误差和物理误差</h2><p>FVM在正热容、互易热导、解析极限、独立矩阵组装和逐层能量账本上通过检查。全部实测预测每区间/每层能量误差小于2.2×10⁻⁹ J，但网格变化仍使测点温度改变约0.5 K，超过0.1 K预定门槛。守恒不能代替空间收敛。</p>
<table><tr><th>冷却</th><th>xy细化变化 K</th><th>z细化变化 K</th><th>主网格距连续体 K</th><th>谱解512→1024变化 K</th></tr>{''.join(numerical_rows)}</table>
<p>因此补建独立稳态参考：横向绝热边界用余弦展开，纵向分层传导用解析热导纳；热源保留15 μm厚度的体发热，测点位于该层中面。独立分段边值微分方程校验通过。256阶未达到0.01 K收敛筛查，已保留；扩至1024阶后变化约0.001291 K。这是级数收敛诊断，不是实物误差保证。主网格在13个合成稳态功率图样上偏离连续体约1.67/1.70 K；这些高功率稳态仅用于数学对照，不代表设备可绕过100°C保护持续运行。</p>
<h2>去除均匀散热边界后的独立诊断</h2><p>对同高测点减去16点平均温度，在本轮空间均匀散热边界假设下，共同散热温升严格消去；稳态温差因此不依赖G_a或C_b。用每次主通电结束前10到1秒的9秒窗口，26组均通过预定的功率漂移≤2%、空间温差漂移≤0.1 K筛查。比较连续体预测和实测空间温差，仍未看到改善：</p>
<table><tr><th>冷却</th><th>原模型温差RMSE K</th><th>连续体温差RMSE K</th><th>改善案例</th></tr>{''.join(dc_rows)}</table>
<p>这一窗口分析是在主实验后提出的机制诊断，未用于重新选择主模型或拟合参数。它支持继续检查空间散热边界、接触分布、源材料与传感器假设；尚不能唯一认定铜底座就是误差原因。下一步固定内部几何，加入可追溯的铜底座/鳍片空间网络，与均匀边界做配对对照，同时保留环境及接触不确定性。</p>
<p>本轮继续使用用户授权的 codex-chatgpt-skill 做<a href="https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865">ChatGPT监督审核</a>。其建议用于实验设计审查，不作为数值或物理认证。十项长期目标继续，真实Pad、封装电气、多lane、完整温度时序与SOTA比较仍有未完成项。</p></html>'''
    (args.output/'chiplet-ttc-spatial-audit.html').write_text(body,encoding='utf-8')
    (args.output/'chiplet-ttc-spatial-audit.json').write_text(json.dumps(dict(spatial=spatial,spectral=spectral,dc=dc,milestone_commits=args.milestone_commit),indent=2,allow_nan=False)+'\n')
    print(args.output/'chiplet-ttc-spatial-audit.html')


if __name__=='__main__':main()
