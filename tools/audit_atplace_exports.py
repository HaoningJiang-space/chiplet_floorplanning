"""Independently rescore ATPlace coordinates, including preserved exports after scoring failures."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from compare_atplace_margin import NAMES, write


def read(path):
    return json.loads(path.read_bytes())


def timed(script, *args):
    start = perf_counter()
    subprocess.run([sys.executable, str(Path(__file__).with_name(script)), *map(str, args)], check=True)
    return perf_counter() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.run.resolve()
    initial = read(root / "results.json")
    guarded = read(root / "guarded.json")
    tight = read(root / "tight-endpoints.json")
    replay_path = root / "unguarded-replay.json"
    replay = read(replay_path)["cases"] if replay_path.exists() else {}
    digest = hashlib.sha256((root / "results.json").read_bytes()).hexdigest()
    assert guarded["results_sha256"] == tight["results_sha256"] == digest
    audited = dict(seed=initial["seed"], upstream=initial["upstream"], results_sha256=digest, cases={})

    for name in NAMES:
        case = initial["cases"][name]
        src = root / name
        arms = {"margin": case["arms"]["margin"]}
        for key, directory, mode, original in (
            ("guarded", src/"guarded", "shared", guarded["cases"].get(name)),
            ("native", src, "native", case["arms"].get("native")),
            ("shared", src/"unguarded-replay" if name in replay else src,
             "shared", replay.get(name, case["arms"].get("shared"))),
        ):
            if not (directory / (mode + ".json")).exists():
                continue
            rescoring_s = timed("compare_atplace_margin.py", "assess", directory, mode)
            result = read(directory / (mode + "-evaluated.json"))
            if original is not None and "best_peak_c" in original:
                # Report the original complete wall time; separately log this independent replay.
                assert abs(result["best_peak_c"] - original["best_peak_c"]) < 1e-7
                assert abs(result["best_wire_m"] - original["best_wire_m"]) < 1e-9
                warm_s = original["warm_s"]
            else:
                # The placement had completed. Replace the failed terminal score only.
                warm_s = case["timings_s"][mode] + rescoring_s
            result.update(warm_s=warm_s, cold_total_s=warm_s + case["timings_s"]["train"],
                          audit_s=rescoring_s)
            arms[key] = result

        refinement = tight["cases"][name]
        native = arms.get("native")
        if "gain_k" not in refinement and native and native["candidates"][1]["feasible"]:
            extra = timed("refine_atplace_endpoint.py", src, "--worker")
            refinement = read(src / "tight.json")
            refinement.update(extra_s=extra, full_s=native["cold_total_s"] + extra)
        manifest = read(src/"input.json")
        sampled = {filename: hashlib.sha256((src/filename).read_bytes()).hexdigest()
                   for filename in ("sampled.npz","labels.npy","shared-fv.pt") if (src/filename).exists()}
        audited["cases"][name] = dict(arms=arms, native_refinement=refinement,
                                      training=case["training"], train_s=case["timings_s"]["train"],
                                      input=manifest, training_artifact_sha256=sampled)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(args.output, audited)


if __name__ == "__main__":
    main()
