"""Draw the measured 64-slot example using its two saved power assignments."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("figure", type=Path)
    args = parser.parse_args()
    data = json.loads(args.evidence.read_bytes())["cases"]["slots_8x8_folded_torus_grid_start"]["joint"]
    example = next(v for v in data["same_power_single_axis_examples"] if v["axis"] == "rows")
    identity = np.arange(64)
    mapped = np.asarray(example["chip_to_slot"])
    source_rows = np.argsort(mapped).reshape(8, 8)[:, 0] // 8
    cold, hot = "#8dbec7", "#ca6546"
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 4.3))
    for ax, title, peak, rows in zip(axes, ("Original row order", "Pin-feasible row order"),
                                    (data["initial_peak_c"], data["peak_c"]),
                                    (identity.reshape(8, 8)[:, 0]//8, source_rows)):
        for row, source in enumerate(rows):
            for col in range(8):
                ax.add_patch(Rectangle((col-.39, row-.39), .78, .78,
                                       facecolor=cold if source < 4 else hot, edgecolor="none"))
            ax.text(-.72, row, str(source+1), ha="right", va="center", fontsize=9)
        ax.set(xlim=(-1.2,7.6), ylim=(-.65,7.62), aspect="equal", title=f"{title}\n3D peak {peak:.3f} °C")
        ax.axis("off")
    fig.legend(handles=[Patch(color=cold, label="1.025 W"), Patch(color=hot, label="3.075 W")],
               loc="lower center", ncol=2, frameon=False)
    fig.suptitle("64-chiplet folded torus  |  pin length 1.921795 m in both layouts", fontsize=12)
    fig.subplots_adjust(top=.77,bottom=.13,left=.03,right=.98,wspace=.06)
    fig.savefig(args.figure,dpi=160,bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
