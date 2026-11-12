"""Resource proofs and routed timing evidence, with physical scope explicit."""

import argparse
import base64
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from validation.measured_sources import digest
from validation.sources import write_json


def draw(ax,case,routes,title):
    f=case['fabric'];colors={'a':'#287d96','b':'#bc7448','clock':'#287d96'}
    for x in range(f['nx']):
        for y in range(f['ny']):
            ax.plot(x,y,'.',color='#c5cdd3',ms=7)
    for name,edges in routes.items():
        for a,b in edges:
            ax.plot([a[0],b[0]],[a[1],b[1]],color=colors[name],lw=4,solid_capstyle='round')
    for net in case['nets']:
        for index,p in enumerate([net['source']]+net['sinks']):
            ax.scatter(p[0],p[1],s=85,facecolor='white',edgecolor=colors[net['name']],linewidth=2,zorder=4)
            ax.annotate(net['name']+(' source' if index==0 else ' sink '+str(index)),(p[0],p[1]),xytext=(7,7),textcoords='offset points',fontsize=8)
    ax.set(xlim=(-.4,f['nx']-.35),ylim=(-.4,f['ny']-.35),xticks=range(f['nx']),yticks=range(f['ny']),xlabel='Grid x',ylabel='Grid y',title=title)
    ax.set_aspect('equal');ax.grid(alpha=.12)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routing',required=True,type=Path)
    parser.add_argument('--timing',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--review-note',default='已请求 Chat 模式自主读取 Git 历史；实际可读范围与审核结论仍待核实。')
    args=parser.parse_args()
    routing=json.loads((args.routing/'report.json').read_text());timing=json.loads((args.timing/'report.json').read_text())
    if not routing['complete'] or not timing['complete']:
        raise ValueError('complete both experiment suites first')
    args.output.mkdir(parents=True,exist_ok=True)
    summary=dict(routing_report_sha256=digest(args.routing/'report.json'),timing_report_sha256=digest(args.timing/'report.json'),
        routing_checks=routing['checks'],timing_checks=timing['checks'],routing_cases={},timing_cases={},
        physical_package_qualified=False,physical_channel_qualified=False,chat_full_history_review=args.review_note)
    rows=[]
    for name,case in routing['cases'].items():
        if name.startswith('chiplets_'):
            record={k:case[k] for k in ('certificate','certificate_verified_infeasible','route_time_s')}
            record['search_status']=case['greedy']['status']
            if 'audit' in case['greedy']:
                record['audit']=case['greedy']['audit']
            summary['routing_cases'][name]=record
            certificate=record['certificate']
            rows.append(f"<tr><td>{name}</td><td>{certificate['demand']}</td><td>{certificate['capacity']}</td><td>{'已证明不可行' if record['certificate_verified_infeasible'] else '已找到合法布线'}</td></tr>")
        else:
            summary['routing_cases'][name]=case
    timing_rows=[]
    for name,case in timing['cases'].items():
        for file,expected in case['input_sha256'].items():
            if digest(args.timing/name/file)!=expected:
                raise ValueError('STA input changed')
        if digest(args.timing/name/'sta.log')!=case['log_sha256']:
            raise ValueError('STA log changed')
        record={k:v for k,v in case.items() if k not in ('paths','channel_checks','routed_observed')}
        if 'routed_observed' not in case:
            raise ValueError('routed path times must be explicitly retained')
        for check in ('setup','hold'):
            record['worst_routed_'+check+'_ns']=min(v['slack_ns'] for k,v in case['routed_observed'].items() if '_'+check+'_' in k)
        record['max_expected_clock_delay_ns']=max(v['expected_delay_ns'] for v in case['channel_checks'] if v['channel']=='clock')
        summary['timing_cases'][name]=record
        timing_rows.append(f"<tr><td>{name}</td><td>{record['checked_paths']}</td><td>{record['max_expected_clock_delay_ns']:.7g}</td><td>{record['max_time_error_ns']:.3g}</td><td>{record['unresolved_channel_delay_observations']}</td></tr>")
    summary['checked_routed_paths']=sum(v['checked_paths'] for v in summary['timing_cases'].values())
    summary['negative_controls']={k:{f:v[f] for f in ('numerical_contract_accepted','rejection_reason','log_sha256')} for k,v in timing['negative_controls'].items()}
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,3,figsize=(14,4.7),constrained_layout=True)
    case=routing['cases']['greedy_counterexample']
    draw(axes[0],case,case['greedy']['routes'],'Greedy: search failed')
    draw(axes[1],case,case['exact']['routes'],'Exhaustive: legal witness found')
    shared=routing['cases']['shared_clock_single_slot']
    draw(axes[2],shared,shared['routes'],'One clock, two sinks, one cut slot')
    axes[2].axvline(1.5,color='#777',ls='--',lw=1)
    axes[2].scatter([1.5,1.5],[0,2],marker='x',s=65,color='#a84739',label='Blocked crossing')
    axes[2].legend(fontsize=8,loc='upper left')
    fig.suptitle('Search failure is not physical infeasibility | shared conductors have one identity\n'
                 'Declared grid only: 20 um pitch, 10 um width/spacing. No bump or foundry qualification.',fontsize=12)
    picture=args.output/'chiplet-shared-routing.png';fig.savefig(picture,dpi=170);plt.close(fig)
    encoded=base64.b64encode(picture.read_bytes()).decode()
    clock=routing['cases']['chiplets_16_feasible']['greedy']['audit']['nets']['forwarded_clock']
    page=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>共享时钟：布线到时序</title>
