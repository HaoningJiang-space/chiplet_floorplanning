"""Plot the attainable common-FV points and the remaining 3D cooling interval."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("evidence",type=Path)
    args=ap.parse_args()
    root=args.evidence
    ext=json.loads((root/"audited.json").read_bytes())["cases"]
    scale=json.loads((root/"scale.json").read_bytes())["cases"]
    grid=json.loads((root/"grid-start.json").read_bytes())["cases"]
    fig,(left,right)=plt.subplots(1,2,figsize=(11,4.1),layout="constrained")
    colors=("#9a492d","#176a70","#465987")
    names=list(ext)
    for i,(arm,label) in enumerate((("guarded","ATPlace, shared start"),("margin","Joint placement"),
                                     ("native","ATPlace, native start"))):
        rows=[ext[n]["arms"].get(arm,{}) for n in names]
        vals=[r["start_peak_c"]-r["best_peak_c"] if "best_peak_c" in r else np.nan for r in rows]
        x=np.arange(len(names))+(i-1)*.24
        left.bar(x,vals,.22,color=colors[i],label=label)
        for xx,v in zip(x,vals):
            if not np.isfinite(v):
                left.annotate("n/a",(xx,0),xytext=(0,3),textcoords="offset points",ha="center",fontsize=7)
            elif v==0:
                left.plot(xx,0,"_",color=colors[i],markersize=8,clip_on=False)
    left.set(xticks=range(len(names)),xticklabels=names,ylabel="Peak reduction from shared start (K)",
             title="External comparison under a common wire cap")
    left.legend(frameon=False,fontsize=8)
    rows=[r for r in scale.values() if not r["uniform"]]
    n=[r["count"] for r in rows]
    found=[r["gain_k"] for r in rows]
    limit=[r["max_possible_gain_k"] for r in rows]
    right.vlines(n,found,limit,color="#777",lw=2)
    right.scatter(n,limit,marker="_",s=150,color=colors[0],label="Upper bound on cooling")
    right.scatter(n,found,s=35,color=colors[1],label="Verified feasible cooling")
    for i,r in enumerate(grid.values()):
        xx=r["count"]+.75
        right.vlines(xx,r["gain_k"],r["max_possible_gain_k"],color=colors[2],ls="--")
        right.plot(xx,r["max_possible_gain_k"],"_",color=colors[2],markersize=11)
        right.plot(xx,r["gain_k"],"s",color=colors[2],markersize=4,clip_on=False,
                   label="Tighter grid-start interval" if i==0 else None)
    right.set(xticks=n,xlabel="Chiplets on interchangeable slots",ylabel="3D peak reduction (K)",
              title="How much more cooling is possible?")
    right.legend(frameon=False,fontsize=8)
    for axis in (left,right):
        axis.spines[["top","right"]].set_visible(False)
        axis.grid(axis="y",alpha=.2)
        axis.set_axisbelow(True)
        axis.set_ylim(bottom=0)
    fig.savefig(root/"comparison.png",dpi=160)
    plt.close(fig)


if __name__=="__main__":
    main()
