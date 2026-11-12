"""Render complete-path evidence; never promote synthetic timing to hardware."""

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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    report=json.loads((args.input/'report.json').read_text())
    if not report.get('complete'):
        raise ValueError('wait for the full positive and negative-control suite')
    args.output.mkdir(parents=True,exist_ok=True)
    summary=dict(git=report['git'], source_sha256=digest(args.input/'report.json'),
        sta_version=report['sta_version'], executable_sha256=report['executable_sha256'],
        numerical_checks_passed=report['numerical_checks_passed'], cases={}, negative_controls={},
        physical_d2d_qualified=False, routing_qualified=False, thermal_feedback_qualified=False)
    rows=[]
    for name,case in report['cases'].items():
        for file,expected in case['input_sha256'].items():
            if digest(args.input/name/file)!=expected:
                raise ValueError('input hash changed')
        if digest(args.input/name/'sta.log')!=case['log_sha256']:
            raise ValueError('STA evidence changed')
        record={k:v for k,v in case.items() if k!='paths'}
        for check in ('setup','hold'):
            record['worst_'+check+'_ns']=min(v['normalized_observed']['slack_ns'] for k,v in case['paths'].items() if '_'+check+'_' in k)
        summary['cases'][name]=record
        rows.append(f"<tr><td>{html.escape(name)}</td><td>{case['model']['receivers']+1}</td><td>{case['model']['receivers']*case['model']['lanes']}</td>"
                    f"<td>{case['checked_paths']}</td><td>{record['worst_setup_ns']:.3f}</td><td>{record['worst_hold_ns']:.3f}</td>"
                    f"<td>{case['max_time_error_ns']:.2g}</td></tr>")
    for name,case in report['negative_controls'].items():
        summary['negative_controls'][name]={k:case[k] for k in ('numerical_contract_accepted','rejection_reason','log_sha256')}
    summary['checked_paths']=sum(c['checked_paths'] for c in summary['cases'].values())
    summary['checked_numeric_time_fields']=sum(c['checked_time_fields'] for c in summary['cases'].values())
    plt.rcParams.update({'font.size':10})
    fig,axes=plt.subplots(1,2,figsize=(12,6.2),constrained_layout=True)
    case=report['cases']['chiplets_16_correlated']
    for ax,check in zip(axes,('setup','hold')):
        values=np.array([[min(case['paths'][f'{r}_{lane}_{check}_{edge}']['normalized_observed']['slack_ns'] for edge in ('rise','fall')) for lane in range(8)] for r in range(15)])
        chart=ax.imshow(values,aspect='auto',cmap='viridis')
        for r in range(15):
            for lane in range(8):
                ax.text(lane,r,f'{values[r,lane]:.2f}',ha='center',va='center',fontsize=7,color='white' if values[r,lane] < (values.min()+values.max())/2 else 'black')
        ax.set(xticks=range(8),yticks=range(15),yticklabels=range(1,16),xlabel='Data lane',ylabel='Receiver chiplet',title=check.capitalize()+' worst-polarity slack (ns)')
        fig.colorbar(chart,ax=ax,shrink=.8)
    fig.suptitle('16 chiplets / 120 data lanes / 480 complete path checks\nSynthetic early/late bounds; correlated common-root delay only. No physical Pad or routed-channel qualification.',fontsize=11)
    picture=args.output/'chiplet-multilane-timing.png'
    fig.savefig(picture,dpi=170);plt.close(fig)
    image=base64.b64encode(picture.read_bytes()).decode()
    negative=''.join(f'<li>{html.escape(k)}：{html.escape(v["rejection_reason"])}</li>' for k,v in summary['negative_controls'].items())
    page=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>共享时钟多 Lane 核对</title>
<style>body{{max-width:1150px;margin:36px auto;padding:0 20px;font:16px/1.65 system-ui;color:#253440;background:#fafbfc}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}img{{width:100%}}.note{{background:#fff1d8;padding:16px;border-radius:8px}}code{{overflow-wrap:anywhere}}</style>
<h1>共享时钟与多 Lane：完整路径核对</h1>
<p class="note">数值语义检查{'通过' if summary['numerical_checks_passed'] else '未通过'}。15 个正常/故障裕量配置，5 个错误注入控制，共 {summary['checked_paths']:,} 个路径结果。真实 Pad、电气通道、布线容量和温度反馈仍未获准。</p>
<p>一个公共时钟根驱动发送端时钟缓冲组和一个转发主干；每个接收 chiplet 的分支与反相器服务 8 条数据 Lane。共享硬件只实例化一次，其负载按真实连接数求和。检查 2、4、8、16 个 chiplet，而不是只查看全网最坏的一条路径。</p>
<p>关键结果：公共根的上升沿与下降沿同时增加 0.5 ns，绝对到达时间改变，但裕量抵消；只增加下降沿 0.5 ns，setup 增加 0.5 ns、hold 减少 0.5 ns。一个数据 Lane 的变化只影响该 Lane，接收时钟分支的变化影响对应的 8 条 Lane。</p>
<p>公共根不确定量被声明为同一个 0–0.2 ns 加性变量，同时作用于两个极性。枚举此变量，与 OpenSTA 去除公共路径悲观量后的结果核对。不能把这个限定假设推广成一般 PVT、周期抖动或随机相关模型。</p>
<img src="data:image/png;base64,{image}">
<table><tr><th>配置</th><th>Chiplets</th><th>数据 Lane</th><th>路径</th><th>最差 setup/ns</th><th>最差 hold/ns</th><th>最大核对误差/ns</th></tr>{''.join(rows)}</table>
<p>setup_failure 和 hold_failure 的负裕量是正确检出的不可满足时序，不是分析器错误。表内检查仍与独立事件时间参考吻合。</p>
<h2>错误注入结果</h2><ul>{negative}</ul>
<h2>适用范围</h2><p>所有单元延迟、输入电容、约束和早晚界限都是明确声明的人工数值。验证覆盖边沿配对、共享实例、扇出、负载与完整路径；尚未将它们接入合法封装布线、独立表征的 Pad/PHY 或温度依赖模型。此结果不支持真实频率、能耗、可布性或 SOTA 声明。</p>
<p>仅本地运行。报告 SHA-256：<code>{summary['source_sha256']}</code>。</p></html>'''
    (args.output/'chiplet-multilane-timing.html').write_text(page,encoding='utf-8')
    write_json(args.output/'chiplet-multilane-timing.json',summary)
    print('rendered',summary['checked_paths'],'paths',summary['checked_numeric_time_fields'],'numeric time fields')


if __name__=='__main__':
    main()
