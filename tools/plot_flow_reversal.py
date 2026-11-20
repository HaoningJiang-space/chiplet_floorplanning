"""Plot frozen die footprints and the computed peak under each flow direction."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.geometry import boxes


def render(source, evidence, output):
    def read(path):
        return json.loads(path.read_bytes())

    layouts = read(evidence / 'flow-reversal-layouts.json')['cases']
    results = read(evidence / 'flow-reversal-results.json')['cases']
    geom = read(evidence / 'flow-reversal-precheck.json')['geometry']
    plate_mm = 1000 * np.array([geom['length_m'], geom['count'] * geom['pitch_m']])
    problems = {name: Problem.from_imported(read(source / f'{name}.json')) for name in layouts}
    density = {name: p.power_w / np.prod(p.size_um / 1000, axis=1) for name, p in problems.items()}
    norm = Normalize(0, max(values.max() for values in density.values()))
    cmap = plt.get_cmap('YlOrRd')
    markers = [('forward', 'o', '#114775'), ('reverse', 'x', '#161616')]
    fig, axes = plt.subplots(2, 2, figsize=(7.5, 7.8), layout='constrained')
    for row, name in enumerate(('Case9', 'Case3')):
        p = problems[name]
        carrier_mm = np.asarray(p.carrier_um) / 1000
        origin = (plate_mm - carrier_mm) / 2
        for ax, label in zip(axes[row], ('A', 'B')):
            rec = layouts[name]['poses'][label]
            pose = Layout(np.array(rec['centre_um']), np.array(rec['rotation_deg']))
            for rect, power_density in zip(boxes(p, pose) / 1000, density[name]):
                x0, y0, x1, y1 = rect
                ax.add_patch(Rectangle(origin + [x0, y0], x1 - x0, y1 - y0,
                                       facecolor=cmap(norm(power_density)), edgecolor='#655850', lw=.55))
            ax.add_patch(Rectangle(origin, *carrier_mm, fill=False, edgecolor='#7a7773', lw=.8))
            for direction, marker, color in markers:
                peak = results[name]['layouts'][label]['96']['directions'][direction]
                ax.plot(peak['x_mm'], peak['y_mm'], marker=marker, color=color, ms=9,
                        mew=2, fillstyle='none', linestyle='none')
            ax.set(xlim=(0, plate_mm[0]), ylim=(0, plate_mm[1]), aspect='equal',
                   xticks=[0, 20, 40, 60], yticks=[0, 20, 40, 60])
            ax.tick_params(labelsize=8, length=2)
            if row == 1:
                ax.set_xlabel('x (mm)')
            if label == 'A':
                ax.set_ylabel('y (mm)')
            note = '  (25 mm reach)' if name == 'Case3' else ''
            ax.set_title(f'{name}  /  layout {label}{note}', fontsize=10, loc='left')
    scale = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(scale, ax=axes, location='right', shrink=.65, label='Die power density (W/mm²)')
    handles = [Line2D([], [], marker=m, color=c, ls='none', ms=8, mew=2, fillstyle='none')
               for _, m, c in markers]
    fig.legend(handles, ['Peak with flow →', 'Peak with flow ←'], loc='outside lower center',
               ncol=2, frameon=False)
    fig.savefig(output, dpi=160, bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, default=Path(__file__).resolve().parents[1] / 'docs/evidence')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(args.source, args.evidence, args.output)
