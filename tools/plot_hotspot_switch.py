"""Plot one observed hotspot handoff using only saved coordinates and checks."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def plot(geometry, online, name, output):
    row = online['cases'][name]
    arm = row['arms']['single']
    xy = np.array(geometry['inputs']['centres_um'])/1000
    watts = np.array(geometry['cases'][name]['power_w'])
    trace = arm['trace']
    panels = [('Start', arm['candidates'][0], arm['start_hot_die'], None)]
    for number, (step, point) in enumerate(zip(trace,arm['candidates'][1:]),1):
        panels.append((f'Check {number}',point,step['hot_slot'],step['previous_hot_slot']))
    fig, axes = plt.subplots(1,len(panels),figsize=(3.15*len(panels)+.7,3.2),layout='constrained',
                             sharex=True,sharey=True,squeeze=False)
    for ax, (title,point,hot,old) in zip(axes[0],panels):
        assigned = geometry['maps'][point['map_id']]['slots']
        scatter = ax.scatter(*xy[assigned].T,c=watts,vmin=watts.min(),vmax=watts.max(),cmap='YlOrRd',
                             marker='s',s=225,linewidths=.6,edgecolors='#4f4944')
        if old is not None and old>=0 and old!=hot:
            ax.scatter(*xy[old],marker='o',s=380,facecolors='none',edgecolors='#246d8c',linewidths=1.7)
        if hot>=0:
            ax.scatter(*xy[hot],marker='x',c='#19282f',s=72,linewidths=1.9)
        ax.set(title=f"{title} · #{point['map_id']}\n{point['peak_c']:.4f} °C",aspect='equal',xlabel='x (mm)')
        ax.margins(.18)
        ax.spines[['top','right']].set_visible(False)
    axes[0,0].set_ylabel('y (mm)')
    fig.colorbar(scatter,ax=axes.ravel().tolist(),label='Die power (W)',shrink=.72)
    fig.savefig(output,dpi=175)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('geometry','online','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--case',required=True)
    args=parser.parse_args()
    plot(json.loads(args.geometry.read_bytes()),json.loads(args.online.read_bytes()),args.case,args.output)
