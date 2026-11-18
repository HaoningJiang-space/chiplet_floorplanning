"""Bound the peak over every continuous four-CPU floorplan at each specified combined span."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import permutations
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

from case3_ring_certificate import mutual_tables
from compare_wire_heat import digest

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--nodes", type=int, default=180000)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("use a fresh output file")
    ring_file = EVIDENCE / "case3-ring-certificate-v1.json"
    cut_file = EVIDENCE / "case3-interface-cut-v1.json"
    h = json.loads(ring_file.read_text())["heat_lower_bound"]
    wide = json.loads(cut_file.read_text())["wide_span"]["universal_upper_mm"]
    spans = [40.0, wide, 56.0]
    k = mutual_tables(np.array(h["radii_mm"]), np.array(h["coefficients_k_w"]))
    # Taking the smallest kernel over the placement orientations relaxes all orientation coupling.
    kernel = np.minimum.reduce(list(k.values()))
    kernel = np.minimum.accumulate(np.minimum.accumulate(kernel, axis=0), axis=1)
    assert (
        np.max(np.diff(kernel, axis=0)) < 1e-12
        and np.max(np.diff(kernel, axis=1)) < 1e-12
    )
    assert np.max(abs(kernel - kernel.T)) < 1e-12
    blob = kernel.astype("<f8").tobytes()
    cpp = Path(__file__).with_name("wide_span_bound.cpp")
    with TemporaryDirectory(dir=args.output.parent) as temp:
        binary = Path(temp).resolve() / "bound"
        subprocess.run(
            ["c++", "-O3", "-std=c++17", str(cpp), "-o", str(binary)], check=True
        )

        def run(job):
            span, order = job
            ticks = int(np.ceil(span * 8))
            cmd = [
                str(binary),
                str(ticks),
                str(h["cpu_self_floor_k"]),
                str(args.nodes),
                order,
            ]
            r = subprocess.run(cmd, input=blob, capture_output=True, check=True)
            rise, n, q, leaf, discard = r.stdout.split()
            return dict(
                span_mm=span,
                outer_span_mm=ticks / 8,
                y_ranks_in_x_order=order,
                lower_peak_c=45 + float(rise),
                expanded=int(n),
                open_boxes=int(q),
                terminal_boxes=int(leaf),
                infeasible_children=int(discard),
            )

        with ThreadPoolExecutor(args.workers) as pool:
            rows = list(
                pool.map(
                    run,
                    [
                        (s, "".join(map(str, p)))
                        for s in spans
                        for p in permutations(range(4))
                    ],
                )
            )
    result = dict(
        driver_sha256=digest(Path(__file__)),
        cpp_sha256=digest(cpp),
        prior_sha256={p.name: digest(p) for p in (cut_file, ring_file)},
        self_floor_k=h["cpu_self_floor_k"],
        nodes_per_order=args.nodes,
        rows=rows,
    )
    args.output.write_text(json.dumps(result, allow_nan=False) + "\n")
    for s in spans:
        print(s, min(r["lower_peak_c"] for r in rows if r["span_mm"] == s), flush=True)


if __name__ == "__main__":
    main()
