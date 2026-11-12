"""Combine the frozen benchmark and separate proof witnesses into reviewable evidence."""

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

from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.decision import summarize_decisions
from chiplet_floorplanning.floorplanning import write_json
from chiplet_floorplanning.model import parse_case
from benchmark_floorplanning import compact
from validation.decision_evidence import (verify_coverage, verify_inputs, verify_artifact_links,
    verify_timing_identity, verify_saved_sta_files)


def read(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('witness', type=Path)
    parser.add_argument('--thermal-audit', type=Path, required=True)
    parser.add_argument('--channel-audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    benchmark = read(args.benchmark/'report.json'); witness = read(args.witness/'report.json')
    thermal = read(args.thermal_audit); channel = read(args.channel_audit)
    frozen = read(args.benchmark/'frozen-inputs.json')
    verify_artifact_links(digest(args.benchmark/'frozen-inputs.json'), benchmark, witness, thermal, channel,
                          [digest(args.benchmark/'report.json'), digest(args.witness/'report.json')])
    verify_coverage(benchmark['cases'], frozen)
    if set(benchmark['profiles'])!=set(frozen['profiles']):
        raise ValueError('operating profile coverage differs from frozen domain')
    expected_channels = {item['id']+'_'+mode for record in (benchmark, witness)
                         for item in record['cases']+record['paired_refinement'] if item['status']=='analyzed'
                         for mode in ('reference', 'feedback')}
    if set(channel['cases'])!=expected_channels:
        raise ValueError('channel audit coverage is incomplete')
    rows = []; case_reports = {}; timing_reports = {}
    for root, record in ((args.benchmark, benchmark), (args.witness, witness)):
        for item in record['cases']+record['paired_refinement']:
            folder = root/item['id']; row = read(folder/'report.json')
            row.update({k: item[k] for k in ('id', 'layout_id', 'profile', 'policy')})
            verify_inputs(row, read(folder/'inputs.json'), frozen, refinement_factor=item.get('factor', 1))
            if compact(row)!={k: v for k, v in item.items() if k!='factor'}:
                raise ValueError('aggregate candidate differs from original evaluator receipt')
            if item['id'] in case_reports:
                raise ValueError('duplicate evaluator receipt ID')
            case_reports[item['id']] = digest(folder/'report.json')
            for mode, value in row.get('timing', {}).items():
                if 'executable_sha256' not in value:
                    if value['status']=='analyzed':
                        raise ValueError('analyzed timing is missing its runtime identity')
                    continue
                timing_path = folder/mode/'report.json'; receipt = read(timing_path)
                verify_timing_identity(receipt, frozen)
                verify_saved_sta_files(receipt, timing_path.parent)
                # Bind every field used by the proof to its original STA receipt.
                if any(value.get(k)!=v for k, v in receipt.items() if k not in ('models', 'rc')):
                    raise ValueError('evaluator timing differs from original STA receipt')
                key = item['id']+'_'+mode
                timing_reports[key] = digest(timing_path)
                if row['status']=='analyzed':
                    check = channel['cases'][key]
                    if check['report_sha256']!=timing_reports[key] or check['accepted'] is not True:
                        raise ValueError('channel audit belongs to another STA receipt or failed')
            if item in record['cases']:
                rows.append(row)
    if set(thermal['profiles'])!={'nominal', 'tx_power_125pct', 'cooling_800'}:
        raise ValueError('thermal audit must cover the three declared heat problems')
    for profile_rows in thermal['profiles'].values():
        if set(profile_rows)!={'2', '4'}:
            raise ValueError('thermal audit must cover both declared refinement levels')
        for level_rows in profile_rows.values():
            if len(level_rows)!=len(frozen['layouts']) or {r['layout_id'] for r in level_rows}!=set(frozen['layouts']):
                raise ValueError('thermal refinement lacks complete placement coverage')
    report = dict(schema_version=1, source_sha256={str(p): digest(p) for p in
                  (args.benchmark/'report.json', args.witness/'report.json', args.thermal_audit, args.channel_audit)},
                  frozen_inputs=frozen,
                  frozen_budget_results={}, proof_with_additional_witness={},
                  proof_admission=dict(complete_cartesian_domain=True, exact_saved_inputs_verified=True,
                      timing_runtime_identity_verified=True, saved_STA_files_verified=True,
                      linked_audit_hashes_verified=True,
                      artifact_manifest=dict(case_report_sha256=case_reports, timing_report_sha256=timing_reports),
                      source_sha256={str(p): digest(p) for p in (Path(__file__), Path('tools/benchmark_floorplanning.py'),
                                                           Path('tools/validation/decision_evidence.py'),
                                                           Path('src/chiplet_floorplanning/decision.py'))}),
                  thermal_domain_refinement=thermal, channel_audit_summary={k: v for k, v in channel.items() if k!='cases'},
                  cases=benchmark['cases']+witness['cases'],
                  paired_refinement=benchmark['paired_refinement']+witness['paired_refinement'],
                  checked_paths=benchmark['checked_paths']+sum(r['checked_paths'] for r in witness['cases']+witness['paired_refinement']),
                  physical_interface_qualified=False, physical_optimum_certified=False,
                  scientific_conclusion='conditional_zero_timing_temperature_cost_in_this_finite_core_boundary_model; no demonstrated need for joint optimization',
                  unresolved='actual Pad/channel and SPICE validation; temperature interpolation; package boundary and z-refinement; calibrated uncertainty')
    for condition in benchmark['profiles']:
        original_rows = [r for r in rows if r['profile']==condition and r['policy']!='witness']
        report['frozen_budget_results'][condition] = summarize_decisions(original_rows,
            expected_layout_ids=frozen['layouts'], expected_profile=condition)
        summary = summarize_decisions([r for r in rows if r['profile']==condition],
                                      expected_layout_ids=frozen['layouts'], expected_profile=condition)
        # The extra adaptive witness is proof evidence, not a fair baseline run.
        summary.pop('baselines'); summary.pop('baseline_scope')
        report['proof_with_additional_witness'][condition] = summary
    if not all(s['timing_temperature_cost']['feedback']['exact_penalty_k']==0.
               for s in report['proof_with_additional_witness'].values()):
        raise ValueError('this report narrative requires verified zero-cost witnesses in every condition')
    write_json(args.output/'chiplet-integrated-decision.json', report)
    if args.evidence:
        evidence = {k: v for k, v in report.items() if k!='frozen_inputs'}
        evidence['frozen_inputs_manifest_sha256'] = digest(args.benchmark/'frozen-inputs.json')
        evidence['frozen_source_sha256'] = report['frozen_inputs']['source_sha256']
        evidence['pdk_source_sha256'] = report['frozen_inputs']['pdk_source_sha256']
        evidence['configuration_sha256'] = report['frozen_inputs']['configuration_sha256']
        evidence['placement_domain'] = report['frozen_inputs']['layouts']
        write_json(args.evidence, evidence)

    # Render the actual witness geometry and paths beside the nominal decision
    # data. Unrouted candidates have no fabricated slack coordinate.
    nominal = [r for r in rows if r['profile']=='nominal']
    chosen = next(r for r in witness['cases'] if r['profile']=='nominal')
    folder = args.witness/chosen['id']; placed = parse_case(read(folder/'placed.json'))
    arrays = np.load(folder/'temperature.npz'); routing = read(folder/'routing.json'); fabric = routing['fabric']
    receipt = read(folder/'report.json'); mesh = receipt['thermal']['mesh']
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.1), layout='constrained')
    ax = axes[0]
    heat = ax.pcolormesh(mesh['x_edges_mm'], mesh['y_edges_mm'], arrays['die_c'], cmap='inferno', shading='flat')
    for die in placed.dies:
        b = die.bounds; ax.add_patch(Rectangle((b.x, b.y), b.width, b.height, fill=False, ec='#111827', lw=1.4))
        ax.text(b.x+b.width/2, b.y+b.height/2, f'{die.id}\n{die.rotation} deg', ha='center', va='center', color='white', weight='bold')
    margin = max(fabric['width_um'], fabric['via_landing_um'])/2+fabric['edge_clearance_um']
    for name, edges in routing['result']['routes'].items():
        for a, b in edges:
            x = [(margin+n[0]*fabric['pitch_um'])/1000 for n in (a, b)]
            y = [(margin+n[1]*fabric['pitch_um'])/1000 for n in (a, b)]
            ax.plot(x, y, color='#10b981' if name=='forwarded_clock' else '#2563eb',
                    lw=2 if name=='forwarded_clock' else .65, alpha=.9 if name=='forwarded_clock' else .6,
                    ls='--' if a[2] else '-')
    for pin in receipt['physical_pins']:
        x, y = pin['package_point_mm']
        ax.plot(x, y, 'x' if pin['kind']=='power' else 'o', ms=4,
                color='black' if pin['kind']=='power' else '#10b981' if pin['kind']=='clock' else '#2563eb')
    ax.set(xlim=(0, 10), ylim=(0, 8), xlabel='Package x (mm)', ylabel='Package y (mm)',
           title='Thermal-minimum feasible witness | 3 dies, 8 lanes')
    ax.set_aspect('equal'); fig.colorbar(heat, ax=ax, label='Die-layer cell-centre temperature (C)', shrink=.8)
    ax = axes[1]
    for row in nominal:
        if row['status']!='analyzed':
            continue
        x = row['thermal']['peak_c']; a = row['timing']['reference']['worst_setup_ns']; b = row['timing']['feedback']['worst_setup_ns']
        ax.plot([x, x], [a, b], color='#94a3b8', lw=1)
        ax.scatter(x, a, facecolors='none', edgecolors='#2563eb', s=25)
        ax.scatter(x, b, color='#10b981' if row['policy']=='witness' else '#2563eb', s=30)
    ax.set(xlabel='Peak temperature (C)', ylabel='Worst setup slack (ns)', title='Nominal model: all found routes satisfy timing')
    ax.grid(alpha=.2)
    ax.text(0., -.19, 'Hollow: 25 C reference; solid: temperature feedback\nGreen: extra route witness at the thermal lower bound\nUnknown routes are omitted from the slack axis', transform=ax.transAxes, fontsize=9, va='top')
    fig.suptitle('Conditional core-boundary benchmark — assumed package, no qualified Pad model', fontsize=13)
    png = args.output/'chiplet-integrated-decision.png'; fig.savefig(png, dpi=170, bbox_inches='tight', pad_inches=.15); plt.close(fig)

    labels = {'nominal':'基准：3 W，h=1000', 'tx_power_125pct':'TX 功耗 ×1.25',
              'cooling_800':'冷却 h=800', 'package_load_25ff':'每个接收端额外 25 fF'}
    table = ''
    for condition, summary in report['proof_with_additional_witness'].items():
        stage = summary['stages']['timing_feedback']; cost = summary['timing_temperature_cost']['feedback']
        row = next(r for r in rows if r['id']==stage['best_witness'])
        table += f'<tr><td>{labels[condition]}</td><td>{stage["feasible_upper_bound_c"]:.6f}</td><td>{row["timing"]["feedback"]["worst_setup_ns"]:.6f}</td><td>{row["timing"]["feedback"]["worst_hold_ns"]:.6f}</td><td>{cost["exact_penalty_k"]}</td></tr>'
    image = base64.b64encode(png.read_bytes()).decode()
    text = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Chiplet 统一布局决策基准</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;color:#172033;background:#f6f8fc;max-width:1150px;margin:35px auto;padding:0 25px}}h1{{font-size:30px}}.card{{background:white;padding:24px;border:1px solid #dce3ee;border-radius:12px;margin:20px 0}}.scope{{border-left:5px solid #d97706}}table{{width:100%;border-collapse:collapse}}td,th{{padding:11px;text-align:left;border-bottom:1px solid #dde3ec}}img{{width:100%}}small{{color:#566276}}</style>
