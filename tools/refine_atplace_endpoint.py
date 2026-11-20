"""Test joint placement at the actual wirelength of a native-start ATPlace endpoint."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement.problem import Layout
from compare_atplace_margin import NAMES, candidate, margin_candidates, problem_at, write


def refine(sub):
    _, p, _ = problem_at(sub)
    record = json.loads((sub/"native-evaluated.json").read_bytes())["candidates"][1]
    if not record["feasible"]:
        raise ValueError("native endpoint outside the original physical domain")
    start = Layout(np.array(record["centre_um"]),np.array(record["rotation_deg"]))
    cap = record["wire_m"]
    rows = [candidate(p,start,cap)]
    assert abs(rows[0]["peak_c"]-record["peak_c"]) < 1e-7
    rows.extend(candidate(p,lay,cap) for lay in margin_candidates(p,start,cap))
    selected = min((r for r in rows if r["feasible"]),key=lambda r:(r["peak_c"],r["wire_m"]))
    write(sub/"tight.json",dict(cap_m=cap,atplace_peak_c=rows[0]["peak_c"],
          selected_peak_c=selected["peak_c"],selected_wire_m=selected["wire_m"],
          gain_k=rows[0]["peak_c"]-selected["peak_c"],records=rows))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run",type=Path)
    ap.add_argument("--worker",action="store_true")
    ap.add_argument("--upstream",type=Path)
    ap.add_argument("--atpython",type=Path)
    args=ap.parse_args()
    root=args.run.resolve()
    if args.worker:
        refine(root)
        return
    raw=(root/"results.json").read_bytes()
    evidence=json.loads(raw)
    out=dict(results_sha256=hashlib.sha256(raw).hexdigest(),cases={})
    guarded=dict(results_sha256=out["results_sha256"],cases={})
    recovered=dict(results_sha256=out["results_sha256"],cases={})
    for name in NAMES:
        row=evidence["cases"][name]
        if args.upstream and args.atpython and row["training"]:
            src=root/name
            modes=[("guarded",guarded,["--export-guard"])]
            if "shared" not in row["arms"]:
                modes.append(("unguarded-replay",recovered,[]))
            for mode,summary,flags in modes:
                dest=src/mode
                dest.mkdir(exist_ok=True)
                for filename in ("input.json","source.json","shared-fv.pt"):
                    shutil.copyfile(src/filename,dest/filename)
                then=perf_counter()
                with (dest/"run.log").open("w",encoding="utf8") as log:
                    used=subprocess.run([str(args.atpython.resolve()),str(Path(__file__).with_name("atplace_shared_fv.py")),
                        str(args.upstream.resolve()),str(dest),"shared",sys.executable,*flags],
                        stdout=log,stderr=subprocess.STDOUT)
                if used.returncode:
                    summary["cases"][name]=dict(failed=(dest/"run.log").read_text(encoding="utf8",errors="replace").splitlines()[-1])
                else:
                    subprocess.run([sys.executable,str(Path(__file__).with_name("compare_atplace_margin.py")),
                        "assess",str(dest),"shared"],check=True)
                    seconds=perf_counter()-then
                    data=json.loads((dest/"shared-evaluated.json").read_bytes())
                    data.update(warm_s=seconds,cold_total_s=seconds+row["timings_s"]["train"])
                    summary["cases"][name]=data
                write(root/(mode+".json"),summary)
        native=row["arms"].get("native")
        if native is None or not native["candidates"][1]["feasible"]:
            out["cases"][name]=dict(status="no admissible native endpoint")
            continue
        then=perf_counter()
        sub=root/name
        subprocess.run([sys.executable,__file__,str(sub),"--worker"],check=True)
        elapsed=perf_counter()-then
        data=json.loads((sub/"tight.json").read_bytes())
        data.update(extra_s=elapsed,full_s=native["cold_total_s"]+elapsed)
        out["cases"][name]=data
    write(root/"tight-endpoints.json",out)


if __name__=="__main__":
    main()