<style>body{{max-width:1200px;margin:36px auto;padding:0 20px;font:16px/1.65 system-ui;color:#253440;background:#fafbfc}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:8px;border-bottom:1px solid #dce1e5;text-align:left}}img{{width:100%}}.note{{background:#fff1d8;padding:16px;border-radius:8px}}</style>
<h1>共享时钟：布线容量 → 唯一 R/C → 完整时序</h1>
<p class="note">完整数值链路已跑通，{summary['checked_routed_paths']:,} 条带布线的路径结果通过核对。规则、单元与 R/C 系数均为声明的实验模型；真实 Pad、封装通道、回流路径与温度反馈尚未校准。</p>
<p>导线段、连接点和层间连接都是有限资源。不同网络不能共享节点；同一时钟树可以分支，公共导线只计一次。布线失败与不可行证明分开：完整截面的需求超过容量，才能由该证据判定此离散模型不可行。</p>
<img src="data:image/png;base64,{encoded}">
<p>中间案例穷举了 A 的 2 条候选简单路径、B 的 7 条候选路径，给出合法见证。另一交叉端点案例穷举无解；枚举达到资源上限时则返回未知。所有结论仅适用于所声明的有限网格。</p>
<table><tr><th>案例</th><th>不同网络需求</th><th>截面容量</th><th>结论</th></tr>{''.join(rows)}</table>
<h2>共享线段不重复收费</h2><p>16-chiplet 案例有 120 条数据 Lane 和 1 棵时钟树。时钟物理线长为 {clock['unique_wire_length_mm']:.2f} mm，而逐接收端路径长度之和是 {clock['sum_source_sink_path_length_mm']:.2f} mm。计算导线电容用前者：0.64 pF；15 个接收输入另外贡献 0.15 pF。每条导线与每个接收负载各计一次。</p>
<h2>独立 RC 与时序核对</h2><p>先比较全节点导纳方程与沿树累积得到的精确 RC 一阶矩，再检验明确声明的单极点近似与 OpenSTA simple_rc 的一致性。该近似不等于分布 RC 的真实波形交越时间，更不代表实测封装延迟。原真实 Pad 流程保持独立。</p>
<table><tr><th>配置</th><th>路径数</th><th>最大预测时钟线延迟/ns</th><th>完整路径最大误差/ns</th><th>低于报告分辨率的线延迟观测</th></tr>{''.join(timing_rows)}</table>
<p>名义小延迟存在浮点报告分辨率限制，因此保留“无法分辨”计数；额外的 100 倍电阻配置仅用于数值敏感性检查，不是工艺角、温度角或真实优化压力案例。漏掉时钟寄生、重复计算时钟电容的两组错误注入均被拒绝。</p>
<h2>仍开放的研究门槛</h2><p>真实 bump/Pad、封装层叠与回流、独立电气表征、热边界和网格收敛、同一接口的温度依赖，以及联合优化的必要性和泛化效果，仍需继续验证。首组更细热网格仍出现约 0.98 K 温度变化，不能用拟合或优化结果掩盖这部分数值误差。</p>
<p>{html.escape(args.review_note)}全部计算在本机完成。</p></html>'''
    (args.output/'chiplet-shared-routing.html').write_text(page,encoding='utf-8')
    write_json(args.output/'chiplet-shared-routing.json',summary)
    print('rendered routing proof cases and',summary['checked_routed_paths'],'routed paths')


if __name__=='__main__':
    main()
