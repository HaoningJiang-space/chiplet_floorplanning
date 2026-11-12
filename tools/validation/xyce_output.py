"""Admit Xyce observations by identity, not merely by column count."""
import csv
from pathlib import Path
import re
import subprocess
import numpy as np


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
            run = subprocess.run([str(Path(executable).resolve()), 'deck.cir'], cwd=folder,
                                 stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return dict(status='execution_timeout', returncode=None, timeout_s=timeout_s)
    return dict(status='completed' if run.returncode == 0 else 'execution_failed', returncode=run.returncode)


def warning_inventory(log):
    blocks = re.findall(r'Netlist warning.*?(?=Netlist warning|\*\*\*\*\*|\Z)', log, re.S)
    messages = [' '.join(b.split()) for b in blocks]
    known = ('duplicate PARSER parameter', 'oldest version supported',
             'Pbswgd is set to 0.1', 'Pbswgs is set to 0.1',
             'Source conductance reset to 1.0e3 mho', 'Drain conductance reset to 1.0e3 mho')
    return dict(messages=messages, unknown_messages=[m for m in messages if not any(k in m for k in known)],
                physical_harmlessness_proven=False)
