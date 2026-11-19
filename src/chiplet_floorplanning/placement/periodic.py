"""Periodic thermal response of a passive RC package to equal-duration binary tasks."""
from itertools import combinations

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu


def quota_orders(slots, count):
    """One representative of each cyclic rotation; complementary tasks stay distinct."""
    if slots < 1 or not 0 <= count <= slots:
        raise ValueError("expected a feasible number of tasks")
    orders = set()
    for positions in combinations(range(slots), count):
        bits = "".join("1" if i in positions else "0" for i in range(slots))
        orders.add(min(bits[i:] + bits[:i] for i in range(slots)))
    return sorted(orders)


def balanced_orders(slots):
    if slots < 2 or slots % 2:
        raise ValueError("expected a positive even number of slots")
    return quota_orders(slots, slots//2)


def periodic_pulse(g, capacity, powers, slot_s, substeps, slots):
    """Return the all-zero-mode steady rise and the phase-by-node response to
    replacing slot zero by mode one in every period. Each row is a substep end.
    The Fourier solve enforces the wrap-around condition of backward Euler.
    """
    if slot_s <= 0 or substeps < 1 or slots < 1 or powers.shape != (g.shape[0], 2):
        raise ValueError("expected two power columns and positive slot length, substeps and slots")
    steps = slots * substeps
    waveform = np.zeros(steps)
    waveform[:substeps] = 1
    coeff = np.fft.rfft(waveform)
    phase = 2 * np.pi * np.arange(len(coeff)) / steps
    contrast = powers[:, 1] - powers[:, 0]
    steady = splu(g.tocsc(), permc_spec="MMD_AT_PLUS_A").solve(powers)
    spectrum = np.zeros((len(coeff), g.shape[0]), complex)
    spectrum[0] = coeff[0] * (steady[:, 1] - steady[:, 0])
    for k in range(1, len(coeff)):
        if abs(coeff[k]) < 1e-12:
            continue
        shift = (1 - np.exp(-1j * phase[k])) * substeps / slot_s
        matrix = (g + diags(shift * capacity)).tocsc()
        spectrum[k] = coeff[k] * splu(matrix, permc_spec="MMD_AT_PLUS_A").solve(contrast)
    return steady, np.fft.irfft(spectrum, n=steps, axis=0)


def cycle_trace(base, pulse, order):
    """Spatial field at all recorded phases for a specified repeated order."""
    if not order or len(pulse) % len(order) or set(order) - {"0", "1"}:
        raise ValueError("expected a binary order aligned with the sampled period")
    stride = len(pulse) // len(order)
    trace = np.zeros_like(pulse, dtype=float)
    for i, task in enumerate(order):
        if task == "1":
            trace += np.roll(pulse, i * stride, axis=0)
    return base + trace


def quota_peak(base, pulse, slots, count):
    """Worst observed temperature over all orders with exactly count ones.

    At a fixed cell and phase, any chosen slot contributes its signed pulse.
    Taking the largest count contributions realizes the maximum at that point.
    Cyclic rotation means only the phases of one slot need to be examined.
    """
    if not 0 <= count <= slots or slots < 1 or len(pulse) % slots:
        raise ValueError("expected a feasible task count and an aligned period")
    stride = len(pulse) // slots
    lags = np.stack([np.roll(pulse, i * stride, axis=0)[:stride] for i in range(slots)])
    largest = np.sort(lags, axis=0)[slots-count:]
    return float((base + largest.sum(axis=0)).max())


def response_peak_bounds(mean, lows, highs):
    """Bound the cycle peak from separate sources' spatial response ranges.

    mean is a spatial temperature field. Each row in lows and highs contains
    one source's minimum and maximum zero-mean temperature excursion per cell
    over the same periodic cycle. No relative phase information is required.
    """
    mean, lows, highs = (np.asarray(v, dtype=float) for v in (mean, lows, highs))
    if lows.shape != highs.shape or lows.ndim != mean.ndim + 1 or not lows.size or lows.shape[1:] != mean.shape:
        raise ValueError("each source must give both extrema on the mean temperature grid")
    # At the time any source reaches its high, others are at least at their lows.
    guaranteed = lows.sum(axis=0) + (highs-lows).max(axis=0)
    lower = mean + np.maximum(0., guaranteed)
    upper = mean + highs.sum(axis=0)
    return float(lower.max()), float(upper.max())
