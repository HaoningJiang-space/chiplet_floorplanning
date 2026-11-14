"""Array form of an imported rectangular two-pin chiplet placement case.

Lengths are micrometres (um) unless a name says otherwise; power is W.
Pin offsets are relative to the chiplet centre in its unrotated frame.
"""
from dataclasses import dataclass

import numpy as np

ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Problem:
    name: str
    names: tuple
    size_um: np.ndarray        # (n, 2) unrotated width, height
    power_w: np.ndarray        # (n,)
    carrier_um: tuple          # (width, height)
    pin_chip: np.ndarray       # (m, 2) chiplet index of each net endpoint
    pin_offset_um: np.ndarray  # (m, 2, 2) unrotated endpoint offsets

    @classmethod
    def from_imported(cls, case):
        """Build from tools/import_atplace_cases.py output; two-pin nets only."""
        names = tuple(c["name"] for c in case["chiplets"])
        index = {name: i for i, name in enumerate(names)}
        if len(index) != len(names):
            raise ValueError("duplicate chiplet name")
        if any(len(net["pins"]) != 2 for net in case["nets"]):
            raise ValueError("only two-pin nets supported")
        pin_chip = np.array([[index[p["chiplet"]] for p in net["pins"]] for net in case["nets"]], dtype=int)
        offsets = np.array([[[float(p["offset_x_um_decimal"]), float(p["offset_y_um_decimal"])]
                             for p in net["pins"]] for net in case["nets"]], dtype=float)
        return cls(
            name=case["name"], names=names,
            size_um=np.array([[c["width_um"], c["height_um"]] for c in case["chiplets"]], dtype=float),
            power_w=np.array([float(c["power_w_decimal"]) for c in case["chiplets"]]),
            carrier_um=(float(case["interposer_width_um"]), float(case["interposer_height_um"])),
            pin_chip=pin_chip.reshape(-1, 2), pin_offset_um=offsets.reshape(-1, 2, 2))

    @property
    def count(self):
        return len(self.names)


@dataclass(frozen=True)
class Layout:
    centre_um: np.ndarray  # (n, 2)
    rotation_deg: np.ndarray  # (n,) counterclockwise quarter turns

    @classmethod
    def from_placements(cls, problem, placements):
        """Convert the legacy list-of-dicts form; every chiplet exactly once."""
        poses = {p["chiplet"]: p for p in placements}
        if len(poses) != len(placements) or set(poses) != set(problem.names):
            raise ValueError("placement must contain each source chiplet exactly once")
        raw = [poses[n]["rotation_deg"] for n in problem.names]
        # Validate before any conversion so e.g. 90.9 is rejected, not truncated to 90.
        if any(type(r) is not int or r not in ROTATIONS for r in raw):
            raise ValueError("only integer quarter turns supported")
        rotation = np.array(raw, dtype=int)
        centre = np.array([[poses[n]["centre_x_um"], poses[n]["centre_y_um"]] for n in problem.names], dtype=float)
        if not np.isfinite(centre).all():
            raise ValueError("nonfinite centre")
        return cls(centre, rotation)

    def to_placements(self, problem):
        return [dict(chiplet=n, centre_x_um=float(c[0]), centre_y_um=float(c[1]), rotation_deg=int(r))
                for n, c, r in zip(problem.names, self.centre_um, self.rotation_deg)]
