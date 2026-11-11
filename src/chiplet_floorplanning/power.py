"""Area-conservative deposition of uniform rectangular heat sources."""

import numpy as np


def rasterize(case):
    dx, dy = case.package.width / case.nx, case.package.height / case.ny
    xs, ys = np.arange(case.nx) * dx, np.arange(case.ny) * dy
    power = np.zeros((case.ny, case.nx))
    records = []
    for die in case.dies:
        for block in die.blocks:
            rect = die.transform(block.rect)
            wx = np.maximum(0, np.minimum(xs + dx, rect.x + rect.width) - np.maximum(xs, rect.x))
            wy = np.maximum(0, np.minimum(ys + dy, rect.y + rect.height) - np.maximum(ys, rect.y))
            deposited = block.power_w * np.outer(wy, wx) / rect.area
            mapped = float(deposited.sum())
            if not np.isclose(mapped, block.power_w, rtol=1e-10, atol=1e-12):
                raise ValueError(f"power mapping failed for {die.id}/{block.id}")
            power += deposited
            records.append({"chiplet": die.id, "block": block.id, "input_w": block.power_w,
                            "mapped_w": mapped, "provenance": block.provenance,
                            "package_rect_mm": {"x": rect.x, "y": rect.y,
                                                "width": rect.width, "height": rect.height}})
    return power, records
