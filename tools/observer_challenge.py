"""Look outside the frozen 24-candidate search budget without reranking its results."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.common_move import HotspotResponse
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.search import rotated_size
from common_relocation import CENTRES, FOUR, ORIGINAL, TARGET, audit, freeze_action
from direct_relocation import rebuild
from observer_placement import joint_bank
from power_uncertainty import cases, text_digest


def key(action):
    return tuple(zip(action["indices"], map(tuple, action["to_um"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    bank = json.loads(args.bank.read_bytes())
    assert bank["anchor_sha256"] == text_digest(ORIGINAL)
    report = dict(bank_sha256=text_digest(args.bank), cases={})
    if args.audit:
        frozen = json.loads(args.audit.read_bytes())
        assert frozen["bank_sha256"] == report["bank_sha256"]
        report["challenge_sha256"] = text_digest(args.audit)
    best_extra_gain = TARGET
    best_package = None
    anchors = json.loads(ORIGINAL.read_bytes())["cases"]
    for (p, designs, meta), anchor in zip(cases(args.cases), anchors, strict=True):
        index, start, cap = min(designs, key=lambda d: d[0])
        assert p.name == anchor["name"] and index == anchor["anchor_id"] and meta["bank_sha256"] == anchor["bank_sha256"]
        np.testing.assert_array_equal(start.centre_um, anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg, anchor["rotation_deg"])
        p = replace(p, power_w=bank["power_fraction"]*p.power_w)
        original = bank["cases"][p.name]
        excluded = {key(a) for a in original["candidates"]}
        sheets = [CooledSheet(p, np.asarray(CENTRES[b])) for b in FOUR]
        base = sheets[0].power_map(start)
        fields = [sheet.temperatures(base) for sheet in sheets]
        if not args.audit:
            rows = [HotspotResponse.at_cell(sh, field, np.unravel_index(field.argmax(), field.shape))
                    for sh, field in zip(sheets, fields)]
            moves, bounds, _ = joint_bank(p, start, cap, meta, rows, rotated_size(p, start.rotation_deg)/1000,
                                          outside=True)
            result = [dict(**freeze_action(move, start, p), old_bound_k=float(bound))
                      for move, bound in zip(moves[1:], bounds[1:])]
            assert not (excluded & {key(a) for a in result})
            report["cases"][p.name] = result
            continue
        endpoint = frozen["cases"][p.name]
        gains = []
        for action in endpoint:
            assert key(action) not in excluded
            watts = sheets[0].power_map(rebuild(start, action))
            gain = min(float(field.max()-sh.temperatures(watts).max()) for sh, field in zip(sheets, fields))
            assert gain <= action["old_bound_k"]+1e-8
            gains.append(gain)
        best = min(range(len(gains)), key=lambda i: (-gains[i], endpoint[i]["cost"], i)) if gains else None
        ref = original["methods"]["full"]
        improvement = gains[best]-ref["estimated_raw_k"] if gains else None
        executable = max(0., gains[best]-ref["actual_gain_k"]) if gains and gains[best]>TARGET else 0.
        report["cases"][p.name] = dict(gains_k=gains, best=best, improvement_over_raw_k=improvement,
                                       executable_extra_gain_k=executable)
        if executable > best_extra_gain:
            best_extra_gain = executable
            best_package = (p, start, cap, meta, dict(actions=dict(
                original=original["candidates"][ref["selected"]], extra=endpoint[best])))
    if args.audit and best_package:
        report["package_case"] = best_package[0].name
        report["package"] = audit(*best_package, grid=64)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
