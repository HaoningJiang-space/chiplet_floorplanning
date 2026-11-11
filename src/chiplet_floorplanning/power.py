"""Area-conservative deposition of uniform rectangular heat sources."""

import numpy as np


def rasterize(case):
    xs, ys = np.asarray(case.mesh.x_edges_mm), np.asarray(case.mesh.y_edges_mm)
    power = np.zeros((case.ny, case.nx))
    records = []
    for die in case.dies:
        for block in die.blocks:
            rect = die.transform(block.rect)
            wx = np.maximum(0, np.minimum(xs[1:], rect.x + rect.width) - np.maximum(xs[:-1], rect.x))
            wy = np.maximum(0, np.minimum(ys[1:], rect.y + rect.height) - np.maximum(ys[:-1], rect.y))
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
