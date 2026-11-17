"""Interposer-dependent package cost as a function of carrier size (plan: docs/sizing-placement-plan.md).

Only the parts that change with the interposer are counted (chiplet cost is placement-independent):
interposer = wafer price / (dies per wafer x yield), with a negative-binomial defect yield and one seam-yield factor
per stitch, plus the organic substrate under it. Defaults follow Chiplet Actuary (DAC'22 repo; the $1,937 wafer is
CSET's 65 nm foundry price); see docs/interposer-cost-data.md for sources and the sensitivity ranges.
"""
import math
from dataclasses import dataclass

RETICLE_MM = (26.0, 33.0)
RETICLE_MM2 = RETICLE_MM[0]*RETICLE_MM[1]


@dataclass(frozen=True)
class CostParams:
    wafer_usd: float = 1937.0          # passive silicon interposer wafer
    d0_per_cm2: float = 0.06
    cluster: float = 6.0
    seam_yield: float = 0.99           # per stitch; no public value, swept
    stitch_limit: float = 3.3          # CoWoS-S class: stitched silicon up to this many reticles
    # Beyond it an RDL interposer with local bridges (CoWoS-L class) is only a cost scenario: the FV model has
    # no RDL/bridge stack, so it is off unless asked for (review of b50044e).
    allow_rdl: bool = False
    rdl_wafer_usd: float = 1200.0
    rdl_d0_per_cm2: float = 0.05
    rdl_cluster: float = 3.0
    rdl_limit: float = 5.5
    substrate_usd_mm2: float = 0.005
    substrate_ratio: float = 2.0       # substrate area / interposer area (declared assumption)
    wafer_mm: float = 300.0


def dies_per_wafer(area_mm2, wafer_mm=300.0):
    return math.pi*(wafer_mm/2)**2/area_mm2 - math.pi*wafer_mm/math.sqrt(2*area_mm2)


def defect_yield(area_mm2, d0_per_cm2, cluster):
    """Negative binomial: (1 + D0 A / c)^-c with A in cm^2."""
    return (1 + d0_per_cm2*area_mm2/100/cluster)**(-cluster)


def substrate_factor(side_mm):
    """Chiplet Actuary's organic-substrate size tiers (<=17, <=30, >30 mm side)."""
    return 1.5 if side_mm <= 17 else 1.75 if side_mm <= 30 else 2.0


def option(width_mm, height_mm, params=CostParams()):
    """('single' | 'stitched' | 'rdl_bridge' | None, exposure fields k)."""
    area = width_mm*height_mm
    if min(width_mm, height_mm) <= RETICLE_MM[0] and max(width_mm, height_mm) <= RETICLE_MM[1]:
        return 'single', 1
    if area <= params.stitch_limit*RETICLE_MM2:
        # Stitching joins whole exposure fields: count the fields that tile the interposer, either orientation.
        fields = min(math.ceil(width_mm/a)*math.ceil(height_mm/b) for a, b in (RETICLE_MM, RETICLE_MM[::-1]))
        return 'stitched', fields
    if params.allow_rdl and area <= params.rdl_limit*RETICLE_MM2:
        return 'rdl_bridge', 1
    return None, 0


def interposer_cost(width_mm, height_mm, params=CostParams()):
    """Cost breakdown (USD) of a width x height interposer and its substrate; total is inf if no option fits."""
    area = width_mm*height_mm
    kind, k = option(width_mm, height_mm, params)
    if kind is None:
        return dict(option=None, fields=0, yield_=0.0, total_usd=math.inf)
    if kind == 'rdl_bridge':
        wafer, y = params.rdl_wafer_usd, defect_yield(area, params.rdl_d0_per_cm2, params.rdl_cluster)
    else:
        wafer = params.wafer_usd
        y = defect_yield(area, params.d0_per_cm2, params.cluster)*params.seam_yield**(k - 1)
    dpw = dies_per_wafer(area, params.wafer_mm)
    interposer = wafer/(dpw*y)
    sub_area = params.substrate_ratio*area
    substrate = params.substrate_usd_mm2*substrate_factor(math.sqrt(sub_area))*sub_area
    return dict(option=kind, fields=k, yield_=y, dies_per_wafer=dpw, interposer_usd=interposer,
                substrate_usd=substrate, total_usd=interposer + substrate)
