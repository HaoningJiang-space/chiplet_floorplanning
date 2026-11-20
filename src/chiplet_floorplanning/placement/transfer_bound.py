"""Enclose peak-temperature changes of a power transfer for passive cooled contacts."""

from dataclasses import dataclass

import numpy as np
from scipy.fft import dctn, idctn

from .cooled_sheet import footprint


def moved_watts(sheet, start, move, sizes_mm, power_w):
    """Deposit only moved rectangles on the 1 mm grid, including fractional edge cells."""
    n = len(sheet.edges)-1
    delta = np.zeros((n, n))
    for chip, destination in zip(move.chips, move.destinations_um, strict=True):
        half = sizes_mm[chip]/2
        density = power_w[chip]/sizes_mm[chip].prod()
        for xy, sign in ((start.centre_um[chip], -1.), (destination, 1.)):
            centre = np.asarray(xy)/1000 + sheet.carrier_offset
            delta += sign*density*footprint(sheet.edges, centre-half, centre+half)
    return delta


def path_upper_k(start, move, sizes_mm, power_w, lateral_w_k, vertical_k_w):
    """Route each watt along a grid path. No field or cold-plate position is needed."""
    bound = 0.
    for chip, destination in zip(move.chips, move.destinations_um, strict=True):
        offset_mm = abs(np.asarray(destination)-start.centre_um[chip])/1000
        if np.any(offset_mm):
            # Translating any point in a uniform rectangle crosses at most this
            # many 1 mm edges. The area fraction caps a single cell's added watts.
            hops = np.ceil(offset_mm).sum()
            local_w = power_w[chip]*min(1., 1./sizes_mm[chip].prod())
            bound += power_w[chip]*hops/lateral_w_k + vertical_k_w*local_w
    return float(bound)


@dataclass(frozen=True)
class Transfer:
    bare_k: np.ndarray
    source_surface_k: np.ndarray
    added: np.ndarray


class InsulatedSheet:
    """Neumann reference for a uniform rectangular grid; edge conductance is in W/K."""

    def __init__(self, shape, lateral_w_k, vertical_k_w):
        if lateral_w_k <= 0 or vertical_k_w < 0:
            raise ValueError("need positive lateral conductance and nonnegative vertical resistance")
        self.vertical_k_w = vertical_k_w
        ey, ex = [4*lateral_w_k*np.sin(np.pi*np.arange(n)/(2*n))**2 for n in shape]
        eigenvalues = ey[:, None] + ex
        eigenvalues[0, 0] = 1
        self.inverse_modes = 1 / eigenvalues
        self.inverse_modes[0, 0] = 0  # The common temperature offset has no effect.

    def transfer(self, delta_w):
        if abs(delta_w.sum()) > 1e-12 * max(1., abs(delta_w).sum()):
            raise ValueError("a power transfer must conserve watts")
        bare = idctn(dctn(delta_w, norm="ortho") * self.inverse_modes, norm="ortho")
        surface = bare + self.vertical_k_w * delta_w
        return Transfer(bare, surface, np.flatnonzero(delta_w > 0))


@dataclass(frozen=True)
class GainWindow:
    rise_upper_k: float
    gain_low_k: float
    gain_high_k: float
    retained_cells: int


def joint_peak(initial_k, old_hot, changes, rise_upper_k, possible_sources):
    """Exact joint peak after excluding cells by headroom; changes are single-move fields."""
    lower_peak = initial_k.flat[old_hot] + sum(field.flat[old_hot] for field in changes)
    eligible = possible_sources & (initial_k >= lower_peak-rise_upper_k-1e-8)
    cells = np.flatnonzero(eligible)
    temperatures = initial_k.ravel()[cells].copy()
    for field in changes:
        temperatures += field.ravel()[cells]
    winner = int(temperatures.argmax())
    return float(temperatures[winner]), np.unravel_index(cells[winner], initial_k.shape), cells.size


class ThermalMargin:
    """A fixed starting field and the cells connected to a common ambient."""

    def __init__(self, initial_k, contact):
        self.initial = initial_k
        self.contact = np.flatnonzero(contact)
        if not self.contact.size:
            raise ValueError("need a nonempty cooled contact")
        self.old_hot = int(initial_k.argmax())
        self.peak = float(initial_k.flat[self.old_hot])

    def window(self, transfer, powered, plane=None):
        # The correction to the insulated copper field is a weighted average
        # of its contact values. Its weights are nonnegative and sum to one.
        contact_values = transfer.bare_k.ravel()[self.contact]
        surface = transfer.source_surface_k
        if plane is not None:
            contact_values, surface = plane.subtract(contact_values, surface)
        lo, hi = float(contact_values.min()), float(contact_values.max())
        highest = float(surface.ravel()[transfer.added].max()) if transfer.added.size else 0.
        rise_upper = max(0., highest-lo)
        # The old hotspot gives a lower bound on the final peak. A cooler cell
        # whose entire margin exceeds the largest possible rise cannot set it.
        witness = self.peak + surface.flat[self.old_hot] - hi
        retain = powered & (self.initial >= witness-rise_upper-1e-8)
        if not retain.any():
            raise ValueError("no powered cells remain for the peak-temperature bound")
        peak = float(np.max(self.initial[retain] + surface[retain]))
        return GainWindow(rise_upper, self.peak-peak+lo, self.peak-peak+hi, int(retain.sum()))


class ContactPlane:
    """Exact response of the cooled sheet to two coordinate fields on its contact."""

    def __init__(self, sheet):
        active = np.flatnonzero(sheet.sink)
        shape = (len(sheet.edges)-1,)*2
        self.xy = np.stack(np.unravel_index(active, shape), axis=1).astype(float)
        self.xy -= self.xy.mean(axis=0)
        self.slopes = np.linalg.pinv(self.xy)
        forcing = np.zeros((sheet.sink.size, 2))
        forcing[active] = sheet.sink[active, None] * self.xy
        self.response = sheet.factor.solve(forcing).reshape((*shape, 2))

    def subtract(self, values, surface):
        # The constant offset cancels in the bounds. Only two slopes need lifting.
        slopes = self.slopes @ values
        residual = values - self.xy @ slopes
        lifted = self.response[:, :, 0]*slopes[0] + self.response[:, :, 1]*slopes[1]
        return residual, surface-lifted
