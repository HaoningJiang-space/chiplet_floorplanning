"""Show how the four online choices compare with all temperatures in the frozen pool."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def draw(online, reference, output):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), layout='constrained', sharey=True)
    methods = [('relation_space_slots', 'relation_space', '#535967', 'o'),
               ('blind', 'Blind draw', '#bb7025', 's'), ('single', 'Single hotspot', '#14799c', '^'),
               ('near', 'Near-peak', '#784b99', 'D')]
    for ax, (name, row) in zip(axes, online['cases'].items()):
        ref = reference['cases'][name]
        gains = row['start_c'] - np.asarray(ref['pool_peaks_c'])
        xs = np.sort(gains)
        ax.plot(xs, np.arange(1, len(xs)+1)/len(xs), color='#243b47', lw=1.5)
        for index, (key, label, colour, symbol) in enumerate(methods):
            gain = row['arms'][key]['gain_k']
            ax.axvline(gain, color=colour, lw=1, alpha=.5)
            ax.scatter(gain, -.05-.07*index, s=45, color=colour, marker=symbol, label=label, zorder=5)
        ax.axvline(xs[-1], color='black', lw=1, ls=':', label='Best feasible')
        ax.axhline(0, color='#9e9e9e', lw=.65)
        ax.set(title='Balanced workload' if name=='balanced' else 'Complementary workload',
               xlabel='Peak reduction from start (K)', ylim=(-.32,1.04), yticks=[0,.25,.5,.75,1])
        ax.spines[['right','top']].set_visible(False)
    axes[0].set_ylabel('Fraction of legal power maps')
    axes[1].legend(loc='upper left', frameon=False, fontsize=8)
    fig.savefig(output, dpi=175)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    draw(json.loads(args.online.read_bytes()), json.loads(args.reference.read_bytes()), args.output)
