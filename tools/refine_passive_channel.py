"""Predeclared fast-edge refinement, with hash-verified reuse of slow-edge runs."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil

from validate_passive_channel import ROOT, sha, simulate, summarize
from validation.passive_channel import Channel, GATES, deck, oracle, frequency_checks
from validation.sources import git_revision, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline, output = args.baseline.resolve(), args.output.resolve()
    prior = json.loads((baseline / 'report.json').read_text())
    old = prior['frozen_inputs']
    executable = Path(old['executable'])
    if (old['integration'] != 'gear' or old['gates'] != GATES
            or old['source_hashes']['tools/validation/passive_channel.py'] != sha(ROOT / 'tools/validation/passive_channel.py')
            or old['executable_sha256'] != sha(executable)
            or old['runtime_dll_sha256'] != {p.name: sha(p) for p in executable.parent.glob('*.dll')}
            or len(prior['records']) != 96):
        raise ValueError('baseline physics, oracle, solver or gates incompatible')
    slow = [r for r in prior['records'] if r['channel']['slew_10_90_ps'] == 600]
    if len(slow) != 48 or not all(r['completed'] and r['numerical_gates_passed'] for r in slow):
        raise ValueError('predeclared slow-edge reuse group not fully passed')
    output.mkdir(parents=True, exist_ok=False)
    init = output / 'init'
    init.mkdir()
    shutil.copyfile(baseline / 'init/spinit', init / 'spinit')
    if sha(init / 'spinit') != old['initialization_sha256']:
        raise ValueError('initialization changed')
    paths = ['tools/validation/passive_channel.py', 'tools/validate_passive_channel.py',
             'tools/refine_passive_channel.py', 'docs/passive-channel-plan.md',
             'tests/passive_channel_unittest.py']
    hashes = {p: sha(ROOT / p) for p in paths}
    for p in paths:
        destination = output / 'frozen-code' / p
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / p, destination)
    frozen = dict(old, created_utc=datetime.now(timezone.utc).isoformat(), revision=git_revision(ROOT),
                  source_hashes=hashes, baseline_report_sha256=sha(baseline / 'report.json'),
                  baseline=str(baseline), fast_max_step_ps=[.125, .0625], slow_max_step_ps=[.5, .25],
                  new_runs=48, reused_runs=48,
                  max_step_ps='fast: 0.125/0.0625 ps; slow: 0.5/0.25 ps')
    write_json(output / 'frozen-inputs.json', frozen)
    records, frequency, reused = [], [], []
    for channel in [Channel(**x) for x in old['channels']]:
        for model in ('RC', 'RLC'):
            for n in (8, 16, 32):
                frequency.append(dict(name=channel.name, model=model, segments=n, **frequency_checks(channel, n, model)))
                steps = ([.125, .0625] if n == 32 else [.125]) if channel.slew_10_90_ps == 100 else ([.5, .25] if n == 32 else [.5])
                reference = oracle(channel, n, model) if channel.slew_10_90_ps == 100 else None
                for step in steps:
                    if reference is not None:
                        record = simulate(output, executable, init, channel, n, model, step, reference, 'gear')
                    else:
                        candidates = [r for r in slow if r['channel'] == asdict(channel) and r['model'] == model and r['segments'] == n and r['max_step_ps'] == step]
                        if len(candidates) != 1:
                            raise ValueError('nonunique baseline')
                        record = candidates[0]
                        src, dst = baseline / record['name'], output / record['name']
                        if (src / 'deck.sp').read_bytes() != deck(channel, n, model, step, 'gear').encode():
                            raise ValueError('reused circuit settings changed')
                        if json.loads((src / 'measurement.json').read_text()) != record:
                            raise ValueError('reused measurement changed')
                        dst.mkdir()
                        for filename, field in [('deck.sp', 'deck_sha256'), ('ngspice.log', 'log_sha256'),
                                                ('endpoints.npz', 'endpoints_sha256'), ('waveform.txt.gz', 'waveform_gzip_sha256')]:
                            if sha(src / filename) != record[field]:
                                raise ValueError('reused archive changed')
                            # Immutable local evidence; hard links avoid duplicate large archives.
                            os.link(src / filename, dst / filename)
                        with gzip.open(src / 'waveform.txt.gz', 'rb') as stream:
                            if hashlib.file_digest(stream, 'sha256').hexdigest() != record['waveform_sha256']:
                                raise ValueError('reused waveform decompression mismatch')
                        shutil.copyfile(src / 'measurement.json', dst / 'measurement.json')
                        reused.append(record['name'])
                    records.append(record)
                    write_json(output / 'progress.json', dict(records=records, frequency=frequency, reused=reused))
                    print(f'{len(records):02}/96 {record["name"]}: gates={record["numerical_gates_passed"]} reused={record["name"] in reused}', flush=True)
    if hashes != {p: sha(ROOT / p) for p in paths}:
        raise ValueError('frozen implementation changed')
    report = dict(frozen_inputs=frozen, records=records, frequency=frequency, reused=reused,
                  physical_model_qualified=False, real_phy_timing_qualified=False, **summarize(records))
    write_json(output / 'report.json', report)
    print(json.dumps(dict(completed=sum(r['completed'] for r in records), passed=sum(r['numerical_gates_passed'] for r in records), new_runs=48, reused_runs=len(reused))))


if __name__ == '__main__':
    main()
