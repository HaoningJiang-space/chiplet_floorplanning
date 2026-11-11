"""Reproduce bounded pad source, library-identity and archive-inventory evidence."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tarfile
from urllib.request import Request, urlopen

import zstandard

from validation.pad_provenance import canonical_blocks, renamed_library_equal
from validation.pad_sources import checked_write, digest, prepare
from validation.pad_spice import closure, subcircuits
from validation.sources import git_revision, verify, write_json


LOCK = Path(__file__).with_name('pad-provenance-sources.lock.json')


def locked_sources(folder, download=False):
    lock = json.loads(LOCK.read_text())
    result = {}
    for item in lock['files']:
        path = folder / item['path']
        if not path.exists() and download:
            request = Request(item['url'], headers={'User-Agent': 'chiplet-floorplanning-local-research'})
            with urlopen(request, timeout=60) as response:
                data = response.read()
            if digest(data) != item['sha256']:
                raise ValueError('download source changed: ' + item['path'])
            checked_write(path, data)
            # The revision runner consumes the same explicit URL/hash receipt.
            write_json(path.with_suffix(path.suffix + '.receipt.json'), item)
        if not path.exists() or digest(path.read_bytes()) != item['sha256']:
            raise ValueError('missing or changed source: ' + str(path))
        receipt_path = path.with_suffix(path.suffix + '.receipt.json')
        if not receipt_path.exists():
            write_json(receipt_path, item)
        result[item['path']] = item
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', type=Path, default=Path('results/characterization-provenance/sources'))
    p.add_argument('--root', type=Path, default=Path('local/pad-spice'))
    p.add_argument('--pdk-root', type=Path, default=Path('local'))
    p.add_argument('--download', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    sources = locked_sources(args.sources, args.download)
    model_manifest = prepare(args.root)
    libraries = verify(args.pdk_root, 'pdk-v03/')
    installed_path = args.root / 'sky130A/libs.ref/sky130_fd_io/spice/sky130_fd_io.spice'
    installed = installed_path.read_text()
    base = (args.sources / 'sky-custom-io-spice.txt').read_text()
    reference = (args.sources / 'sky-io-corrected-spice.txt').read_text()
    proposed = (args.sources / 'sky-pr5-spice.txt').read_text()
    blocks, corrected, pr_blocks = [canonical_blocks(t) for t in (installed, reference, proposed)]
    installed_blocks = subcircuits(installed)
    structure = closure(installed_blocks, 'sky130_fd_io__top_gpiov2')
    reachable = structure['visited_io_subcircuits']
    changed = [n for n in reachable if blocks[n] != corrected.get(n)]
    old_name, new_name = 'sky130_fd_io__top_gpiov2', 'sky130_ef_io__gpiov2_pad'
    pr_lib = (args.sources / 'sky-pr5-tt-lib.txt').read_text()
    active_lib = (args.pdk_root / 'pdk-v03/sky_io_tt_1v8_3v3.lib').read_text()
    gf_header = (args.pdk_root / 'pdk-v03/gf_io_tt_3v3.lib').read_text()
    headers = {}
    for side, text in [('gf180', gf_header), ('sky130', active_lib)]:
        headers[side] = {key: (m[1] if (m := re.search(r'\b' + key + r'\s*:\s*"([^"\n]*)"', text)) else None)
                         for key in ('date', 'revision', 'driver_model', 'simulator', 'def_sim_opt')}
    inventories = {}
    for key in ('gf-io-tree', 'sky-io-tree', 'sky-io-proposed-tree', 'open-pdks-tree', 'skywater-tree'):
        tree = json.loads((args.sources / (key + '.json')).read_text())
        if tree['truncated']:
            raise ValueError('cannot claim full tree coverage: ' + key)
        paths = [r['path'] for r in tree['tree'] if r['type'] == 'blob']
        inventories[key] = dict(tree_entries=len(tree['tree']), file_count=len(paths), truncated=False,
                                keyword_candidates=[n for n in paths if re.search(r'charact|predriver|dspf|spef|pex', n, re.I)],
                                scope='full path inventory; keywords are discovery aids, not evidence that unnamed content is absent')
    archives = {}
    for path in sorted((args.root / 'archives').glob('*.tar.zst')):
        with path.open('rb') as f, zstandard.ZstdDecompressor().stream_reader(f) as stream:
            with tarfile.open(fileobj=stream, mode='r|') as archive:
                names = [member.name for member in archive if member.isfile()]
        archives[path.name] = dict(sha256=digest(path.read_bytes()), regular_files=len(names),
                                  suffix_counts=dict(sorted(Counter(Path(n).suffix for n in names).items())),
                                  keyword_candidates=[n for n in names if re.search(r'charact|predriver|dspf|spef|pex', n, re.I)])
    checks = dict(installed_io_equals_pinned_custom=installed == base,
                  pr5_and_active_lib_equal_except_declared_name=renamed_library_equal(pr_lib, active_lib, old_name, new_name),
                  exactly_three_changed_reachable_definitions=set(changed) == {'sky130_fd_io__hvsbt_nor', 'sky130_fd_io__gpiov2_ctl_hld', 'sky130_fd_io__top_gpiov2'},
                  all_95_corrected_reachable_definitions_equal_pr5=len(reachable) == 95 and all(corrected.get(n) == pr_blocks.get(n) for n in reachable))
    # Explicit unresolved contract fields, never filled by inference from a header label.
    contract = dict(original_characterization_deck=None, original_input_waveform=None,
                    original_load_reference_plane=None, original_extracted_netlist_and_pex_recipe=None,
                    device_model_revision_used_for_liberty=None, original_hspice_reproduction=None)
    report = dict(source=git_revision(Path.cwd()), locked_sources=sources,
                  model_lock_sha256=model_manifest['lock_sha256'], library_source_hashes=libraries,
                  software_checks=checks, software_checks_passed=all(checks.values()),
                  library_headers=headers, original_characterization_contract=contract,
                  original_characterization_recovered=False, physical_model_qualified=False,
                  reachable_io_definition_count=len(reachable), changed_definitions=changed,
                  empty_reachable_io_definitions=structure['empty_subcircuits'],
                  declaration_types_in_reachable_io=dict(Counter(e[0].upper() for n in reachable for e in installed_blocks[n]['elements'])),
                  corrected_definition_hashes={n: digest('\n'.join(corrected[n]).encode()) for n in changed},
                  renamed_library_old_symbol_occurrences=pr_lib.count(old_name),
                  tree_inventories=inventories, archive_inventories=archives,
                  scope='bounded source lineage and netlist differences; not proof of original characterization equivalence or worldwide absence of files')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, report)
    print(json.dumps(checks, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
