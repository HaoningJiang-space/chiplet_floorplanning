"""Source-supported SKY IO revision controls; never a qualified PDK upgrade."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

import numpy as np

from validate_pad_spice import definitions, simulate
from validation.pad_diagnostics import METRICS, source_measurements, nominal_comparison
from validation.pad_provenance import canonical_blocks, replace_definitions
from validation.pad_sources import digest, prepare
from validation.pad_spice import closure, deck, differences, subcircuits
from validation.sources import git_revision, write_json


SOURCE_NAME = 'sky-io-corrected-spice.txt'
SOURCE_URL = ('https://raw.githubusercontent.com/RTimothyEdwards/open_pdks/'
              '2d93509249763cb83dae021fd0dbf3c79e262f47/'
              'sky130/custom/sky130_fd_io/spice/sky130_fd_io.spice')
NOR = 'sky130_fd_io__hvsbt_nor'
UPDATED_BLOCKS = (NOR, 'sky130_fd_io__gpiov2_ctl_hld', 'sky130_fd_io__top_gpiov2')
CASE_IDS = ('sky_nominal', 'sky130_anchor_rise', 'sky130_anchor_fall')


def sha(path):
    return digest(Path(path).read_bytes())


def nor_instances(text):
    """List hierarchical instances, without assuming their mode is active."""
    blocks = subcircuits(text)
    result = []

    def visit(cell, path):
        for line in blocks[cell]['elements']:
            t = line.split()
            if not t[0].lower().startswith('x'):
                continue
            end = next((i for i, v in enumerate(t) if '=' in v), len(t))
            child = t[end - 1].lower()
            if child not in blocks:
                continue
            here = path + '.' + t[0].lower()
            if child == NOR:
                result.append(dict(path=here, parent=cell, parent_nodes=t[1:end - 1],
                                   monitored_internal_node=here + '.net16'))
            visit(child, here)

    visit('sky130_ef_io__gpiov2_pad', 'xpad')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', type=Path, default=Path('results/characterization-provenance/sources'))
    p.add_argument('--root', type=Path, default=Path('local/pad-spice'))
    p.add_argument('--pdk-root', type=Path, default=Path('local/pdk-v03'))
    p.add_argument('--baseline', type=Path, default=Path('results/pad-diagnostic/matrix/report.json'))
    p.add_argument('--ngspice', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root, output, executable = args.root.resolve(), args.output.resolve(), args.ngspice.resolve()
    sources = prepare(root)
    models = definitions(root, args.pdk_root.resolve())
    prior = json.loads(args.baseline.read_text())
    if not prior['software_checks_passed']:
        raise ValueError('baseline numerical/software gates failed')
    if prior['frozen_inputs']['source_lock'] != sources or sha(executable) != prior['frozen_inputs']['ngspice_sha256']:
        raise ValueError('baseline simulator or model source mismatch')
    convention = prior['frozen_inputs']['conventions']['sky130']
    original_path = root / 'sky130A/libs.ref/sky130_fd_io/spice/sky130_fd_io.spice'
    base = original_path.read_text()
    ref_path = args.sources / SOURCE_NAME
    receipt = json.loads(ref_path.with_suffix('.txt.receipt.json').read_text())
    if receipt['url'] != SOURCE_URL or sha(ref_path) != receipt['sha256']:
        raise ValueError('upstream correction provenance mismatch')
    upstream = ref_path.read_text()
    a, b = canonical_blocks(base), canonical_blocks(upstream)
    reachable = closure(subcircuits(base), 'sky130_fd_io__top_gpiov2')['visited_io_subcircuits']
    if set(n for n in reachable if a[n] != b.get(n)) != set(UPDATED_BLOCKS):
        raise ValueError('unexpected upstream reachable differences')
    variants = {'nor_only': (NOR,), 'reachable_updates': UPDATED_BLOCKS}
    output.mkdir(parents=True, exist_ok=False)
    init = output / 'init'
    init.mkdir()
    (init / 'spinit').write_bytes(b'* Isolated initialization.\n')
    derived, variant_meta = {}, {}
    for variant, names in variants.items():
        path = output / (variant + '.spice')
        path.write_bytes(replace_definitions(base, upstream, names).encode('utf-8'))
        derived[variant] = path
        variant_meta[variant] = dict(blocks=list(names), sha256=sha(path))
        (output / variant).mkdir()
    ef = (root / 'sky130A/libs.ref/sky130_fd_io/spice/sky130_ef_io.spice').read_text()
    monitors = nor_instances(base + '\n' + ef)
    baselines, configs = {}, []
    for case_id in CASE_IDS:
        old_case = prior['cases'][case_id]
        config = {k: old_case['config'][k] for k in ('side', 'input_slew_ns', 'external_load_pf')}
        config['temperature_c'] = 25
        configs.append(dict(case_id=case_id, **config))
        for step in (5.0, 2.5):
            old = next(r for r in prior['records'] if r['case_id'] == case_id and r['max_step_ps'] == step)
            folder = args.baseline.parent / old['name']
            for name, key in [('deck.sp', 'deck_sha256'), ('ngspice.log', 'log_sha256'), ('waveform.txt', 'waveform_sha256')]:
                if sha(folder / name) != old[key]:
                    raise ValueError('baseline file changed: ' + str(folder / name))
            generated = deck(root, 'sky130', models['sky130']['mapping'], models['sky130']['pins'],
                             **{k: v for k, v in config.items() if k != 'side'}, max_step_ps=step)
            if generated.encode('utf-8') != (folder / 'deck.sp').read_bytes():
                raise ValueError('baseline deck differs from current fixed settings')
            remeasured = source_measurements(np.loadtxt(folder / 'waveform.txt', skiprows=1), convention, 3.3, 1.8)
            if any(abs(remeasured[k] - old['source_measurements'][k]) > 1e-12 for k in remeasured):
                raise ValueError('baseline measurement convention changed')
            baselines[(case_id, step)] = old
    frozen = dict(source=git_revision(Path.cwd()), source_lock=sources, upstream_source=receipt,
                  baseline_sha256=sha(args.baseline), baseline_path=str(args.baseline.resolve()),
                  ngspice_sha256=sha(executable), ngspice_version=subprocess.check_output([str(executable), '-n', '--version'], text=True),
                  cases=configs, variants=variant_meta, max_steps_ps=[5.0, 2.5],
                  conventions=convention, controls=models['sky130']['mapping'], nor_monitors=monitors,
                  halfstep_gate=dict(absolute_ns=0.002, relative=0.005),
                  nominal_gate=dict(absolute_ns=0.020, relative=0.10),
                  empirical_delta_screen='sum of baseline and candidate endpoint halfstep changes; not an error bound',
                  physical_model_qualified=False, original_characterization_recovered=False,
                  source_files_sha256={f: sha(f) for f in ('tools/validate_pad_revision.py', 'tools/validate_pad_spice.py',
                      'tools/validation/pad_provenance.py', 'tools/validation/pad_spice.py', 'tools/validation/pad_diagnostics.py')})
    write_json(output / 'frozen-inputs.json', frozen)

    def execute(item):
        variant, config, step = item
        case_id = config['case_id']
        run_config = {k: v for k, v in config.items() if k != 'case_id'}
        run_config['max_step_ps'] = step
        old = baselines[(case_id, step)]
        content = (args.baseline.parent / old['name'] / 'deck.sp').read_text()
        matches = [m for m in re.finditer(r'(?im)^\.include\s+"([^"\n]+)"\s*$', content)
                   if Path(m[1]).resolve() == original_path]
        if len(matches) != 1:
            raise ValueError('cannot uniquely replace IO include')
        m = matches[0]
        content = content[:m.start()] + f'.include "{derived[variant]}"\n' + content[m.end():]
        activity = 'wrdata nor_activity.txt ' + ' '.join('v(' + x['monitored_internal_node'] + ')' for x in monitors)
        content = content.replace('wrdata waveform.txt v(vin) v(vout)', 'wrdata waveform.txt v(vin) v(vout)\n' + activity)
        record = simulate(run_config, models, root, executable, output / variant, init, content=content)
        folder = output / variant / record['name']
        record.update(variant=variant, case_id=case_id)
        if record.get('waveform_gate_passed'):
            measured = source_measurements(np.loadtxt(folder / 'waveform.txt', skiprows=1), convention, 3.3, 1.8)
            record['source_measurements'] = measured
            record['comparison'] = nominal_comparison(measured, old['comparisons']['external_only'], None)
            record['signed_change_from_baseline_ns'] = {k: measured[k] - old['source_measurements'][k] for k in METRICS}
            activity_path = folder / 'nor_activity.txt'
            if activity_path.exists():
                data = np.loadtxt(activity_path, skiprows=1)
                valid = data.ndim == 2 and data.shape[1] == 1 + len(monitors) and np.all(np.isfinite(data))
                record['activity_valid'] = bool(valid)
                if valid:
                    record['activity_sha256'] = sha(activity_path)
                    record['internal_node_activity_v'] = {m['path']: dict(
                        rise_window_peak_to_peak=float(np.ptp(data[(data[:, 0] >= 9e-9) & (data[:, 0] <= 39e-9), i + 1])),
                        fall_window_peak_to_peak=float(np.ptp(data[(data[:, 0] >= 39e-9) & (data[:, 0] <= 69e-9), i + 1])))
                        for i, m in enumerate(monitors)}
        write_json(folder / 'revision.json', record)
        return record

    tasks = [(variant, config, step) for config in configs for variant in variants for step in (5.0, 2.5)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(execute, tasks))
    cases = []
    for variant in variants:
        for config in configs:
            case_id = config['case_id']
            pair = {r['max_step_ps']: r for r in records if r['variant'] == variant and r['case_id'] == case_id}
            if not all(r.get('waveform_gate_passed') for r in pair.values()):
                continue
            fine, coarse = pair[2.5], pair[5.0]
            old_fine, old_coarse = baselines[(case_id, 2.5)], baselines[(case_id, 5.0)]
            step_changes = {k: abs(fine['source_measurements'][k] - coarse['source_measurements'][k]) for k in METRICS}
            screens = {k: step_changes[k] + abs(old_fine['source_measurements'][k] - old_coarse['source_measurements'][k]) for k in METRICS}
            cases.append(dict(variant=variant, case_id=case_id, fine=fine,
                              convergence=differences(fine['source_measurements'], coarse['source_measurements'], 0.002, 0.005),
                              step_changes_ns=step_changes, empirical_delta_screen_ns=screens))
    checks = dict(all_12_completed=len(records) == 12 and all(r['simulation_completed'] for r in records),
                  all_waveforms_valid=all(r.get('waveform_gate_passed', False) for r in records),
                  all_activity_saved=all(r.get('activity_valid', False) for r in records),
                  all_6_halfstep_checks=len(cases) == 6 and all(r['convergence']['passed'] for r in cases),
                  fixed_input_slews=all(r.get('waveform_gate_passed', False) and all(
                      abs(r['source_measurements'][e + '_input_slew_ns'] - r['input_slew_ns']) < 1e-8 for e in ('rise', 'fall')) for r in records),
                  original_models_unchanged=prepare(root) == sources)
    write_json(output / 'report.json', dict(frozen_inputs=frozen, software_checks=checks,
        software_checks_passed=all(checks.values()), records=records, cases=cases,
        physical_model_qualified=False, original_characterization_recovered=False,
        scope='source-supported block substitutions in pinned model stack; not a complete upstream PDK release or physical calibration'))
    print(json.dumps(checks, indent=2), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
