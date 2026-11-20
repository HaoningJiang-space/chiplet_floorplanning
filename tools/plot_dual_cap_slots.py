"""Show the feasible destinations of each die in the certified 64-slot instance."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    case = json.loads(args.evidence.read_bytes())['cases']['slots_8x8_folded_torus']
    domain = case['all_permutations']
    assert domain['complete']
    perms = np.array([r['slot_of_die'] for r in domain['witnesses']])
    power = np.array(domain['representatives'][0]['power_w'])
    groups = sorted(set(tuple(np.unique(perms[:, i])) for i in range(64)))
    assert all(len(g) == 4 and np.ptp(power[list(g)]) == 0 for g in groups)
    fig, (ax, right) = plt.subplots(1, 2, figsize=(9.2, 4.8), gridspec_kw={'width_ratios':[1.05,1]})
    colours = ['#b6dbea', '#e99568']
    for i, q in enumerate(power):
        y, x = divmod(i, 8)
        ax.add_patch(Rectangle((x, y), 1, 1, facecolor=colours[int(q == power.max())],
                               edgecolor='white', lw=1))
    for group in groups:
        y, x = np.divmod(group, 8)
        ax.add_patch(Rectangle((x.min(), y.min()), 2, 2, fill=False, edgecolor='#263b46', lw=1.8))
    ax.set(xlim=(0,8), ylim=(0,8), aspect='equal', xlabel='Column', ylabel='Row')
    ax.set_xticks(np.arange(8)+.5, labels=np.arange(1,9))
    ax.set_yticks(np.arange(8)+.5, labels=np.arange(1,9))
    ax.set_title('16 groups of four reachable slots', loc='left', fontsize=12, pad=12)
    ax.text(0,-.22,'Blue  1.025 W     Orange  3.075 W',transform=ax.transAxes,fontsize=10)
    example = np.array(groups[0])
    local = {v:k for k, v in enumerate(example)}
    for i, perm in enumerate(perms):
        signature = [local[v] for v in perm[example]]
        assert all([group.index(v) for v in perm[list(group)]] == signature for group in groups)
        x0, y0 = (i%4)*2.65, (1-i//4)*3.15
        for k, origin in enumerate(example):
            y, x = divmod(local[perm[origin]],2)
            right.add_patch(Rectangle((x0+x,y0+y),1,1,facecolor='#e5eef1',edgecolor='white'))
            right.text(x0+x+.5,y0+y+.5,'ABCD'[k],ha='center',va='center',fontsize=12,color='#243e49')
        moved = np.count_nonzero(perm != np.arange(64))
        right.text(x0+1,y0-.35,f'{moved} dies moved',ha='center',fontsize=8)
    right.set(xlim=(-.2,10.1),ylim=(-.8,5.4),aspect='equal')
    right.set_title('Same permutation in every group',loc='left',fontsize=12,pad=12)
    right.axis('off')
    fig.suptitle('64-die folded torus at the original link limits',x=.08,ha='left',fontsize=15)
    fig.subplots_adjust(left=.08,right=.98,bottom=.19,top=.82,wspace=.24)
    fig.savefig(args.output,dpi=180,bbox_inches='tight',facecolor='white')
    plt.close(fig)


if __name__ == '__main__':
    main()
