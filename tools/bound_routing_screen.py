"""Layout-independent upper bounds on the necessary routing screen's utilization.

The screen (removed with the atplace_* chain; frozen at f1df9fd) tests, on 1 mm
bins with 2 um tracks and one layer per direction:
  cut:     nets crossing a full-width/height cut <= cross-section tracks;
  escape:  nets leaving a bin <= tracks on the bin's boundary edges;
  access:  pins in a bin <= (bin/access_pitch)^2.
For every legal layout (gap >= bin size, so a half-open bin holds pins of at most
one die), demand is bounded by data alone:
  cut <= nets / (min(rows, cols) * tracks_per_bin);
  escape, access <= max pins of one die inside any closed bin-sized window.
If every bound is below 1, the screen cannot reject any legal layout of the case.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Problem

BIN_UM, TRACK_PITCH_UM, ACCESS_PITCH_UM = 1000, 2, 2


def window_max(points, size):
    """Most points inside any closed size x size axis-aligned square (rotation invariant)."""
    if not len(points):
        return 0
    points = points[np.argsort(points[:, 0], kind='stable')]
    xs = points[:, 0]
    best = 0
    for i in range(len(points)):
        # Some optimal square has its left edge on a point; then slide in y.
        j = np.searchsorted(xs, xs[i] + size, side='right')
        ys = np.sort(points[i:j, 1])
        if len(ys) <= best:
            continue
        upper = np.searchsorted(ys, ys + size, side='right')
        best = max(best, int((upper - np.arange(len(ys))).max()))
    return best


def bounds(problem, gap_um):
    if gap_um < BIN_UM:
        raise ValueError('one-die-per-bin argument needs gap >= bin size')
    tracks = BIN_UM // TRACK_PITCH_UM
    rows, cols = (int(problem.carrier_um[1] // BIN_UM), int(problem.carrier_um[0] // BIN_UM))
    nets = len(problem.pin_chip)
    per_die = []
    for k in range(problem.count):
        mask = problem.pin_chip == k
        per_die.append(window_max(np.round(problem.pin_offset_um[mask], 6), BIN_UM))
    pins_in_bin = max(per_die)
    return dict(case=problem.name, chips=problem.count, nets=nets, carrier_bins=[cols, rows],
                cut_utilization_bound=nets/(min(rows, cols)*tracks),
                max_pins_one_bin_bound=pins_in_bin,
                escape_utilization_bound=pins_in_bin/(2*tracks),  # corner bin: one h edge + one v edge
                access_utilization_bound=pins_in_bin/(BIN_UM//ACCESS_PITCH_UM)**2)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cases', type=Path, nargs='+')
    parser.add_argument('--gap-um', type=float, default=1000)
    args = parser.parse_args()
    for path in args.cases:
        b = bounds(Problem.from_imported(json.loads(path.read_text())), args.gap_um)
        b['screen_can_reject'] = max(b['cut_utilization_bound'], b['escape_utilization_bound'],
                                     b['access_utilization_bound']) >= 1
        print(json.dumps(b), flush=True)


if __name__ == '__main__':
    main()
