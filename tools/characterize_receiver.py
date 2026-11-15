"""Transistor-level setup/hold of SKY130 dfxtp_1 by bisection (gate of docs/receiver-constraint-plan.md).

One flip-flop at a uniform temperature (ngspice global .temp, which ngspice applies),
pinned netlist and hash-locked tt models. Times are D 50% to CLK 50%; slews are 20-80%.
Pass criterion of one trial: Q makes one lasting transition to the expected value (its last
50% crossing is the output time; non-finite waves fail) and clock-to-Q is at most 110% of the reference with the data edge 2 ns away from the clock. Setup is the smallest
data lead that passes; hold is the smallest delay after the clock edge of a new data
value that still leaves the old capture intact. These criteria are declared, not Liberty's.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np

VDD = 1.8
NETLIST_SHA = '39049c3c6a74ac24fdc0d93528dd5b0e15f7ef51729008913bdeeee0d8ead2df'
EDGE_NS = (5., 15.)  # rising clock edges at 50%: first one initialises Q, second one is tested


def ramp(t50, slew, rising):
    """PWL points of a full-swing linear edge whose 20-80% time is `slew` and 50% time is t50."""
    full = slew/.6
    a, b = (0, VDD) if rising else (VDD, 0)
    return [(t50 - full/2, a), (t50 + full/2, b)]


def pwl(points):
    return ' '.join(f'{t:.6f}n {v}' for t, v in [(0., points[0][1])] + points + [(30., points[-1][1])])


def crossing(t, v, level, rising, after, last=False):
    """First (or last) crossing of `level` in the given direction after `after` (ns)."""
    m = t >= after
    t, v = t[m], v[m]
    above = v >= level if rising else v <= level
    hit = np.flatnonzero(above[1:] & ~above[:-1])
    if not hit.size:
        return None
    i = hit[-1] if last else hit[0]
    return float(t[i] + (level - v[i])*(t[i + 1] - t[i])/(v[i + 1] - v[i]))


def clock_to_q(t, clk, q, expect_high):
    """Clock-to-Q (ns) at the second edge, or None unless Q makes one lasting transition to the expected value.

    Non-finite samples reject the trial. The output time is Q's last 50% crossing into the expected
    value, so a glitch that crosses early and returns delays the reading instead of passing it.
    """
    if not (np.isfinite(t).all() and np.isfinite(clk).all() and np.isfinite(q).all()):
        return None
    settled = q[(t >= EDGE_NS[1] + 4) & (t <= EDGE_NS[1] + 5)]
    if not settled.size or abs(settled.mean() - (VDD if expect_high else 0)) > .1*VDD or np.ptp(settled) > .05*VDD:
        return None
    start = q[(t >= EDGE_NS[1] - 1.5) & (t <= EDGE_NS[1] - 1)]
    if not start.size or abs(start.mean() - (0 if expect_high else VDD)) > .1*VDD:
        return None  # the first edge must have captured the opposite value
    c = crossing(t, clk, VDD/2, True, EDGE_NS[1] - 1)
    qc = crossing(t, q, VDD/2, expect_high, EDGE_NS[1] - 1, last=True)
    return None if c is None or qc is None else qc - c


class Simulator:
    def __init__(self, ngspice, model, netlist, temp, clk_slew, d_slew, step_ps):
        self.ngspice, self.model, self.netlist = ngspice, model, netlist
        self.temp, self.clk_slew, self.d_slew, self.step = temp, clk_slew, d_slew, step_ps
        self.runs = 0

    def run(self, d_points, expect_high):
        """Clock-to-Q (ns) at the second edge, or None if Q does not settle as expected."""
        clock = ramp(EDGE_NS[0], self.clk_slew, True) + ramp(EDGE_NS[0] + 5, self.clk_slew, False) \
            + ramp(EDGE_NS[1], self.clk_slew, True) + ramp(EDGE_NS[1] + 5, self.clk_slew, False)
        with tempfile.TemporaryDirectory() as folder:
            deck = f'''dfxtp_1 constraint trial
.lib "{self.model}" tt
.include "{self.netlist}"
.options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8
.temp {self.temp}
VDD vdd 0 {VDD}
VCLK clk 0 PWL({pwl(clock)})
VD d 0 PWL({pwl(d_points)})
Xff clk d 0 0 vdd vdd q sky130_fd_sc_hd__dfxtp_1
Cload q 0 0.005p
.control
set wr_singlescale
set numdgt=12
tran {self.step}p 30n 0 {self.step}p
wrdata wave.txt v(clk) v(d) v(q)
quit
.endc
.end
'''
            (Path(folder)/'deck.sp').write_text(deck)
            init = Path(folder)/'init'
            init.mkdir()
            (init/'spinit').write_text('* explicit models only\n')
            done = subprocess.run([self.ngspice, '-b', 'deck.sp'], cwd=folder, capture_output=True, text=True,
                                  timeout=300, env={**os.environ, 'SPICE_SCRIPTS': str(init)})
            self.runs += 1
            if done.returncode:
                raise RuntimeError(done.stdout[-2000:] + done.stderr[-2000:])
            w = np.loadtxt(Path(folder)/'wave.txt')
        return clock_to_q(w[:, 0]*1e9, w[:, 1], w[:, 3], expect_high)  # wr_singlescale: time, clk, d, q


def setup_trial(sim, edge, lead):
    """D makes the tested transition `lead` ns before the second clock edge (50%-50%)."""
    rising = edge == 'rise'
    first = ramp(EDGE_NS[0] - 3, sim.d_slew, not rising)  # first edge captures the opposite value
    return sim.run(first + ramp(EDGE_NS[1] - lead, sim.d_slew, rising), rising)


def hold_trial(sim, edge, delay):
    """The second edge captures the old value; D makes the tested transition `delay` ns after it."""
    rising = edge == 'rise'  # hold rise_constraint: D rises after the edge, so the captured value is low
    points = ramp(EDGE_NS[0] - 3, sim.d_slew, rising)           # first edge captures the opposite value
    points += ramp(EDGE_NS[0] + 5, sim.d_slew, not rising)      # old value, set up long before edge two
    points += ramp(EDGE_NS[1] + delay, sim.d_slew, rising)      # the tested late transition
    return sim.run(points, not rising)


def bisect(trial, low, high, reference, tol=0.001):
    """Smallest x in [low, high] whose trial passes (pass is monotone in x)."""
    ok = lambda x: (lambda d: d is not None and d <= 1.1*reference)(trial(x))
    if not ok(high) or ok(low):
        raise ValueError('constraint not bracketed')
    while high - low > tol:
        middle = (low + high)/2
        low, high = (low, middle) if ok(middle) else (middle, high)
    return high


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ngspice', required=True)
    parser.add_argument('--model', type=Path, required=True, help='sky130.lib.spice')
    parser.add_argument('--netlist', type=Path, required=True, help='pinned dfxtp_1.spice')
    parser.add_argument('--clk-slew', type=float, required=True)
    parser.add_argument('--d-slew', type=float, required=True)
    parser.add_argument('--temperatures', type=float, nargs='+', default=[25., 62.5, 100.])
    parser.add_argument('--step-ps', type=float, default=1.)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sha256(args.netlist.read_bytes()).hexdigest() != NETLIST_SHA:
        raise SystemExit('pinned netlist mismatch')
    rows = []
    for temp in args.temperatures:
        sim = Simulator(args.ngspice, args.model.resolve(), args.netlist.resolve(), temp,
                        args.clk_slew, args.d_slew, args.step_ps)
        for edge in ('rise', 'fall'):
            ref_setup, ref_hold = setup_trial(sim, edge, 2.), hold_trial(sim, edge, 2.)
            if ref_setup is None or ref_hold is None:
                raise ValueError('reference trial failed')
            rows.append(dict(temp_c=temp, edge=edge, reference_clock_to_q_ns=ref_setup,
                             setup_ns=bisect(lambda x: setup_trial(sim, edge, x), -1., 2., ref_setup),
                             hold_ns=bisect(lambda x: hold_trial(sim, edge, x), -1., 2., ref_hold)))
            print(json.dumps(rows[-1]), flush=True)
    args.output.write_text(json.dumps(dict(
        physical_qualified=False, criterion='Q correct and clock-to-Q <= 1.1 x reference (data edge 2 ns away)',
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), netlist_sha256=NETLIST_SHA,
        model=str(args.model), clk_slew_ns=args.clk_slew, d_slew_ns=args.d_slew, step_ps=args.step_ps,
        load_pf=0.005, rows=rows), indent=2) + '\n')


if __name__ == '__main__':
    main()
