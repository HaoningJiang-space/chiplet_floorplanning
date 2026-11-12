"""Retrospectively verify the known v1-to-v2 BE cache adapter and saved arrays.

This audits existing frozen runs. It is not yet integrated into cache admission.
"""

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

if __package__:
    from .validation.measured_sources import digest
    from .validation.sources import write_json
else:
    from validation.measured_sources import digest
    from validation.sources import write_json


def protocol(folder):
    frozen = json.loads((folder/'frozen-inputs.json').read_text())
    path = folder/'audit_ttc_package_transient.py'
    expected = next(h for p, h in frozen['code_sha256'].items() if Path(p).name == path.name)
    if digest(path) != expected:
        raise ValueError('frozen driver copy changed')
    tree = ast.parse(path.read_text())
    functions = {n.name: copy.deepcopy(n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    controls = functions['controls']
    if controls.args.args[-1].arg == 'prior_controls':
        defaults = controls.args.defaults
        if len(defaults) != 1 or not isinstance(defaults[0], ast.Constant) or defaults[0].value is not None:
            raise ValueError('unknown cache adapter signature')
        controls.args.args.pop()
        controls.args.defaults = []

    class Normalize(ast.NodeTransformer):
        def visit_If(self, node):
            if ast.dump(node.test) == ast.dump(ast.parse('prior_controls is None', mode='eval').body):
                expected = ast.parse("print('reuse verified full backward Euler reference', dt, flush=True)\n"
                    "reference, metadata = prior_controls\n"
                    "be = {k:reference['be_'+str(dt)+'_'+k] for k in ('sensors', 'body_means', 'cumulative_boundary_heat_j')}\n"
                    "be.update(metadata['backward_euler'][str(dt)])").body
                if [ast.dump(n) for n in node.orelse] != [ast.dump(n) for n in expected]:
                    raise ValueError('unrecognized cache adapter')
                return node.body
            return self.generic_visit(node)

    controls = Normalize().visit(controls)
    # The known v2 adapter moves this metadata write to main to add provenance.
    relocated_write = ast.dump(ast.parse("write_json(folder/'numerical-controls.json', result)").body[0])
    controls.body = [n for n in controls.body if ast.dump(n) != relocated_write]
    sources = {name: ast.dump(functions[name], include_attributes=False)
               for name in ('pulse', 'physical_flux_check')}
    sources['controls'] = ast.dump(controls, include_attributes=False)
    sources['module_nonfunction_statements'] = [ast.dump(n, include_attributes=False) for n in tree.body
                                               if not isinstance(n, (ast.FunctionDef, ast.If))]
    return frozen, sources, expected


def audit(old, new):
    fo, po, ho = protocol(old)
    fn, pn, hn = protocol(new)
    if po != pn:
        raise ValueError('control protocol changed beyond known cache adapter')
    for path, expected in fo['code_sha256'].items():
        if Path(path).name != 'audit_ttc_package_transient.py' and fn['code_sha256'].get(path) != expected:
            raise ValueError('dependency changed: '+path)
        snapshot = old/Path(path).name
        if snapshot.exists() and digest(snapshot) != expected:
            raise ValueError('old frozen dependency copy changed: '+path)
        snapshot = new/Path(path).name
        if snapshot.exists() and digest(snapshot) != fn['code_sha256'][path]:
            raise ValueError('new frozen dependency copy changed: '+path)
    if fo['geometry'] != fn['geometry'] or fo['boundary'] != fn['boundary']:
        raise ValueError('physical inputs differ')
    report = json.loads((new/'report.json').read_text())
    records = []
    for key, model in report['completed'].items():
        provenance = model['numerical_controls']['cached_be_reference']
        if provenance is None:
            continue
        a, b = old/key, new/key
        if (digest(a/'numerical-controls.npz') != provenance['controls_sha256'] or
                digest(a/'numerical-controls.json') != provenance['metadata_sha256']):
            raise ValueError('cache hash changed')
        if json.loads((a/'geometry.json').read_text()) != json.loads((b/'geometry.json').read_text()):
            raise ValueError('mesh differs')
        with np.load(a/'numerical-controls.npz') as x, np.load(b/'numerical-controls.npz') as y:
            names = [k for k in x.files if k.startswith('be_') or k.startswith('richardson_')]
            if not all(np.array_equal(x[k], y[k]) for k in names):
                raise ValueError('cached reference arrays differ')
        records.append(dict(model=key, identical_arrays=names,
                            source_controls_sha256=digest(a/'numerical-controls.npz'),
                            used_controls_sha256=digest(b/'numerical-controls.npz')))
    if not records:
        raise ValueError('no reused reference bundles found')
    return dict(scope='Retrospective audit of already reused BE caches; not a future cache admission guard',
                old_driver_sha256=ho, new_driver_sha256=hn,
                normalized_control_protocol_sha256=hashlib.sha256(json.dumps(po, sort_keys=True).encode()).hexdigest(),
                protocol_identical_except_verified_cache_adapter=True, checked_cached_models=records,
                future_runner_guard_integrated=False, physical_model_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', required=True, type=Path)
    parser.add_argument('--current', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('preserve existing audit receipt; choose a fresh output')
    result = audit(args.prior, args.current)
    write_json(args.output, result)
    print('verified', len(result['checked_cached_models']), 'existing cache bundles')


if __name__ == '__main__':
    main()
