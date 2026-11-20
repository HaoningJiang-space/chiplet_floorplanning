"""Plot the actual power relocation in a verified double-cap layout, using saved results."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=Path('docs/evidence'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case = 'folded_torus_8x8_inward'
    geometry = json.loads((args.evidence/'movable-power-geometry.json').read_bytes())['cases'][case]
    result = json.loads((args.evidence/'movable-power-results.json').read_bytes())['cases'][case]
    arm = result['arms']['near_hotspots']
    fig, axes = plt.subplots(1, 2, figsize=(7.7, 3.8), layout='constrained', sharey=True)
    cmap = ListedColormap(['#d0e1ea', '#bd572a'])
    norm = BoundaryNorm([0, 2.05, 4.10], cmap.N)
    power = np.asarray(geometry['power_w'])
    for ax, point, name in zip(axes, (arm['candidates'][0], arm['best']), ('Starting layout', 'Selected joint move')):
        xy = np.asarray(point['centre_um'])/1000
        ax.scatter(*xy.T, c=power, marker='s', s=78, cmap=cmap, norm=norm)
        ax.set(aspect='equal', xlabel='x (mm)', title=f"{name}\nPeak {point['peak_c']:.3f} °C")
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylabel('y (mm)')
    handles = [axes[0].scatter([], [], c=c, marker='s', s=72, label=f'{w:.3f} W')
               for c, w in zip(cmap.colors, (power.min(), power.max()))]
    axes[1].legend(handles=handles, title='Die power', loc='upper left', bbox_to_anchor=(1., 1.),
                   frameon=False)
    fig.savefig(args.output, dpi=165)
    plt.close(fig)


if __name__ == '__main__':
    main()
