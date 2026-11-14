"""Plot the saved step-size comparison without running search or heat solves."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def main():
    result = json.loads(Path('docs/evidence/atplace-case1-step-size-v1.json').read_text())
    plan = json.loads(Path('docs/evidence/atplace-case1-step-size-plan-v1.json').read_text())
    source = json.loads(Path('results/physical-calibration/atplace-import-v1/Case1.json').read_text())
    chips = {c['name']: c for c in source['chiplets']}
    initial = plan['warm_rows'][0]
    reference = plan['best_known_reference']['temperature_at_length']['selected']
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    colors = ('#2670ad', '#d96322')
    for arm, color, layout_ax in zip(result['arms'], colors, axes[1]):
        record = arm['record']
        label = f"Fixed {arm['step_um']/1000:g} mm"
        rows = record['rows'][1:]
        axes[0, 0].scatter([r['pin_length_m'] for r in rows], [r['peak_c'] for r in rows],
                           color=color, alpha=.7, s=30, label=label)
        for metric, marker in (('temperature_at_length', '*'), ('length_at_temperature', 'D')):
            row = record['physical_comparison'][metric]['selected']
            axes[0, 0].scatter(row['pin_length_m'], row['peak_c'], marker=marker, s=160,
                               edgecolors=color, facecolors='none', linewidths=1.7, zorder=5)
        checkpoints = record['checkpoints']
        axes[0, 1].step([0]+[c['new_thermal_queries'] for c in checkpoints],
            [initial['peak_c']]+[c['physical_comparison']['temperature_at_length']['selected']['peak_c']
                                 for c in checkpoints], where='post', color=color, label=label)
        row = record['physical_comparison']['temperature_at_length']['selected']
        for pose in row['placement']:
            chip = chips[pose['chiplet']]
            w, h = chip['width_um']/1000, chip['height_um']/1000
            if pose['rotation_deg'] % 180:
                w, h = h, w
            x, y = pose['centre_x_um']/1000, pose['centre_y_um']/1000
            fill = '#ffcf9d' if pose['chiplet'].startswith('GPU') else '#a9cde8' if pose['chiplet'].startswith('CPU') else '#c9dfc2'
            layout_ax.add_patch(Rectangle((x-w/2, y-h/2), w, h, facecolor=fill, edgecolor='#333333'))
            layout_ax.text(x, y, f"{pose['chiplet']}\n{chip['power_w_decimal']} W\n{pose['rotation_deg']} deg",
                            ha='center', va='center', fontsize=8)
        layout_ax.set(xlim=(0, 42), ylim=(0, 42), aspect='equal', xlabel='x (mm)', ylabel='y (mm)',
            title=f"{label}: best temperature, row {row['row_index']}\n{row['peak_c']:.4f} C / {row['pin_length_m']:.4f} m")
    axes[0, 0].scatter(initial['pin_length_m'], initial['peak_c'], color='#444444', marker='s', label='Shared C24 start')
    axes[0, 0].scatter(reference['pin_length_m'], reference['peak_c'], marker='x', color='#777777', label='Known reference (not visited)')
    axes[0, 0].axvline(plan['length_cap_m'], linestyle='--', color='#777777', linewidth=1)
    axes[0, 0].axhline(plan['temperature_cap_c'], linestyle=':', color='#777777', linewidth=1)
    axes[0, 0].set(xlabel='Source-pin Manhattan total (m)', ylabel='Peak temperature (C)',
                   title='Joint evaluated points\nStar: min T under Lcap; diamond: min L under T0')
    axes[0, 1].axhline(reference['peak_c'], linestyle=':', color='#777777', label='Known reference')
    axes[0, 1].set(xlabel='Charged thermal evaluations', ylabel='Best feasible peak temperature (C)',
                   title='Same information and query allowance', xticks=(0, 4, 8, 12, 16))
    for ax in axes[0]:
        ax.grid(alpha=.15)
        ax.legend(fontsize=8)
    fig.suptitle('Case1 | one seed | only the translation step changes | Lcap = 35.014737 m', fontsize=13)
    fig.text(.5, .015, 'Fixed 780 W, steady FV/HiTS. Pin length is a lower bound; no routed timing claim.\n'
             '2 mm: saved trajectory replay; 1 mm: new search. Query charges are separate from new solver calls.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .055, 1, .96))
    fig.savefig('docs/evidence/atplace-case1-step-size-v1.png', dpi=170)
    plt.close(fig)


if __name__ == '__main__':
    main()
