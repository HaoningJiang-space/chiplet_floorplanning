"""Freeze two different RapidChiplet topology-generator outputs without using thermal results."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


REV = "17176f92c91eda629a25bc11bf7959d6b963a23b"
SEED = 20261119


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rapidchiplet", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.rapidchiplet.resolve()
    assert subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() == REV
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("upstream_topology", root/"generate_topology.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    chip = json.loads((root/"inputs/chiplets/chiplets_example_experiment.json").read_bytes())["example_experiment"]
    size = np.array([chip["dimensions"][axis] for axis in "xy"])
    pins = np.array([[v["x"],v["y"]] for v in chip["phys"]])-size/2
    data = {}
    for name, rows, cols in (("mesh",3,4), ("folded_torus",4,4)):
        edges = getattr(module, "generate_"+name+"_topology")(dict(rows=rows, cols=cols))
        links = [[e["ep1"],e["ep2"]] for e in edges]
        n = rows*cols
        pitch = size+3.
        xy = np.array([[x,y] for y in range(rows) for x in range(cols)])*pitch + size/2+3.
        xy = xy[np.random.default_rng(SEED).permutation(n)]
        data[f"RC-{name}-{rows}x{cols}"] = dict(size_um=(1000*size).tolist(), rated_w=chip["power"],
            from_um=(1000*xy).tolist(), carrier_um=(1000*(np.array([cols-1,rows-1])*pitch+size+6)).tolist(),
            pin_chip=[[v["outer_id"] for v in e] for e in links],
            pin_offset_um=[[list(1000*pins[v["inner_id"]]) for v in e] for e in links])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(source_revision=REV, seed=SEED, cases=data), indent=2)+"\n",
                           encoding="utf8", newline="\n")


if __name__ == "__main__":
    main()
