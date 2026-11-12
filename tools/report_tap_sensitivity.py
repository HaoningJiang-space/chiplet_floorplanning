"""Publish bounded sensitivity evidence and a two-panel scientific figure."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from build_tap_ihp_endpoints import source_bytes


def compact_thermal(t):
    keys = ('peak_power_layer_c', 'source_power_w', 'numerical_admission_passed',
            'energy_balance_error_w', 'original_relative_residual', 'max_reference_difference_k')
    return {k: t[k] for k in keys}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = source_bytes(args.input)
    data = json.loads(raw)
    if data['status'] != 'complete_bounded_diagnostic':
        raise ValueError('Incomplete diagnostic')
    data['raw_result_sha256'] = hashlib.sha256(raw).hexdigest()
    data['source_hashes'] = {p: hashlib.sha256(source_bytes(p)).hexdigest() for p in (
        'tools/diagnose_tap_sensitivity.py', 'tools/prepare_tap_fv.py',
        'tools/solve_tap_fv_hits.py', 'src/chiplet_floorplanning/package.py')}
    for case in data['cases']:
        for row in case['rows']:
            row['thermal'] = compact_thermal(row['thermal'])
    for row in data['decomposition']:
        row['thermal'] = compact_thermal(row['thermal'])
        for source in row['contributions']:
            source['thermal'] = compact_thermal(source['thermal'])
    args.output.with_suffix('.json').write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), layout='constrained')
    colors = ['#2879b9', '#bd502d', '#368662']
    for case, color in zip(data['cases'], colors):
        axes[0].scatter([r['centre_span_mm'] for r in case['rows']],
                        [r['thermal']['peak_power_layer_c'] for r in case['rows']],
                        label=case['case'], color=color, s=29, alpha=.85)
    axes[0].set(xlabel='Demand-weighted centre span (mm)', ylabel='Peak power-layer temperature (C)',
                title='20 preselected layouts per workload')
    axes[0].legend(frameon=False)
    labels = ['Cold', 'Middle', 'Hot']
    self_rise = [r['self_rise_k'] for r in data['decomposition']]
    other_rise = [r['other_sources_rise_k'] for r in data['decomposition']]
    axes[1].bar(labels, self_rise, label='Hotspot die contribution', color='#2879b9')
    axes[1].bar(labels, other_rise, bottom=self_rise, label='Other source contributions', color='#e8a653')
    axes[1].set(ylabel='Rise at the total-field hotspot (K)', title='Ascend: frozen small-domain references')
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.spines[['top', 'right']].set_visible(False)
    fig.savefig(args.output.with_suffix('.png'), dpi=180)
    fig.savefig(args.output.with_suffix('.pdf'))
    plt.close(fig)
    print(json.dumps([dict(case=c['case'], min=c['min_peak_c'], max=c['max_peak_c'], span=c['sampled_span_k'])
                      for c in data['cases']], indent=2))
    print(json.dumps([dict(class_index=r['class_index'], self=r['self_rise_k'], other=r['other_sources_rise_k'],
                          owner=r['hotspot']['owner'], error=r['field_superposition_error_k'])
                      for r in data['decomposition']], indent=2))


if __name__ == '__main__':
    main()
