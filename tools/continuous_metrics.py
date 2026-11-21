"""Pin-distance, routing-capacity and steady-state thermal metrics for continuous layouts."""
import numpy as np

from chiplet_floorplanning.placement.geometry import is_legal, pin_points_um
from chiplet_floorplanning.placement.thermal import die_peaks_c, solve, thermal_case_data


GAP_UM = 100
THERMAL_RESOLUTION = 64
TRACKS_PER_MM = 500


def inspect(p, layout, reach, cap):
    """Check per-net reach (mm), total pin length (m) and full-carrier cut capacity."""
    pins_mm = pin_points_um(p, layout) / 1000
    length_mm = np.abs(pins_mm[:, 0] - pins_mm[:, 1]).sum(axis=1)
    excess_mm = length_mm - reach
    # Each 1 mm boundary is a cut through the other full carrier dimension.
    # Tracks under the dies participate in this capacity.
    side_mm = np.array(p.carrier_um) / 1000
    cut_util = 0.
    for axis in (0, 1):
        ends = np.sort(pins_mm[:, :, axis], axis=1)
        borders = np.arange(1., side_mm[axis])
        entering = np.searchsorted(np.sort(ends[:, 0]), borders, side='left')
        leaving = np.searchsorted(np.sort(ends[:, 1]), borders, side='left')
        capacity = np.floor(side_mm[1-axis] * TRACKS_PER_MM)
        cut_util = max(cut_util, float((entering - leaving).max(initial=0) / capacity))
    legal = is_legal(p, layout, GAP_UM)
    wire_m = float(length_mm.sum() / 1000)
    return dict(
        legal=legal, wire_m=wire_m, max_net_mm=float(length_mm.max()),
        reach_violations=int((excess_mm > 1e-9).sum()), worst_excess_mm=max(0., float(excess_mm.max())),
        full_cut_utilization=cut_util,
        feasible=bool(legal and wire_m <= cap + 1e-9 and excess_mm.max() <= 1e-9 and cut_util <= 1.),
    )


def escape_util(p, lay):
    """Largest ratio of escaping signal pins to tracks on the interior edges of a 1 mm bin."""
    side_mm = np.array(p.carrier_um) / 1000
    shape = np.ceil(side_mm).astype(int)
    bins = np.clip(np.floor(pin_points_um(p, lay) / 1000).astype(int), 0, shape-1)
    index = bins[:, :, 0] + shape[0] * bins[:, :, 1]
    escaping = index[index[:, 0] != index[:, 1]].ravel()
    demand = np.bincount(escaping, minlength=int(np.prod(shape))).reshape(shape[::-1])

    x, y = np.arange(shape[0]), np.arange(shape[1])
    width_mm = np.minimum(1., side_mm[0] - x)
    height_mm = np.minimum(1., side_mm[1] - y)
    sides_x = (x > 0).astype(int) + (x+1 < shape[0])
    sides_y = (y > 0).astype(int) + (y+1 < shape[1])
    vertical = (height_mm * TRACKS_PER_MM).astype(int)[:, None] * sides_x[None, :]
    horizontal = sides_y[:, None] * (width_mm * TRACKS_PER_MM).astype(int)[None, :]
    return float((demand / (vertical + horizontal)).max())


def verified(p, layout):
    """Evaluate the board once and return the summary and each die's peak temperature."""
    summary, rise, edges = solve(thermal_case_data(p, layout, GAP_UM, THERMAL_RESOLUTION))
    return summary, die_peaks_c(p, layout, rise, edges)


def point(p, layout, reach, cap):
    return dict(centre_um=layout.centre_um.tolist(), rotation_deg=layout.rotation_deg.tolist(),
                **inspect(p, layout, reach, cap))
