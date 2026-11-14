"""Area-conservative deposition of uniform rectangular heat sources."""

import numpy as np

from .mesh import GEOMETRY_TOL_MM


def _on_edges(value, edges):
    """Use the mesh edge for a block edge within the geometry tolerance (same physical line)."""
    nearest = edges[int(np.argmin(abs(edges - value)))]
    return float(nearest) if abs(nearest - value) <= GEOMETRY_TOL_MM else value


def rasterize(case):
    xs, ys = np.asarray(case.mesh.x_edges_mm), np.asarray(case.mesh.y_edges_mm)
    power = np.zeros((case.ny, case.nx))
    records = []
    for die in case.dies:
        for block in die.blocks:
            rect = die.transform(block.rect)
            x0, x1 = _on_edges(rect.x, xs), _on_edges(rect.x + rect.width, xs)
            y0, y1 = _on_edges(rect.y, ys), _on_edges(rect.y + rect.height, ys)
            wx = np.maximum(0, np.minimum(xs[1:], x1) - np.maximum(xs[:-1], x0))
            wy = np.maximum(0, np.minimum(ys[1:], y1) - np.maximum(ys[:-1], y0))
            deposited = block.power_w * np.outer(wy, wx) / ((x1 - x0)*(y1 - y0))
            mapped = float(deposited.sum())
            if not np.isclose(mapped, block.power_w, rtol=1e-10, atol=1e-12):
                raise ValueError(f"power mapping failed for {die.id}/{block.id}")
            power += deposited
            records.append({"chiplet": die.id, "block": block.id, "input_w": block.power_w,
                            "mapped_w": mapped, "provenance": block.provenance,
                            "package_rect_mm": {"x": rect.x, "y": rect.y,
                                                "width": rect.width, "height": rect.height}})
    return power, records
