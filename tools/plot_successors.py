"""Show the verified sparse-method winner and the actual motion on each carrier."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import numpy as np

from chiplet_floorplanning.placement.geometry import boxes
from successor_protocol import coolest_verified, load_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'results', 'output'):
        parser.add_argument('--'+key, required=True, type=Path)
    parser.add_argument('--distinct-pins',type=Path,help='Use the independently rerun distinct-pad held-out case.')
    args = parser.parse_args()
    cases = json.loads(args.results.read_bytes())['cases']
    if args.distinct_pins:
        cases.pop('Stagger12', None)
        cases.update(json.loads(args.distinct_pins.read_bytes())['cases'])
    figure_width = 12.4 * (len(cases) / 3)
    fig, grid = plt.subplots(1, len(cases), squeeze=False, figsize=(figure_width, 4.7), layout='constrained')
    axes = grid[0]
    teal, red, blue = '#19736b', '#ae332b', '#274876'
    for ax,(name,case) in zip(axes,cases.items()):
        p,start,*_ = load_case(name,args.source)
        arm = case['arms']['three']
        best = coolest_verified(arm['verified'])
        original = start.centre_um/1000
        target = np.asarray(best['centre_um'])/1000
        bounds = boxes(p,start)/1000
        hot = int(np.argmax(best['die_peaks_c']))
        decision = next((d for d in arm['decisions'] if d['selected']==best.get('candidate')),None)
        observers = (decision or arm['decisions'][0])['observers'] if arm['decisions'] else []
        for i,(lo,hi) in enumerate(zip(bounds[:,:2],bounds[:,2:])):
            delta = target[i]-original[i]
            moved = abs(delta).max()>1e-8
            ax.add_patch(Rectangle(lo,*(hi-lo),facecolor='#e4f2ef' if moved else '#f3f4f5',
                                   edgecolor=teal if moved else '#a3aab0',linewidth=1.2 if moved else .65))
            if moved:
                ax.add_patch(Rectangle(lo+delta,*(hi-lo),fill=False,edgecolor=teal,linestyle=':',linewidth=1))
                ax.annotate('',xy=target[i],xytext=original[i],zorder=6,
                            arrowprops=dict(arrowstyle='-|>',color=teal,lw=1.4,shrinkA=0,shrinkB=0))
        if observers:
            ax.scatter(*target[observers].T,s=61,facecolors='none',edgecolors=blue,linewidth=1.4,zorder=7)
        ax.scatter(*target[hot],marker='x',s=36,color=red,linewidths=1.6,zorder=8)
        w,h = np.array(p.carrier_um)/1000
        ax.set(xlim=(0,w),ylim=(0,h),aspect='equal',xlabel='x (mm)')
        ax.set_title(f"{name}   |   {arm['cooling_k']:.3f} K cooler",loc='left',fontsize=12)
    axes[0].set_ylabel('y (mm)')
    handles = [Patch(facecolor='#e4f2ef',edgecolor=teal,label='Moved die at start'),
               Patch(facecolor='none',edgecolor=teal,linestyle=':',label='Verified landing'),
               Line2D([],[],marker='o',markerfacecolor='none',color=blue,ls='none',label='Scored die'),
               Line2D([],[],marker='x',color=red,ls='none',label='Verified hottest die')]
    fig.legend(handles=handles,loc='outside lower center',ncols=min(4, 2*len(cases)),frameon=False)
    fig.savefig(args.output,dpi=165,bbox_inches='tight')


if __name__=='__main__':
    main()
