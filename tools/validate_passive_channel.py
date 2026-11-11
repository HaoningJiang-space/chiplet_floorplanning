"""Locally compare 12 declared ideal channels using RC/RLC and independent ODEs."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

import numpy as np
import scipy

from validation.passive_channel import (Channel, GATES, VDD, STOP_S, network, oracle,
                                        deck, crossings, crossing_difference,
                                        ledger, frequency_checks)
from validation.sources import git_revision, write_json
from validation.spice_waveform import read_real_binary


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def refinement(coarse, fine):
    differences = []
    passed = crossing_difference(coarse, fine) is not None
    for edge in ('rise', 'fall'):
        for name in ('delay_50_ps', 'slew_10_90_ps'):
            x, y = coarse[edge][name], fine[edge][name]
            if x is None or y is None:
                passed = False
                continue
            delta = abs(x-y)
            limit = max(GATES['refinement_absolute_ps'], GATES['refinement_relative']*abs(y))
            differences.append(dict(edge=edge, metric=name, difference_ps=delta, limit_ps=limit))
            passed = passed and delta <= limit
    return dict(passed=bool(passed), metrics=differences,
                max_crossing_difference_ps=crossing_difference(coarse, fine))


def negative_controls(t, u, v, current, branch, c, r, l, b, driver, load):
    records = {}
    cc = c.copy()
    cc[-1] -= load
    dd = c.copy()
    dd[-1] += load
    ii = branch.copy()
    ii[:, 0] *= -1
    variants = [('reversed_source_current', -current, branch, c, l),
                ('omitted_receiver_charge_and_energy', current, branch, cc, l),
                ('duplicated_receiver_charge_and_energy', current, branch, dd, l),
                ('omitted_magnetic_energy', current, branch, c, np.zeros_like(l)),
                ('reversed_first_branch_current', current, ii, c, l)]
    for name, source, branches, caps, inds in variants:
        value = ledger(t, u, v, source, branches, caps, r, inds, b, driver)
        records[name] = dict(detected=not value['gates_passed'], **value)
    return records


def simulate(output, executable, init, channel, segments, model, step_ps, reference, integration='trap', accuracy='standard', waveform_format='text'):
    if accuracy not in ('standard', 'strict', 'balanced') or waveform_format not in ('text', 'binary'):
        raise ValueError('unsupported numerical precision profile')
    run_dir = output / f'{channel.name}_{model}_n{segments}_dt{step_ps:g}'
    run_dir.mkdir()
    content = deck(channel, segments, model, step_ps, integration)
    if accuracy == 'strict':
        content = content.replace('reltol=1e-7 abstol=1e-14 vntol=1e-9',
                                  'reltol=1e-9 abstol=1e-16 vntol=1e-11 chgtol=1e-20 trtol=1')
        content = content.replace('wrdata waveform.txt', 'option\nwrdata waveform.txt')
    elif accuracy == 'balanced':
        content = content.replace('reltol=1e-7 abstol=1e-14 vntol=1e-9',
                                  'reltol=1e-8 abstol=1e-14 vntol=1e-9 chgtol=1e-18 trtol=1')
        content = content.replace('wrdata waveform.txt', 'option\nwrdata waveform.txt')
    raw_name = 'waveform.txt'
    if waveform_format == 'binary':
        content = content.replace('wrdata waveform.txt', 'set filetype=binary\nwrite waveform.raw')
        raw_name = 'waveform.raw'
    (run_dir / 'deck.sp').write_bytes(content.encode())
    tic = time.monotonic()
    timed_out = False
    # Stream diagnostics to disk so a timeout cannot discard the evidence.
    with (run_dir / 'ngspice.log').open('wb') as log:
        try:
            run = subprocess.run([str(executable), '-n', '-b', 'deck.sp'], cwd=run_dir,
                                 env={**os.environ, 'SPICE_SCRIPTS': str(init), 'OMP_NUM_THREADS': '1'},
                                 stdout=log, stderr=subprocess.STDOUT, timeout=180)
            returncode = run.returncode
        except subprocess.TimeoutExpired:
            timed_out, returncode = True, None
    record = dict(name=run_dir.name, channel=asdict(channel), segments=segments,
                  model=model, max_step_ps=step_ps, integration=integration,
                  accuracy=accuracy,
                  waveform_format=waveform_format, waveform_gzip_file=raw_name+'.gz',
                  returncode=returncode, timed_out=timed_out,
                  elapsed_s=time.monotonic()-tic, deck_sha256=sha(run_dir / 'deck.sp'),
                  log_sha256=sha(run_dir / 'ngspice.log'), completed=False,
                  numerical_gates_passed=False, physical_model_qualified=False)
    write_json(run_dir / 'measurement.json', record)
    if timed_out or returncode or not (run_dir / raw_name).exists():
        return record
    raw = run_dir / raw_name
    # Header, dimensions and source equation detect parser/sign/column mistakes.
    expected = ['time', 'v(src)', 'i(vs)'] + [f'v(n{j})' for j in range(segments+1)] + [f'i(vp{j})' for j in range(segments)]
    if waveform_format == 'binary':
        samples = read_real_binary(raw, expected)
    else:
        with raw.open() as stream:
            header = stream.readline().split()
        if header != expected:
            raise ValueError(f'waveform header mismatch: {header}')
        samples = np.loadtxt(raw, skiprows=1)
    if samples.shape[1] != 2*segments+4 or not np.all(np.isfinite(samples)):
        raise ValueError('invalid waveform array')
    if samples[0, 0] > 0:
        samples = np.vstack([np.zeros(samples.shape[1]), samples])
    t, u, source = samples[:, 0], samples[:, 1], -samples[:, 2]
    v, branch = samples[:, 3:segments+4], samples[:, segments+4:]
    if abs(t[-1]-STOP_S) > 1e-18 or np.max(np.diff(t)) > step_ps*1e-12*1.00001:
        raise ValueError('incomplete waveform or exceeded maximum step')
    c, r, l, b = network(channel, segments, model)
    balance = ledger(t, u, v, source, branch, c, r, l, b, channel.driver_ohm)
    measured = crossings(t, v[:, -1], channel)
    ot, ov = reference
    reference_crossings = crossings(ot, ov[:, -1], channel)
    # Both endpoint voltages on the independent, finer uniform oracle grid.
    waveform_error = max(float(np.max(abs(np.interp(ot, t, v[:, j])-ov[:, k])))
                         for j, k in ((0, 0), (-1, 1)))
    timing_error = crossing_difference(measured, reference_crossings)
    pre = t < 1e-9
    stimulus_error = float(np.max(abs(u-np.interp(t, *channel.pwl))))
    driver_error = float(np.max(abs((u-v[:, 0])/channel.driver_ohm-source)))
    quiet = float(max(np.max(abs(v[pre])), np.max(abs(branch[pre]))))
    record.update(completed=True, sample_count=len(t),
                  stimulus_max_error_v=stimulus_error, driver_kcl_max_error_a=driver_error,
                  initial_rest_max_absolute=quiet, ledger=balance, crossings=measured,
                  receiver_min_v=float(v[:, -1].min()), receiver_max_v=float(v[:, -1].max()),
                  oracle_endpoint_max_error_v=waveform_error, oracle_crossing_max_error_ps=timing_error,
                  oracle_grid_ps=0.125,
                  numerical_gates_passed=bool(balance['gates_passed'] and waveform_error <= GATES['waveform_v']
                    and timing_error is not None and timing_error <= GATES['crossing_ps']
                    and stimulus_error < 1e-8 and driver_error < 1e-10 and quiet < 1e-12))
    if channel.name == 'l6_r25_s100' and model == 'RLC' and segments == 32:
        record['negative_controls'] = negative_controls(t, u, v, source, branch, c, r, l, b,
                                                        channel.driver_ohm, channel.load_f)
    np.savez_compressed(run_dir / 'endpoints.npz', time_s=t, source_v=u,
                        driver_current_a=source, near_v=v[:, 0], far_v=v[:, -1],
                        oracle_time_s=ot, oracle_near_v=ov[:, 0], oracle_far_v=ov[:, 1])
    record['endpoints_sha256'] = sha(run_dir / 'endpoints.npz')
    original_hash = sha(raw)
    compressed = run_dir / (raw_name+'.gz')
    with raw.open('rb') as src, compressed.open('wb') as dst:
        with gzip.GzipFile(filename='', fileobj=dst, mode='wb', compresslevel=1, mtime=0) as zipped:
            while chunk := src.read(1 << 20):
                zipped.write(chunk)
    with gzip.open(compressed, 'rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != original_hash:
            raise ValueError('lossless waveform archive verification failed')
    record.update(waveform_sha256=original_hash, waveform_gzip_sha256=sha(compressed),
                  waveform_gzip_bytes=compressed.stat().st_size)
    # Only this freshly generated file, verified against its lossless archive.
    if raw.resolve().parent != run_dir.resolve() or not raw.resolve().is_relative_to(output.resolve()):
        raise ValueError('raw waveform outside this run')
    raw.unlink()
    write_json(run_dir / 'measurement.json', record)
    return record


def finest_records(records):
    return [x for x in records if x['segments'] == 32 and x['completed']
            and x['max_step_ps'] == min(y['max_step_ps'] for y in records
                if y['channel'] == x['channel'] and y['model'] == x['model'] and y['segments'] == 32)]


def summarize(records):
    comparisons = []
    for name in sorted({Channel(**x['channel']).name for x in records}):
        rows = [x for x in records if Channel(**x['channel']).name == name]
        for model in ('RC', 'RLC'):
            selected = {(x['segments'], x['max_step_ps']): x for x in rows if x['model'] == model}
            if len(selected) != 4 or not all(x['completed'] for x in selected.values()):
                comparisons.append(dict(name=name, model=model, incomplete=True))
                continue
            fine_step, coarse_step = sorted({x['max_step_ps'] for x in selected.values()})
            comparisons.append(dict(name=name, model=model,
                fine_step_ps=fine_step, coarse_step_ps=coarse_step,
                temporal=refinement(selected[32, coarse_step]['crossings'], selected[32, fine_step]['crossings']),
                spatial=refinement(selected[16, coarse_step]['crossings'], selected[32, coarse_step]['crossings']),
                coarse_spatial=refinement(selected[8, coarse_step]['crossings'], selected[16, coarse_step]['crossings'])))
    fine = finest_records(records)
    effects = []
    for rc in [x for x in fine if x['model'] == 'RC']:
        channel = Channel(**rc['channel'])
        rlc = next((x for x in fine if x['model'] == 'RLC' and x['channel'] == rc['channel']), None)
        clocks = {model: next((x for x in fine if x['model'] == model and x['channel'] == asdict(Channel(3, channel.driver_ohm, channel.slew_10_90_ps))), None) for model in ('RC', 'RLC')}
        if rlc is None or any(x is None for x in clocks.values()):
            continue
        effects.append(dict(name=channel.name, channel=asdict(channel),
                            rc_delay_ps={e: rc['crossings'][e]['delay_50_ps'] for e in ('rise', 'fall')},
                            rlc_delay_ps={e: rlc['crossings'][e]['delay_50_ps'] for e in ('rise', 'fall')},
                            # Same-edge comparison, explicitly fixed source-event pairing.
                            same_edge_skew_ps={model: {e: None if row['crossings'][e]['delay_50_ps'] is None or clocks[model]['crossings'][e]['delay_50_ps'] is None else row['crossings'][e]['delay_50_ps']-clocks[model]['crossings'][e]['delay_50_ps'] for e in ('rise', 'fall')} for model, row in [('RC', rc), ('RLC', rlc)]},
                            receiver_extrema_v={model: [row['receiver_min_v'], row['receiver_max_v']] for model, row in [('RC', rc), ('RLC', rlc)]}))
    return dict(refinement=comparisons, channel_effects=effects)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ngspice', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--integration', choices=['trap', 'gear'], default='trap')
    args = parser.parse_args()
    output, executable = args.output.resolve(), args.ngspice.resolve()
    output.mkdir(parents=True, exist_ok=False)
    init = output / 'init'
    init.mkdir()
    (init / 'spinit').write_bytes(b'* Isolated initialization; no PDK.\n')
    channels = [Channel(length, driver, slew) for length in (1, 3, 6) for driver in (25, 100) for slew in (100, 600)]
    files = ['tools/validation/passive_channel.py', 'tools/validate_passive_channel.py',
             'docs/passive-channel-plan.md', 'tests/passive_channel_unittest.py',
             'tools/ngspice-windows.lock.json', 'examples/low_speed_gpio.json']
    hashes = {name: sha(ROOT / name) for name in files}
    # Hash runtime DLLs too, because the executable alone does not identify a solver.
    runtime = {p.name: sha(p) for p in executable.parent.glob('*.dll')}
    frozen = dict(created_utc=datetime.now(timezone.utc).isoformat(), revision=git_revision(ROOT),
                  remote_commit=subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=ROOT, text=True).strip(),
                  source_hashes=hashes, python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                  executable=str(executable), executable_sha256=sha(executable), runtime_dll_sha256=runtime,
                  simulator_version=subprocess.check_output([str(executable), '-v'], text=True),
                  initialization_sha256=sha(init / 'spinit'), gates=GATES,
                  channels=[asdict(x) for x in channels], segments=[8, 16, 32],
                  max_step_ps=[.5, .25], fine_step_segments=32, oracle_step_ps=.125,
                  integration=args.integration,
                  physical_model_qualified=False)
    write_json(output / 'frozen-inputs.json', frozen)
    records, frequency = [], []
    for channel in channels:
        for model in ('RC', 'RLC'):
            for n in (8, 16, 32):
                reference = oracle(channel, n, model)
                frequency.append(dict(name=channel.name, model=model, segments=n, **frequency_checks(channel, n, model)))
                for step in ([.5, .25] if n == 32 else [.5]):
                    record = simulate(output, executable, init, channel, n, model, step, reference, args.integration)
                    records.append(record)
                    write_json(output / 'progress.json', dict(records=records, frequency=frequency))
                    print(f'{len(records):02}/96 {record["name"]}: complete={record["completed"]} gates={record["numerical_gates_passed"]}', flush=True)
    if hashes != {name: sha(ROOT / name) for name in files}:
        raise ValueError('frozen implementation changed during experiment')
    report = dict(frozen_inputs=frozen, records=records, frequency=frequency,
                  physical_model_qualified=False, real_phy_timing_qualified=False, **summarize(records))
    write_json(output / 'report.json', report)
    print(json.dumps(dict(completed=sum(x['completed'] for x in records),
                          numerical_passed=sum(x['numerical_gates_passed'] for x in records)), indent=2))


if __name__ == '__main__':
    main()
