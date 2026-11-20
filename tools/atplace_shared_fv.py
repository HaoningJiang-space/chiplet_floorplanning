"""Run the pinned upstream thermal trainer and optimizer with common 3D FV labels (Python 3.9)."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("upstream", type=Path)
    ap.add_argument("case_dir", type=Path)
    ap.add_argument("stage", choices=["train", "shared", "native"])
    ap.add_argument("project_python")
    ap.add_argument("--export-guard",action="store_true",
                    help="Reserve CBC text and float32 coordinate precision inside the same physical cap.")
    ap.add_argument("--projected-labels", action="store_true")
    ap.add_argument("--native-limit-s", type=float, default=10.)
    args = ap.parse_args()
    upstream, out = args.upstream.resolve(), args.case_dir.resolve()
    sys.path.insert(0, str(upstream))
    from src.opt import cli, place_flow
    from src.thermal import checkpoint, training
    import numpy as np
    import pulp
    import torch

    os.environ["OMP_NUM_THREADS"] = "1"
    torch.set_num_threads(1)
    # The packaged Windows CBC hangs with one parallel worker on a sample
    # that serial CBC solves in 0.15 s. Zero selects its single-thread engine.
    if os.name == "nt":
        cbc = pulp.PULP_CBC_CMD
        def serial_cbc(*args, **kwargs):
            kwargs["threads"] = 0
            return cbc(*args, **kwargs)
        pulp.PULP_CBC_CMD = serial_cbc
    case = json.loads((out/"input.json").read_bytes())
    name = case["name"]
    params = cli.load_params(upstream/"cases"/name/"Thermal-aware.json", name, out, mode="thermal")
    params.num_threads = params.thermal_num_threads = 1
    params.ilp_solver = "pulp"
    params.training_seed = params.random_seed = 20261119
    params.training_iterations = 100
    params.training_sampling_time_limit_s = 10
    params.initialization_time_limit_s = params.legalization_time_limit_s = args.native_limit_s
    params.dis_bet_chips = 100.05  # 50 nm numerical allowance for float32/CBC coordinate export.
    params.floorplan_stages[0]["iteration"] = params.iteration = 10
    params.thermal_model = str(out/"shared-fv.pt")
    system = cli.build_system(Path(params.case_dir), name, params)
    data_names = list(system.node_names[:system.num_chiplets])
    assert set(data_names) == set(case["names"])
    order = [case["names"].index(n) for n in data_names]
    np.testing.assert_allclose(system.powermap, np.array(case["powers_w"])[order])

    # Persist the actual label generator's identity. Upstream verifies this metadata on load.
    signature = dict(case=name, source=case["source_sha256"], names=data_names,
                     powers_w=system.powermap.tolist(), grid=[params.num_grid_x, params.num_grid_y],
                     evaluator=case["fv_fingerprint"], ambient_c=45, upstream=case["upstream"])
    if args.projected_labels:
        signature['labels'] = 'geometry-specific FV Galerkin, 4 mm blocks'
    checkpoint.metadata = training.metadata = lambda params, system: signature
    if args.stage == "train":
        rng = np.random.default_rng(params.training_seed)
        try:
            geo = np.stack([training.sample_layout(system, params, rng) for _ in range(5)])
            sample_method = 'author'
        except RuntimeError:
            if not args.projected_labels:
                raise
            driver = Path(__file__).with_name("continuous_atplace_reference.py")
            subprocess.run([args.project_python,str(driver),"sample",str(out)],check=True)
            sample = np.load(out/"fallback-samples.npz")
            reorder = [sample['names'].tolist().index(n) for n in data_names]
            geo = sample['geometry'][:,reorder]
            sample_method = 'constructive legal sampler after native sampling timeout'
        np.savez(out/"sampled.npz", geometry=geo, names=np.array(data_names), grid=signature["grid"])
        driver = Path(__file__).with_name("continuous_atplace_reference.py" if args.projected_labels
                                          else "compare_atplace_margin.py").resolve()
        subprocess.run([args.project_python, str(driver), "labels", str(out)], check=True)
        saved = dict(metadata=signature, geometry=torch.from_numpy(geo),
                     power=torch.tensor(system.powermap, dtype=torch.float32).repeat(5,1),
                     temperature_rise=torch.from_numpy(np.load(out/"labels.npy")).float().unsqueeze(1),
                     train_samples=4, test_samples=1, seed=params.training_seed)
        report = training.fit_model(saved, params, system, params.thermal_model, out)
        model = checkpoint.load_model(params.thermal_model, params, system)
        with torch.no_grad():
            inputs = tuple(saved["geometry"][:,:,k] for k in range(4)) + (saved["power"],)
            peaks = model(inputs).flatten(1).max(1).values.numpy()
        labels = saved["temperature_rise"].flatten(1).max(1).values.numpy()
        stats = dict(fit_s=report["runtime_s"], test_mae_k=report["test_mae_c"],
                     heldout_sampled_peak_error_k=float(peaks[-1]-labels[-1]),
                     labels=5, torch=torch.__version__, pulp=pulp.__version__)
        if args.projected_labels:
            stats['sample_method'] = sample_method
        (out/"training.json").write_text(json.dumps(stats), encoding="utf8")
        return

    if args.stage == "shared":
        def shared_initial(*args, **kwargs):
            xy = np.asarray(case["start_um"])[order]
            return [xy.T.copy(), np.deg2rad(np.asarray(case["angles"])[order])]
        place_flow.Init_woflip_pulp = shared_initial

        # The native weighted legalizer already defines two per-net HPWL epigraphs.
        # Give its weighted solve the same hard cap as the competing generator.
        original = pulp.LpProblem.solve
        def solve_with_cap(problem, *solver_args, **kwargs):
            if problem.name == "legalization":
                h = [v for v in problem.variables() if v.name.startswith(("hpwl_x_", "hpwl_y_"))]
                if h:
                    # Two endpoints and two coordinates per net. One float32
                    # spacing plus 0.01 um for the CBC text representation.
                    precision = np.spacing(np.float32(max(system.intp_width,system.intp_height)))+.01
                    guard_um = 4*len(system.net2pin_map)*precision if args.export_guard else 0.
                    problem += pulp.lpSum(h) <= case["cap_m"]*1e6-guard_um
            return original(problem, *solver_args, **kwargs)
        pulp.LpProblem.solve = solve_with_cap
    then = perf_counter()
    if args.projected_labels and args.stage in ('native','shared'):
        # Reuse the native solver's own continuous result when only its terminal
        # MILP timed out. All positions, angles, weights and source pins remain its inputs.
        model_id = sha256(Path(params.thermal_model).read_bytes()).hexdigest()
        saved = out/(args.stage+'-before-legalization-'+model_id+'.npz')
        legalize = place_flow.Legalization
        if args.stage=='native' and args.native_limit_s > 10 and saved.exists():
            prior = np.load(saved)
            system.node_orient = prior['orient']
            target = [[prior['x'],prior['y']]]
            size = [prior['size_x'],prior['size_y']]
            final = None
            for weight in (params.wl_weight,0):
                final = legalize(system,params.ilp_solver,weight,target,size,TimeLimit=args.native_limit_s,
                                 num_threads=params.num_threads,random_seed=params.random_seed)
                if final is not None:
                    break
            if final is None:
                raise RuntimeError('native terminal legalization returned no feasible layout')
            n = system.num_chiplets
            xy = np.zeros((2,system.num_nodes))
            xy[:,:n] = final[:,:n]
            layout = cli.export_layout([xy.ravel().tolist(),system.node_orient.tolist()],system,params,name,'thermal')
            (out/'native.json').write_text(json.dumps(dict(chiplets=layout['chiplets'],
                optimizer_s=perf_counter()-then,terminal_replay=True)),encoding='utf8')
            return
        def record_target(sys_data, solver, weight, pos, size, **kwargs):
            if weight:
                np.savez(saved,orient=sys_data.node_orient,x=pos[0][0],y=pos[0][1],
                         size_x=size[0],size_y=size[1])
            return legalize(sys_data,solver,weight,pos,size,**kwargs)
        place_flow.Legalization = record_target
    model = cli.build_compact_model(params, system)
    result = cli.placeflow_core(params, system, model)
    hpwl, best = cli.unpack_result(result)
    layout = cli.export_layout(best, system, params, name, "thermal")
    (out/(args.stage+".json")).write_text(json.dumps(dict(
        chiplets=layout["chiplets"], source_wire_m=float(hpwl)/1e6,
        optimizer_s=perf_counter()-then)), encoding="utf8")


if __name__ == "__main__":
    main()
