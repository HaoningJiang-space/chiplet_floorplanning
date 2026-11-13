"""Plot saved Case1 joint evaluations and their actual constrained winners."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    data = json.loads(args.evidence.read_text())
    source = json.loads(args.input.read_text())
    chips = {c['name']: c for c in source['chiplets']}
    colors = ('#2366a8', '#d66b13')
    labels = ('A: legal mutation', 'B: pin-guided mutation')
    fig, axes = plt.subplots(1, 3, figsize=(15.4, 5.2), gridspec_kw={'width_ratios': [1.25, 1, 1]})
    ax = axes[0]
    initial = data['records'][0]['rows'][:16]
    ax.scatter([r['pin_length_m'] for r in initial], [r['peak_c'] for r in initial],
               color='#8c8c8c', s=20, label='16 shared initial layouts', zorder=2)
    for record, color, label in zip(data['records'], colors, labels):
        rows = record['rows'][16:]
        ax.scatter([r['pin_length_m'] for r in rows], [r['peak_c'] for r in rows],
                   s=24, color=color, alpha=.7, label=label, zorder=3)
        for axis, marker in (('temperature_at_length', '*'), ('length_at_temperature', 'D')):
            r = record['physical_comparison'][axis]['selected']
            ax.scatter(r['pin_length_m'], r['peak_c'], marker=marker, s=160 if marker == '*' else 65,
                       facecolors='none', edgecolors=color, linewidths=1.8, zorder=5)
    plan = data['plan']
    ax.axvline(plan['length_cap_m'], color='#555555', linestyle='--', linewidth=1)
    ax.axhline(plan['temperature_cap_c'], color='#555555', linestyle=':', linewidth=1)
    ax.set(xlabel='Total source-pin Manhattan length (m)', ylabel='Peak power-layer temperature (C)',
           title='Actual joint evaluations\nStar: min T under L0; diamond: min L under T0')
    ax.grid(alpha=.15)
    ax.legend(fontsize=8, loc='upper right')
    for ax, record, color, label in zip(axes[1:], data['records'], colors, labels):
        row = record['physical_comparison']['temperature_at_length']['selected']
        for pose in row['placement']:
            c = chips[pose['chiplet']]
            w, h = c['width_um']/1000, c['height_um']/1000
            if pose['rotation_deg'] % 180:
                w, h = h, w
            x, y = pose['centre_x_um']/1000, pose['centre_y_um']/1000
            fill = '#ffc991' if pose['chiplet'].startswith('GPU') else '#a9cde8' if pose['chiplet'].startswith('CPU') else '#c9dfc2'
            ax.add_patch(Rectangle((x-w/2, y-h/2), w, h, facecolor=fill, edgecolor='#333333', linewidth=1))
            ax.text(x, y, f"{pose['chiplet']}\n{c['power_w_decimal']} W\n{pose['rotation_deg']} deg", ha='center', va='center', fontsize=8)
        ax.set(xlim=(0, 42), ylim=(0, 42), aspect='equal', xlabel='x (mm)', ylabel='y (mm)',
               title=f"{label}: min T under L0\n{row['peak_c']:.3f} C; {row['pin_length_m']:.3f} m; row {row['row_index']}")
        ax.set_xticks((0, 10, 20, 30, 42))
        ax.set_yticks((0, 10, 20, 30, 42))
    fig.suptitle('Case1 | one paired seed | 48 fresh thermal queries per method | L0 = 73.840 m; T0 = 107.450 C', fontsize=12)
    fig.text(.5, .025, 'Declared steady uniform-die FV/HiTS model. Pin distance is a geometric objective; no routed RC or timing claim.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .06, 1, .94))
    for suffix in ('.png', '.pdf'):
        fig.savefig(args.output.with_suffix(suffix), dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    main()
