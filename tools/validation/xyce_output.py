"""Admit Xyce observations by identity, not merely by column count."""
import csv
import json
from pathlib import Path
import re
import subprocess
import numpy as np
from chiplet_floorplanning.characterization import digest


def record_observation(report, report_path, folder, record, columns, observer):
    """Persist execution/diagnostic/measurement admission, including failed cases."""
    folder = Path(folder)
    report['cases'].append(record)
    record['artifacts_sha256'] = {name: digest(folder/name)
        for name in ('deck.cir', 'xyce.log', 'deck.cir.csv') if (folder/name).exists()}
    def save():
        Path(report_path).write_text(json.dumps(report, indent=2)+'\n')
    try:
        record['warnings'] = warning_inventory((folder/'xyce.log').read_text())
        if record['status'] != 'completed':
            raise ValueError('Xyce execution did not complete')
        if record['warnings']['unknown_messages']:
            record['status'] = 'unknown_diagnostic'
            raise ValueError('unknown or suppressed Xyce diagnostic')
        rows = observer(read_wave(folder/'deck.cir.csv', columns))
    except (ValueError, OSError, IndexError) as error:
        if record['status'] == 'completed':
            record['status'] = 'invalid_observation'
        record.update(reason=str(error), error_type=type(error).__name__)
        report['complete'] = False
        report['failure_case'] = folder.name
        save()
        raise
    record['observation_admitted'] = True
    save()
    return rows


def read_wave(path, columns):
    with Path(path).open(newline='') as stream:
        header = next(csv.reader(stream), None)
    expected = ['TIME', *[c.upper() for c in columns]]
    if header != expected:
        raise ValueError('Xyce CSV header identity/order mismatch')
    wave = np.loadtxt(path, delimiter=',', skiprows=1)
    if wave.ndim != 2 or wave.shape[1] != len(expected) or not np.isfinite(wave).all():
        raise ValueError('invalid Xyce CSV values')
    return wave


def execute(executable, folder, timeout_s=60):
    with (Path(folder)/'xyce.log').open('w') as log:
        try:
            run = subprocess.run([str(Path(executable).resolve()), '-max-warnings', '100000', 'deck.cir'], cwd=folder,
                                 stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return dict(status='execution_timeout', returncode=None, timeout_s=timeout_s)
    return dict(status='completed' if run.returncode == 0 else 'execution_failed', returncode=run.returncode)


def warning_inventory(log):
    # Scan warning markers regardless of prefix/case. Only the observed Netlist
    # prefix can enter the allowlist; unfamiliar diagnostic formats fail closed.
    lines = log.splitlines()
    starts = {i for i, line in enumerate(lines) if re.search(r'\bwarning\b', line, re.I)}
    messages, unknown = [], []
    patterns = (
        r'SCALE: duplicate PARSER parameter\. Using the first value found = (?:1\.0u|1u)',
        r'Model card specifies BSIM4 version 4\.5 which is older than the oldest version supported in Xyce \(4\.6\.1\)\. Using oldest version available\.',
        r'Given pbswgd is less than 0\.1\. Pbswgd is set to 0\.1',
        r'Given pbswgs is less than 0\.1\. Pbswgs is set to 0\.1',
        r'(?:Source|Drain) conductance reset to 1\.0e3 mho',
    )
    for start in sorted(starts):
        end = start+1
        while end < len(lines) and end not in starts and lines[end].strip() and not lines[end].lstrip().startswith('*****'):
            end += 1
        message = ' '.join(' '.join(lines[start:end]).split())
        messages.append(message)
        body = re.sub(r'^Netlist warning in file .+? at or near line \d+\s+', '', message)
        body = re.sub(r'^Netlist warning:\s*', '', body)
        recognized_prefix = body != message
        body = re.sub(r'^Device (?:model|instance) \S+:\s*', '', body)
        if not recognized_prefix or not any(re.fullmatch(pattern, body) for pattern in patterns):
            unknown.append(message)
    return dict(messages=messages, unknown_messages=unknown, classification_version=2,
                physical_harmlessness_proven=False)
