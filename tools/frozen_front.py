"""Frozen reference fronts (docs/evidence/front-gap0) as analysis input: identity checks and the shared CLI.

A front is accepted only if the case file is the one it was frozen on, layouts.npz holds the summary's
points, and the coordinates reproduce the summary's lengths. Pins do not enter the heat equation, so
matching peaks alone cannot prove the interconnect input; peaks are re-checked by each tool's own solve.
"""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, pin_manhattan_um


@dataclass(frozen=True)
class Front:
    summary: dict
    summary_sha256: str
    problem: Problem
    index: list
    layouts: list
    length_m: np.ndarray
    peak_c: np.ndarray

    @property
    def case(self):
        return self.summary['case']

    @property
    def gap_um(self):
        return self.summary['gap_um']

    @property
    def resolution(self):
        return self.summary['fv_resolution']


def load(case_path, summary_path, layouts_path):
    summary = json.loads(Path(summary_path).read_text())
    if sha256(Path(case_path).read_bytes()).hexdigest() != summary['case_sha256']:
        raise SystemExit(f'{case_path} is not the case the front was frozen on')
    problem = Problem.from_imported(json.loads(Path(case_path).read_text()))
    z = np.load(layouts_path)
    index = [p['index'] for p in summary['front']]
    for p, i in zip(summary['front'], index):
        if abs(z['length_m'][i] - p['length_m']) > 1e-9 or abs(z['peak_c'][i] - p['peak_c']) > 1e-9:
            raise SystemExit(f'front point {i} does not match layouts.npz')
    layouts = [Layout(z['centre_um'][i], z['rotation_deg'][i]) for i in index]
    length = np.array([p['length_m'] for p in summary['front']])
    # Review of 56f3af6: the summary's numbers must describe these coordinates, not another layout file.
    if layouts and np.abs([pin_manhattan_um(problem, l).sum()/1e6 for l in layouts] - length).max() > 1e-9:
        raise SystemExit('front lengths do not match the layout coordinates')
    return Front(summary, sha256(Path(summary_path).read_bytes()).hexdigest(), problem, index, layouts, length,
                 np.array([p['peak_c'] for p in summary['front']]))


def parser(description, cases=tuple(range(1, 11))):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--cases', type=int, nargs='+', default=list(cases))
    p.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    p.add_argument('--front-dir', type=Path, default=Path('results/front-gap0'))
    p.add_argument('--summary-dir', type=Path, default=Path('docs/evidence/front-gap0'))
    p.add_argument('--workers', type=int, default=24)
    p.add_argument('--output', type=Path, required=True)
    return p


def arguments(description, cases=tuple(range(1, 11))):
    args = parser(description, cases).parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    return args


def paths(args, n):
    """(case, summary, layouts) paths of case n."""
    return args.import_dir/f'Case{n}.json', args.summary_dir/f'case{n}-summary.json', \
        args.front_dir/f'case{n}'/'layouts.npz'
