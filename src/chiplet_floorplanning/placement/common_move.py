"""Select one feasible layout that cools every declared boundary as much as possible."""

from dataclasses import dataclass

import numpy as np

from .cooled_sheet import VERTICAL_MM2_K_W


class HotspotResponse:
    """Temperature at a starting hotspot per watt placed in each 1 mm sheet cell."""

    def __init__(self, sheet, initial_watts):
        initial = sheet.temperatures(initial_watts)
        self._set_cell(sheet, initial, np.unravel_index(initial.argmax(), initial.shape))

    @classmethod
    def at_cell(cls, sheet, initial, cell_yx):
        """Build the adjoint at a specified observer using the already solved starting field."""
        row = cls.__new__(cls)
        row._set_cell(sheet, initial, cell_yx)
        return row

    def _set_cell(self, sheet, initial, cell_yx):
        self.peak_k = float(initial.max())
        self.cell_yx = tuple(cell_yx)
        self.headroom_k = self.peak_k - float(initial[self.cell_yx])
        impulse = np.zeros_like(initial)
        impulse[self.cell_yx] = 1
        response = sheet.factor.solve(impulse.ravel(), trans="T").reshape(impulse.shape) + VERTICAL_MM2_K_W * impulse
        self.origin = sheet.edges[0] - sheet.carrier_offset
        self.prefix = np.pad(response.cumsum(0).cumsum(1), ((1,0),(1,0)))

    def integral(self, xy):
        # Bilinear interpolation of the cumulative integral is exact inside a uniform cell.
        x,y = (np.asarray(xy) - self.origin).T
        n = self.prefix.shape[0] - 1
        i,j = np.minimum(x.astype(int), n-1), np.minimum(y.astype(int), n-1)
        dx,dy = x-i, y-j
        f = self.prefix
        return ((1-dy)*((1-dx)*f[j,i] + dx*f[j,i+1]) +
                dy*((1-dx)*f[j+1,i] + dx*f[j+1,i+1]))

    def contribution(self, centres_mm, sizes_mm, power_w):
        lo, hi = centres_mm - sizes_mm/2, centres_mm + sizes_mm/2
        total = (self.integral(hi) + self.integral(lo) - self.integral(np.column_stack((hi[:,0],lo[:,1])))
                 - self.integral(np.column_stack((lo[:,0],hi[:,1]))))
        return power_w * total / sizes_mm.prod(axis=1)


def cooling_bounds(bank, start, sizes_mm, power_w, response):
    """Remove the old source footprint and place it at its proposed destination."""
    parents, chips, centres = [], [], []
    for index, move in enumerate(bank):
        for chip, xy in zip(move.chips, move.destinations_um):
            parents.append(index)
            chips.append(chip)
            centres.append(xy)
    if not chips:
        return np.zeros(len(bank))
    initial = response.contribution(start.centre_um/1000, sizes_mm, power_w)
    chips = np.asarray(chips)
    after = response.contribution(np.asarray(centres)/1000, sizes_mm[chips], power_w[chips])
    return np.bincount(parents, initial[chips]-after, minlength=len(bank))


@dataclass(frozen=True)
class CommonMove:
    index: int
    best_gain_k: float
    checked_moves: int


def common_landing(upper, costs, exact_gain, threshold_k=0.1):
    """Maximize the minimum gain in the fixed action set. Index zero denotes staying put."""
    order = sorted(range(1,len(upper)), key=lambda i: (-upper[i], costs[i], i))
    best, best_gain, checked = 0, 0., 0
    for i in order:
        if upper[i] < best_gain - 1e-8:
            break
        gain = float(exact_gain(i))
        checked += 1
        if gain > upper[i] + 1e-8:
            raise ValueError("model gain exceeds the old-hotspot bound")
        if (-gain, costs[i], i) < (-best_gain, costs[best], best):
            best, best_gain = i, gain
    return CommonMove(best if best_gain > threshold_k else 0, best_gain, checked)
