"""Recompute decision costs and discrete-profile regret from published evidence."""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path

from validation.ranking import summarize
from validation.sources import write_json


def regret(profiles):
    tables = {}
    for name, profile in profiles.items():
        rows = profile['candidates']
        table = {r['id']: r['peak_c'] for r in rows}
        if len(table) != len(rows) or not table or not all(math.isfinite(t) for t in table.values()):
            raise ValueError('invalid thermal candidate table')
        tables[name] = table
    if not tables or len({tuple(sorted(t)) for t in tables.values()}) != 1:
        raise ValueError('regret requires identical candidate IDs across all profiles')
    minima = {name: min(table.values()) for name, table in tables.items()}
    records = []
    for candidate in next(iter(tables.values())):
        costs = {name: table[candidate]-minima[name] for name, table in tables.items()}
        records.append(dict(id=candidate, regret_by_profile_k=costs, maximum_regret_k=max(costs.values())))
    records.sort(key=lambda r: (r['maximum_regret_k'], r['id']))
    return dict(profile_minima_c=minima, candidates=records, minimax_id=records[0]['id'],
                scope='thermal table only; six discrete assumptions and 27 candidates, no continuous uncertainty guarantee or timing qualification')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=Path('docs/evidence'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    paths = {k: args.evidence/name for k, name in (
        ('routing', 'v07-validation.json'), ('thermal', 'v08-e1-validation.json'),
        ('boundary', 'local-ttc-package-boundary-level2.json'))}
    contents = {k: p.read_bytes() for k, p in paths.items()}
    source = {k: json.loads(v) for k, v in contents.items()}
    policies = {name: summarize(rows) for name, rows in source['routing']['policies'].items()}
    for name, current in policies.items():
        old = source['routing']['summaries'][name]
        if current['timing_constraint_thermal_penalty_k'] != old['timing_constraint_thermal_penalty_k']:
            raise ValueError('legacy timing-cost result changed')
    robust = regret(source['thermal']['profiles'])
    boundary = {}
    model = source['boundary']['groups']['heatsink']['models']['P']
    for kind in ('raw', 'corrected'):
        old = model[kind+'_summary']['held_out_all']
        reduction = 1-old['spatial_rmse_k']/old['uniform_continuum_spatial_rmse_k']
        if abs(reduction-old['relative_reduction']) > 1e-12:
            raise ValueError('boundary improvement arithmetic differs')
        boundary[kind] = dict(rmse_k=old['spatial_rmse_k'], reduction_fraction=reduction,
                              at_least_20_percent=reduction >= .2,
                              improved_patterns=old['improved_patterns'], case_count=old['case_count'])
    result = dict(input_sha256={str(paths[k]): hashlib.sha256(v).hexdigest() for k, v in contents.items()},
                  analysis='retrospective recomputation of published evidence; no new physics or simulator runs',
                  physical_model_qualified=False, policies=policies, discrete_thermal_regret=robust,
                  natural_P_level2_improvement=boundary)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output/'chiplet-research-decisions.json', result)
    rows = []
    for name, policy in policies.items():
        item = policy['constraint_stages']; s = item['stages']
        costs = [item[k] for k in ('electrical_admission_penalty_k', 'setup_hold_incremental_penalty_k', 'combined_admission_penalty_k')]
        cells = ''.join('<td>'+('无定义' if value is None else f'{value:.7g}')+'</td>' for value in costs)
        rows.append(f"<tr><td>{name}</td><td>{s['geometry_routing']['candidate_count']}</td><td>{s['electrical']['candidate_count']}</td><td>{s['setup_hold']['candidate_count']}</td>{cells}</tr>")
    regret_rows = ''.join(f"<tr><td>{html.escape(r['id'])}</td><td>{r['maximum_regret_k']:.6f}</td></tr>" for r in robust['candidates'][:5])
    page = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>布局决策证据复核</title>
<style>body{{max-width:1050px;margin:36px auto;padding:0 22px;font:16px/1.7 system-ui;color:#263743}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}.note{{background:#fff1d8;padding:16px}}</style>
<h1>布局决策：电气准入、时序约束与离散假设后悔值</h1><p class="note">复算已有公开记录；没有新仿真、参数拟合或物理校准。本结果不证明温度反馈改变布局，也不证明联合算法优于基线。</p>
<p>G 为已评估的几何及路由合法候选，E 再通过电气检查，T 再通过 setup/hold。分别计算 min(E)−min(G)、min(T)−min(E) 及两者之和，温度单位均为 K。空集合不记作零代价；搜索未找到解不等于证明不可行。</p>
<table><tr><th>策略</th><th>G</th><th>E</th><th>T</th><th>电气代价</th><th>新增时序代价</th><th>合计</th></tr>{''.join(rows)}</table>
<p>此前代码已经在电气合法集合上计算时序代价；本轮统一了文档定义并增加分层统计。R3 仅表示已评估的固定路由均未通过几何检查，不代表整个设计不存在合法路由。</p>
<h2>名次反转与实际决策损失</h2><p>对六组热学假设分别减去该组最低峰温，再取同一布局的最大差值。{robust['minimax_id']} 在这个有限表格中取得最小的最大后悔值。</p>
<table><tr><th>布局</th><th>六组中最大后悔值 / K</th></tr>{regret_rows}</table>
<p>没有赋予这六组参数概率，也没有把两芯粒模型与 TTC 的网格差混作统一误差条。未做温度反馈或电气可行性重评。</p>
<h2>自然冷却 P 的 level 2 改善依赖数值校正</h2><p>原始 FV 的留出空间 RMSE 为 {boundary['raw']['rmse_k']:.6f} K，相对 U 连续体改善 {100*boundary['raw']['reduction_fraction']:.2f}%；校正后为 {boundary['corrected']['rmse_k']:.6f} K，改善 {100*boundary['corrected']['reduction_fraction']:.2f}%。两种记录都仅改善 8/9 个图样。原始结果未过 20% 改善门槛，校正结果越过该门槛；空间收敛仍未通过，因此不能据此接受真实边界模型。</p>
<p>下一步：定位 P−C 的空间离散、核对同一完整 data/clock 接口、建立可穷举的约束代价实验，再进行同预算算法比较。原始失败与零代价结论继续保留。</p></html>'''
    (args.output/'chiplet-research-decisions.html').write_text(page, encoding='utf-8')
    print(json.dumps(dict(policies={k:v['constraint_stages'] for k,v in policies.items()},
                          best_regret=robust['candidates'][:3], natural_P=boundary), indent=2))


if __name__ == '__main__':
    main()
