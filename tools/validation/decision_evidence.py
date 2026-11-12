"""Bind decision claims to a complete frozen domain and exact evaluator inputs."""

import copy
import hashlib
import itertools
import json
from pathlib import Path, PurePosixPath


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_pdk(model_root, expected):
    """Check the selected model directory itself, never a similarly named sibling."""
    if not expected:
        raise ValueError('complete frozen PDK source manifest is required')
    root = Path(model_root).resolve(strict=True)
    for name, fingerprint in expected.items():
        relative = PurePosixPath(name)
        if relative.parts[0]!='pdk-v03' or len(relative.parts)<2 or '..' in relative.parts:
            raise ValueError('unexpected PDK source path')
        path = root.joinpath(*relative.parts[1:]).resolve(strict=True)
        if not path.is_relative_to(root) or file_hash(path)!=fingerprint:
            raise ValueError('PDK source hash mismatch: '+name)
    return dict(expected)


def verify_runtime(sta, model_root, frozen):
    executable = file_hash(sta)
    if executable!=frozen['executable_sha256']:
        raise ValueError('OpenSTA executable differs from frozen benchmark')
    return dict(executable_sha256=executable,
                pdk_source_sha256=verify_pdk(model_root, frozen['pdk_source_sha256']))


def verify_saved_sta_files(receipt, folder):
    """The independent channel audit must read exactly the saved STA inputs."""
    folder = Path(folder).resolve(strict=True)
    if not receipt['input_sha256'] or not receipt['models']:
        raise ValueError('missing saved STA input or model manifest')
    for name, expected in receipt['input_sha256'].items():
        if Path(name).name!=name or file_hash(folder/name)!=expected:
            raise ValueError('saved STA input hash mismatch: '+name)
    if file_hash(folder/'sta.log')!=receipt['log_sha256']:
        raise ValueError('saved STA log hash mismatch')
    for name, model in receipt['models'].items():
        library = name+'.lib'
        if library not in receipt['input_sha256'] or Path(model['path']).resolve()!=folder/library:
            raise ValueError('channel capacitance model is not the recorded STA library')


def verify_timing_identity(receipt, frozen):
    if receipt['executable_sha256']!=frozen['executable_sha256']:
        raise ValueError('timing receipt uses another OpenSTA executable')
    if not receipt['models']:
        raise ValueError('missing timing model identities')
    for model in receipt['models'].values():
        if not model['source_files']:
            raise ValueError('missing timing model source identities')
        for name, fingerprint in model['source_files'].items():
            if frozen['pdk_source_sha256'].get('pdk-v03/'+name)!=fingerprint:
                raise ValueError('timing receipt uses another PDK source: '+name)


def verify_artifact_links(frozen_sha, benchmark, witness, thermal, channel, report_hashes):
    if not all(r.get('complete') is True for r in (benchmark, witness, thermal)) or channel.get('accepted') is not True:
        raise ValueError('complete source evidence and accepted channel audit required')
    if benchmark['frozen_inputs_sha256']!=frozen_sha:
        raise ValueError('benchmark does not bind its frozen inputs')
    for record in (witness, thermal):
        if record['benchmark_inputs_sha256']!=frozen_sha:
            raise ValueError('attached witness or thermal audit belongs to another benchmark')
    actual = list(channel['input_report_sha256'].values())
    if len(actual)!=len(report_hashes) or set(actual)!=set(report_hashes):
        raise ValueError('channel audit does not bind these exact result reports')


def verify_coverage(cases, frozen):
    expected = set(itertools.product(frozen['profiles'], frozen['layouts'], frozen['route_orders']))
    observed = [(r['profile'], r['layout_id'], r['policy']) for r in cases]
    if len(observed)!=len(expected) or len(set(observed))!=len(observed) or set(observed)!=expected:
        raise ValueError('fixed-budget result ledger does not cover the complete frozen Cartesian domain')
    if len({r['id'] for r in cases})!=len(cases) or frozen['domain_size']!=len(expected):
        raise ValueError('duplicate result IDs or inconsistent frozen domain size')
    return len(expected)


def verify_inputs(row, inputs, frozen, *, refinement_factor=1):
    expected = copy.deepcopy(frozen['profiles'][row['profile']])
    if refinement_factor not in (1, 2, 4):
        raise ValueError('undeclared planar refinement factor')
    if refinement_factor!=1:
        grid = expected['design']['grid']
        expected['grid'] = {**grid, 'nx': grid['nx']*refinement_factor, 'ny': grid['ny']*refinement_factor}
    policy = row['policy']; order = inputs['configuration']['routing']['order']
    if policy in frozen['route_orders']:
        wanted_order = frozen['route_orders'][policy]
    elif policy=='witness':
        wanted_order = order
        names = next(iter(frozen['route_orders'].values()))
        if len(order)!=len(names) or set(order)!=set(names):
            raise ValueError('witness order does not cover the same physical nets')
    else:
        raise ValueError('undeclared routing policy')
    expected['routing']['order'] = wanted_order
    wanted = dict(layout=frozen['layouts'][row['layout_id']], configuration=expected)
    if inputs != wanted:
        raise ValueError('evaluated layout or physical configuration differs from frozen problem')
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if row['input_sha256']!=fingerprint:
        raise ValueError('reported evaluator fingerprint does not bind the saved inputs')
    return fingerprint
