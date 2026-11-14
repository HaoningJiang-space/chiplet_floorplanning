"""Production placement core: array problem, geometry, pin length and FV evaluation."""
from .geometry import boxes, centre_manhattan_um, is_legal, pin_manhattan_um, violations
from .problem import Layout, Problem
from .thermal import solve_peak, thermal_case_data