<h1>从评估器到布局决策：第一个完整基准</h1>
<div class="card"><b>在这组声明模型和有限设计域内，时序温度代价为 0。</b><p>3 个芯粒、8 条数据 Lane、1 棵共享转发时钟树。12 个预定义位置／旋转组合 × 2 个布线顺序 × 4 组条件，共 96 个固定预算组合。另有 4 个布线见证用于闭合最优性证明，{report['checked_paths']:,} 条完整时序路径检查（含网格加密）。这些布局不覆盖任意连续位置或全部独立旋转组合。</p></div>
<div class="card scope"><b>结论范围：机制实验，尚非真实芯片预测。</b><p>单元来自同工艺、同电压的 SKY130 核心库；封装几何、功耗、边界与额外负载是假设。真实 Pad、独立 SPICE 波形校验、温度插值误差和实物封装校准仍未闭合。数值残差不是物理误差界。</p></div>
<div class="card"><img src="data:image/png;base64,{image}" alt="实际引脚、共享路由和布局时序对照"></div>
<div class="card"><table><thead><tr><th>声明条件</th><th>粗网格最低峰温 °C</th><th>反馈 setup ns</th><th>反馈 hold ns</th><th>ΔT K</th></tr></thead><tbody>{table}</tbody></table><small>h 的单位为 W/(m²·K)。每项均用同一配置比较热最优和时序可行最优；额外负载不改变固定功率热模型。</small></div>
<div class="card"><b>为什么可以证明这里的 0？</b><p>先枚举全部 12 个布局的温度，得到热下界；再找到位于下界的合法布线并检查全部 Lane。可行解上界与热下界相等，因而在该离散布局域、声明布线资源和数值模型内达到最优。无需把其他路由搜索失败当作不可行。</p><p>最初两种布线顺序漏掉了热最优布局。额外搜索第 2 次尝试找到合法线路，消除了基准条件下约 0.087 K 的搜索缺口。固定预算三种遍历基线结果相同；新增见证不计入它们的公平对比，也没有算法提速或联合优化优势的主张。</p></div>
<div class="card"><b>数值可靠性与下一道物理门槛</b><p>对三个不同热问题的全部布局进行了 2×、4× 平面网格加密，最优布局均保持不变。基准条件下最优与次优温差从约 0.087 K 到 0.091 K；这支持所测试网格上的排序稳定性，尚未覆盖厚度离散、材料、热边界与电气模型误差。</p><p>时序核对包含局部温度、rise/fall 负载、唯一导体 RC、完整公共时钟路径和全部 setup/hold。后续优先判断模型差异是否改变布局可行性与排序，不要求跨模型误差归零。当前没有覆盖完整路径与物理输入的误差界，决策不确定性标为 uncertainty_unquantified；这既不是零误差，也不表示候选布局已经证明等价。结构化结果列出每个候选的 setup／hold 最小裕量及距零边界的距离，作为敏感性指标，不能当作实际误差估计。</p></div>
<p><a href="chiplet-integrated-decision.json">完整结构化证据</a> · <a href="https://github.com/HaoningJiang-space/chiplet_floorplanning">GitHub 仓库</a></p></html>'''
    (args.output/'chiplet-integrated-decision.html').write_text(text, encoding='utf-8')
    print('Saved', args.output/'chiplet-integrated-decision.html')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
