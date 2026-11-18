"""Run the equal-bandwidth Case3 experiment in two reproducible stages."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np

from case3_phy_geometry import (
    CAP_M,
    PROFILES,
    BundleLengths,
    candidate_geometries,
    direct_check,
    heat_score,
    memory_states,
    select_ports,
    sizes_mm,
)
from case3_wire_witness import thermal_key
from chiplet_floorplanning.placement import Problem
from compare_wire_heat import digest
from wire_heat_bound import thermal_modes

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence"
STATE = {}


def inputs(data):
    prior = json.loads((EVIDENCE / "case3-ring-certificate-v1.json").read_text())
    source = data / "physical-calibration/atplace-import-v1/Case3.json"
    archive = data / "rs-grb-v4/case3/layouts.npz"
    witness = data / "case3-ring-aa12f7d-release/witness/layouts.json"
    assert (
        digest(source) == prior["case_sha256"]
        and digest(archive) == prior["archive_sha256"]["layouts.npz"]
    )
    assert digest(witness) == prior["raw_sha256"]["witness/layouts.json"]
    return Problem.from_imported(json.loads(source.read_text())), archive, witness


def setup_geometry(p, cert):
    radii, weights = thermal_modes(cert)
    STATE.update(
        p=p,
        costs=BundleLengths(p),
        radii=radii,
        weights=weights,
        self_k=np.array([d["self_floor_k"] for d in cert["dies"]]),
    )


def screen(row):
    p = STATE["p"]
    centres = np.array(row["centres_um"]) / 1000
    size = sizes_mm(p, row["parity"])
    mem, turns = memory_states(centres, row["parity"], STATE["costs"])
    row["score"] = heat_score(
        centres, size, p.power_w, STATE["radii"], STATE["weights"], STATE["self_k"]
    )
    row["profiles"] = {
        name: select_ports(centres, size, mem, turns, profile)
        for name, profile in PROFILES.items()
    }
    return row


def select_ids(rows, p):
    selected = {}
    for name in PROFILES:
        valid = [
            r
            for r in rows
            if r["profiles"][name]
            and r["profiles"][name]["wire_m"] <= CAP_M
            and r["profiles"][name]["latency_ns"] <= 5
        ]
        known = [r for r in valid if r["base_c"] is not None]
        by_wire = lambda r: r["profiles"][name]["wire_m"]
        orders = [
            (sorted(known, key=lambda r: (r["base_c"], by_wire(r))), 12),
            (sorted(valid, key=lambda r: (r["score"], by_wire(r))), 24),
            (sorted(valid, key=lambda r: (by_wire(r), r["score"])), 4),
        ]
        keep, geometries = [], set()
        for ordered, count in orders:
            n = 0
            for row in ordered:
                key = thermal_key(
                    np.array(row["centres_um"]) / 1000,
                    sizes_mm(p, row["parity"]),
                    p.power_w,
                    np.array(p.carrier_um) / 1000,
                )
                if key in geometries:
                    continue
                keep.append(row["id"])
                geometries.add(key)
                n += 1
                if n == count:
                    break
        selected[name] = keep
    return selected


def geometry(args):
    p, arch, wit = inputs(args.data)
    cert = next(
        r["certificate"]
        for r in json.loads((EVIDENCE / "global-heat-floor-v1.json").read_text())[
            "cases"
        ]
        if r["certificate"]["case"] == "Case3"
    )
    with np.load(arch) as archive:
        rows = candidate_geometries(p, archive, json.loads(wit.read_text()))
    print("distinct geometries", len(rows), flush=True)
    with ProcessPoolExecutor(
        args.workers, initializer=setup_geometry, initargs=(p, cert)
    ) as pool:
        rows = list(pool.map(screen, rows, chunksize=16))
    selected = select_ids(rows, p)
    selected_union = {i for group in selected.values() for i in group} | {"reference"}
    for row in rows:
        if row["id"] in selected_union:
            for name, config in row["profiles"].items():
                if config:
                    direct_check(p, np.array(row["centres_um"]), config, PROFILES[name])
    counts = {}
    for name in PROFILES:
        configs = [r["profiles"][name] for r in rows if r["profiles"][name]]
        counts[name] = dict(
            reach=len(configs),
            wire_and_delay=sum(
                c["wire_m"] <= CAP_M and c["latency_ns"] <= 5 for c in configs
            ),
        )
    return dict(
        case_sha256=cert["case_sha256"],
        source_counts=dict(archive=931, prior=52),
        distinct=len(rows),
        counts=counts,
        selected=selected,
        rows=rows,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["geometry", "thermal"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a fresh output file")
    if args.stage == "geometry":
        result = geometry(args)
    else:
        from case3_phy_thermal import thermal

        if args.geometry is None:
            parser.error("thermal needs --geometry from the geometry stage")
        result = thermal(args, inputs(args.data)[0])
    result["source_sha256"] = {
        p.name: digest(p) for p in Path(__file__).parent.glob("case3_phy_*.py")
    }
    args.output.write_text(json.dumps(result, allow_nan=False) + "\n")
    print("complete", args.stage, args.output, flush=True)


if __name__ == "__main__":
    main()
