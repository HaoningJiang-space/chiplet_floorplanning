"""Draw measured, to-scale chip displacements in the two feasible ATPlace cases."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.geometry import boxes


def plot(source, data, target):
    fig,axs=plt.subplots(1,2,figsize=(11,5),layout='constrained')
    for ax,(name,run) in zip(axs,((k,v) for k,v in data.items() if 'verified' in v),strict=True):
        p=Problem.from_imported(json.loads((source/(name+'.json')).read_bytes()))
        start,win=run['verified'][0],run['verified'][run['winner']]
        for row,final in [(start,False),(win,True)]:
            layout=Layout(np.array(row['centre_um']),np.array(row['rotation_deg']))
            for n,(x,y,right,top) in zip(p.names,boxes(p,layout)/1000):
                hot=n in run['hot_dies']
                ax.add_patch(Rectangle((x,y),right-x,top-y,facecolor=('#eeb998' if hot else '#d7e8e9') if final else 'none',
                             edgecolor=('#884019' if hot else '#316267') if final else '#83979b',
                             linewidth=.8,linestyle='-' if final else '--',zorder=2 if final else 3))
        old,new=np.array(start['centre_um'])/1000,np.array(win['centre_um'])/1000
        dif=new-old
        ax.quiver(old[:,0],old[:,1],dif[:,0],dif[:,1],angles='xy',scale_units='xy',scale=1,
                  color='#243238',width=.0034,headwidth=3.8,zorder=4)
        ax.set(xlim=(0,p.carrier_um[0]/1000),ylim=(0,p.carrier_um[1]/1000),aspect='equal',
               xlabel='x (mm)',ylabel='y (mm)')
        ax.set_title(f"{name}    {start['peak_c']:.2f} → {win['peak_c']:.2f} °C")
    fig.legend(handles=[Rectangle((0,0),1,1,fill=False,edgecolor='#83979b',linestyle='--',label='Starting footprint'),
                       Rectangle((0,0),1,1,color='#eeb998',label='Five measured hot dies'),
                       Rectangle((0,0),1,1,color='#d7e8e9',label='Other dies after the move')],
               loc='outside lower center',ncols=3,frameon=False)
    fig.savefig(target,dpi=170)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','directed','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    plot(args.source,json.loads(args.directed.read_bytes()),args.output)
