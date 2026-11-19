"""Steady-solve bounds on cycle peaks under unrestricted periodic task orders."""
import argparse
from itertools import permutations
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse.linalg import splu

from chiplet_floorplanning.package import checked_solution
from cut_traffic import EVIDENCE
from periodic_layout_choice import atplace_inputs, nas_inputs, package_model
from shared_capacity import NAMES


def bounds(model, free_shares):
    g, _, rhs, sink, observed, ambient = model
    # The envelope source can exceed any physically attainable total watts.
    # It is used only for a conservative upper bound.
    columns = np.column_stack((rhs, rhs.max(axis=1)))
    fields = splu(g.tocsc(), permc_spec="MMD_AT_PLUS_A").solve(columns)
    for p, t in zip(columns.T, fields.T):
        checked_solution(g, p, sink, t)
    peaks = fields[observed] + ambient
    modes = rhs.shape[1]
    if free_shares:
        limits = np.column_stack((peaks[:, :modes], -np.ones(len(observed))))
        lp = linprog(np.r_[np.zeros(modes), 1.], A_ub=limits, b_ub=np.zeros(len(limits)),
                     A_eq=[np.r_[np.ones(modes), 0.]], b_eq=[1.],
                     bounds=[(0, 1)]*modes + [(None, None)], method="highs")
        if not lp.success:
            raise RuntimeError(lp.message)
        shares = lp.x[:modes]
        np.testing.assert_allclose(lp.fun, (peaks[:, :modes] @ shares).max(), atol=1e-6, rtol=0)
    else:
        shares = np.full(modes, 1/modes)
    return dict(lower_c=float((peaks[:, :modes] @ shares).max()), upper_c=float(peaks[:, -1].max()),
                lower_mode_fractions=shares.tolist(), pure_peaks_c=peaks[:, :modes].max(axis=0).tolist(),
                powers_w=rhs.sum(0).tolist(), envelope_power_w=float(columns[:, -1].sum()))


def compare(name, cap, inputs, free_shares):
    rows = [dict(layout=i, wire_m=length, **bounds(package_model(data), free_shares)) for i,length,data in inputs]
    pairs = [dict(cooler=a["layout"], warmer=b["layout"], guaranteed_gap_k=b["lower_c"]-a["upper_c"])
             for a,b in permutations(rows, 2) if b["lower_c"]-a["upper_c"] > 1e-6]
    return dict(case=name, length_cap_m=cap, layouts=rows, separated=pairs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    cases = json.loads((EVIDENCE/"layout-dominance-v1.json").read_bytes())["cases"]
    synthetic = []
    for r in cases:
        path = args.cases/(r["case"]+".json")
        synthetic.append(compare(r["case"], r["length_cap_m"], atplace_inputs(path, r, 32), False))
    nas = []
    for grid in (64, 96):
        cap, inputs = nas_inputs(args.cases/"Case3.json", grid, NAMES)
        nas.append(dict(grid=grid, **compare("Case3 NAS", cap, inputs, True)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(synthetic=synthetic, nas_modes=NAMES, nas=nas),
                                      indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
