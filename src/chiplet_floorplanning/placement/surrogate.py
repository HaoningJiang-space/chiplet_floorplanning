"""Translation-invariant superposition surrogate for the declared FV package.

Physics: with fixed materials the FV system A theta = b is linear in b, so the
rise is a sum of single-source responses. Moving chiplets also moves their
high-conductivity islands (A changes) and the carrier edge breaks translation
invariance; this surrogate ignores both. Its error must be measured against
exact FV solves before it guides any search, and final layouts are always
re-evaluated with FV.
"""
import numpy as np

from .problem import Layout, Problem
from .thermal import AMBIENT_C, solve, thermal_case_data

PACKAGE_MM = 200.0
MAX_CARRIER_MM = 100.0


class Superposition:
    def __init__(self, problem, gap_um, resolution=96, sample_mm=0.25):
        self.problem = problem
        width, height = (s/1000 for s in problem.carrier_um)
        # A kernel centred on a doubled carrier covers every shift inside the real carrier.
        # The declared spreader is 100 mm, so larger carriers cannot be covered: refuse
        # rather than truncate the kernel.
        kw, kh = 2*width, 2*height
        if max(kw, kh) > MAX_CARRIER_MM:
            raise ValueError(f"superposition kernel needs a {kw:g}x{kh:g} mm carrier; "
                             f"the declared package supports at most {MAX_CARRIER_MM:g} mm")
        self.kernels = {}
        for k in range(problem.count):
            for turn in (0, 90):
                single = Problem(name=f"{problem.name}_kernel_{k}_{turn}", names=(problem.names[k],),
                                 size_um=problem.size_um[k:k+1], power_w=problem.power_w[k:k+1],
                                 carrier_um=(kw*1000, kh*1000), pin_chip=np.zeros((0, 2), int),
                                 pin_offset_um=np.zeros((0, 2, 2)))
                layout = Layout(np.array([[kw*500, kh*500]]), np.array([turn]))
                summary, rise, edges = solve(thermal_case_data(single, layout, gap_um, resolution))
                self.kernels[k, turn] = (rise, edges)
        xs = np.arange(sample_mm/2, width, sample_mm)
        ys = np.arange(sample_mm/2, height, sample_mm)
        self.points = np.stack(np.meshgrid(xs, ys, indexing="ij"), -1).reshape(-1, 2)  # carrier mm

    def rise_k(self, layout):
        total = np.zeros(len(self.points))
        for k in range(self.problem.count):
            rise, (ex, ey) = self.kernels[k, int(layout.rotation_deg[k]) % 180]
            # Kernel source sits at the package centre; shift sample points accordingly.
            local = self.points - layout.centre_um[k]/1000 + PACKAGE_MM/2
            ix = np.clip(np.searchsorted(ex, local[:, 0]) - 1, 0, rise.shape[1] - 1)
            iy = np.clip(np.searchsorted(ey, local[:, 1]) - 1, 0, rise.shape[0] - 1)
            total += rise[iy, ix]
        if not np.isfinite(total).all():
            raise ValueError("query outside the kernel's power layer")
        return total

    def peak_c(self, layout):
        return float(self.rise_k(layout).max() + AMBIENT_C)
