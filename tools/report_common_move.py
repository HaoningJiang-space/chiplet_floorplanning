"""Report case-paired gains at a fixed connection cap and cost at a common cooling target."""

import argparse
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from chiplet_floorplanning.placement.geometry import boxes
from common_relocation import FOUR, PAIR, TARGET
from power_uncertainty import cases, text_digest


def case9_figure(inputs, paired, trial, path):
    p,designs,_ = next(x for x in cases(inputs) if x[0].name=="Case9")
    _,start,_ = min(designs,key=lambda x:x[0])
    action = paired["actions"]["pair"]
    fig,(plan,ax) = plt.subplots(1,2,figsize=(9.7,4.4),layout="constrained",width_ratios=(1.1,1))
    colors = ("#137768","#3556a1")
    outline = boxes(p,start)/1000
    for i,(x,y,u,v) in enumerate(outline):
        plan.add_patch(Rectangle((x,y),u-x,v-y,fc="#dce2e5",ec="#77858f",lw=.75))
    for k,i in enumerate(action["indices"]):
        old = np.array(action["from_um"][k])/1000
        new = np.array(action["to_um"][k])/1000
        x,y,u,v = outline[i]
        plan.add_patch(Rectangle((x,y),u-x,v-y,fc=colors[k],alpha=.8))
        plan.add_patch(Rectangle((x,y)+new-old,u-x,v-y,ec=colors[k],fc="none",lw=1.8,ls="--"))
        plan.annotate("",new,old,arrowprops=dict(arrowstyle="-|>",lw=2,color=colors[k],mutation_scale=16))
        plan.plot([],[],color=colors[k],lw=3,label=action["chips"][k])
    plan.set(xlim=(0,p.carrier_um[0]/1000),ylim=(0,p.carrier_um[1]/1000),aspect="equal",
             xlabel="Carrier x (mm)",ylabel="Carrier y (mm)")
    plan.legend(loc="upper center",bbox_to_anchor=(.5,-.14),ncol=2,frameon=False)
    plan.set_title("Case9  |  Two simultaneous moves",loc="left",fontweight="bold",fontsize=12)
    readings = trial["grid64"]["conditions"]
    xs = np.arange(2)
    for i,(part,b) in enumerate(paired["part_worst"].items()):
        xy = b.split("/")[1].split(",")
        labels = [action["chips"][i]+" alone","Together"]
        values = [readings[b][part]["cooling_k"],readings[b]["pair"]["cooling_k"]]
        bars = ax.bar(xs+i*2.7,values,color=[colors[i],"#cc7731"],width=.76)
        ax.bar_label(bars,fmt="%.2f",padding=3,fontsize=9)
        for j,label in enumerate(labels):
            ax.text(xs[j]+i*2.7,-2.29,label,ha="center",va="top",fontsize=8)
        ax.text(.5+i*2.7,-2.82,f"Cold plate ({100+12*int(xy[0])}, {100+12*int(xy[1])}) mm",ha="center",fontsize=8)
    ax.axhline(0,color="#555",lw=.8)
    ax.set(xticks=[],ylim=(-3.15,4.3),ylabel="Reduction in 3-D package peak (K)")
    ax.spines[["top","right","bottom"]].set_visible(False)
    ax.set_title("Each move's adverse contact",loc="left",fontweight="bold",fontsize=12)
    fig.savefig(path,dpi=180,bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",type=Path,required=True)
    ap.add_argument("--evidence",type=Path,required=True)
    args = ap.parse_args()
    d = args.evidence
    def load(name):
        return json.loads((d/(name+".json")).read_bytes())
    p,s,hold,exp,pair,trial = map(load,("predictions","package","holdout","expanded-package","pair-predictions","pair-package"))
    assert s["locked_sha256"] == hold["locked_sha256"] == text_digest(d/"predictions.json")
    assert hold["package_sha256"] == text_digest(d/"package.json")
    assert exp["expanded_sha256"] == pair["expanded_sha256"] == text_digest(d/"expanded-predictions.json")
    assert trial["paired_sha256"] == text_digest(d/"pair-predictions.json")
    thirteen = (*FOUR,"centre",*hold["diagonal_centres_mm"])
    domains = dict(two=PAIR, north_south=FOUR[2:], four=FOUR, five=(*FOUR,"centre"), centre=("centre",),
                   thirteen=thirteen, fifteen=(*thirteen,"held_3_-9","held_-9_3"))
    details = {}
    for name,r in s["cases"].items():
        rows = r["conditions"]
        data = {}
        for label,domain in domains.items():
            arms = {}
            choices = {"thirteen":("four","expanded","pair"), "fifteen":("expanded","pair")}.get(
                label,("four","two","old_hot","half_space"))
            for arm in choices:
                action = p["cases"][name]["actions"].get(arm,{"cost":r["cap"]})
                if arm=="pair":
                    action = pair["cases"][name]["actions"]["pair"]
                    t = trial["cases"][name]
                    gains = [0.] if t["stayed"] else [t["grid64"]["conditions"][b]["pair"]["cooling_k"] for b in domain]
                elif arm=="expanded":
                    t = exp["cases"][name]
                    gains = [0.] if t["stayed"] else [t["grid64"]["conditions"][b]["expanded"]["cooling_k"] for b in domain]
                    if not t["stayed"]:
                        action = {"cost":t["grid64"]["conditions"]["west"][arm]["cost"]}
                else:
                    all_rows = rows | hold["cases"][name].get("additional64",{}).get("conditions",{})
                    if arm=="four" and hold["cases"][name]["stayed"]:
                        assert not action["chips"]
                        gains = [0.]
                    else:
                        gains = [all_rows[b][arm]["cooling_k"] for b in domain]
                assert action["cost"] <= r["cap"]+1e-9
                arms[arm] = dict(worst_cooling_k=min(gains),cost=action["cost"])
            passing = [a for a,v in arms.items() if v["worst_cooling_k"] >= TARGET]
            shortest = min(passing,key=lambda a:arms[a]["cost"],default=None)
            data[label] = dict(arms=arms,shortest_at_target=shortest,
                               cost_at_target=arms[shortest]["cost"] if shortest else None)
        details[name] = dict(metric=r["metric"],cap=r["cap"],domains=data)
    aggregate = {}
    for group in domains:
        groupdata = [v["domains"][group]["arms"] for v in details.values()]
        aggregate[group] = {}
        for a in groupdata[0]:
            vals = [g[a]["worst_cooling_k"] for g in groupdata]
            aggregate[group][a] = dict(cooled_over_target=sum(x>TARGET for x in vals),
                                       warmed_over_target=sum(x< -TARGET for x in vals),median_worst_k=median(vals))
    (d/"summary.json").write_text(json.dumps(dict(aggregate=aggregate,cases=details),indent=2)+"\n",
                                  encoding="utf-8",newline="\n")
    case9_figure(args.cases,pair["cases"]["Case9"],trial["cases"]["Case9"],d/"case9.png")


if __name__ == "__main__":
    main()
