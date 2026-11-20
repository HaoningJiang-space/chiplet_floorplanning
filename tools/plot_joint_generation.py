"""Plot the signed temperature changes at the limiting cold-plate position of a published move."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement.geometry import boxes
from common_relocation import FOUR
from direct_relocation import rebuild
from generate_joint_landings import thermal_start
from transfer_placement import starting_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--search", required=True, type=Path)
    parser.add_argument("--case", default="Case3")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    row = json.loads(args.search.read_bytes())["cases"]["contacts"][args.case]
    p, start, _, _ = next(v for v in starting_cases(args.cases) if v[0].name == args.case)
    move = row["action"]
    end = rebuild(start, move)
    sheets, old = thermal_start(p, start)
    watts = sheets[0].power_map(end)
    new = [sh.temperatures(watts) for sh in sheets]
    gains = [a.max()-b.max() for a,b in zip(old, new)]
    b = int(np.argmin(gains))
    assert abs(gains[b]-row["gain_k"]) < 1e-8
    sh = sheets[b]
    low, high = sh.edges[[0,-1]]
    x, y = sh.carrier_offset
    extent = (low-x, high-x, low-y, high-y)
    width, height = np.array(p.carrier_um)/1000
    centres = (sh.edges[1:] + sh.edges[:-1])/2
    visible = np.ix_((centres-y>=0) & (centres-y<=height), (centres-x>=0) & (centres-x<=width))
    t0, t1 = old[b], new[b]
    diff = t1-t0
    norm = Normalize(min(t0[visible].min(), t1[visible].min()), max(t0.max(), t1.max()))
    limit = abs(diff[visible]).max()
    fig, axes = plt.subplots(1, 3, figsize=(12.8, 4.4), layout="constrained")
    for ax, layout, data, title in zip(axes, (start, end, end), (t0, t1, diff),
                                      ("Start", "Selected joint landing", "Change after both moves")):
        change = ax is axes[-1]
        img = ax.imshow(data, extent=extent, origin="lower", cmap="RdBu_r" if change else "magma",
                        norm=Normalize(-limit, limit) if change else norm, interpolation="nearest")
        for i, (x0,y0,x1,y1) in enumerate(boxes(p,layout)/1000):
            active = i in move["indices"]
            edge = ("black" if change else "white") if active else ("#666666" if change else "#bdbdbd")
            ax.add_patch(Rectangle((x0,y0), x1-x0, y1-y0, fill=False, edgecolor=edge,
                                   linewidth=1.5 if active else .55))
            if active and not change:
                ax.text((x0+x1)/2,(y0+y1)/2,p.names[i], ha="center",va="center",fontsize=8,
                        color="white",bbox=dict(facecolor="#202020",edgecolor="none",alpha=.75,pad=1.6))
        if change:
            for before, after in zip(move["from_um"],move["to_um"]):
                ax.annotate("", np.array(after)/1000, np.array(before)/1000,
                            arrowprops=dict(arrowstyle="->", color="#161616", lw=1.6))
        else:
            iy, ix = np.unravel_index(data.argmax(), data.shape)
            ax.plot(centres[ix]-x,centres[iy]-y,marker="*",color="#a9fbff",markeredgecolor="black",ms=12)
        ax.set(xlim=(0,width),ylim=(0,height),xlabel="x (mm)",title=title)
        if ax is axes[0]:
            ax.set_ylabel("y (mm)")
        fig.colorbar(img,ax=ax,location="bottom",shrink=.88,pad=.12,
                     label="Temperature change (K)" if change else "Temperature above ambient (K)")
    fig.suptitle(f"{p.name}  |  {FOUR[b]} cold plate  |  peak falls {gains[b]:.3f} K", fontsize=15)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.output,dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
