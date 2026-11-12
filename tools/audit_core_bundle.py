"""Compare the installed core bundle with the exact inputs of the SPICE probe."""
import argparse
import json
from pathlib import Path
import re
import tarfile
import zstandard
import numpy as np
from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.liberty_checks import unique_group, read_table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path('local/core-archive-fa87'))
    parser.add_argument('--probe', type=Path, default=Path('results/physical-calibration/core-buf-repro-v1'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive = args.bundle/'sky130_fd_sc_hd.tar.zst'
    if digest(archive)!='d4081b3c0fbfa2afe31dba789c03157ad137ea08b11910e2c8b3ec81b2a61bf6':
        raise ValueError('unexpected installed core archive bytes')
    prefix = 'sky130A/libs.ref/sky130_fd_sc_hd/'
    wanted = {prefix+'spice/sky130_fd_sc_hd.spice'} | {
        prefix+f'lib/sky130_fd_sc_hd__tt_{t:03d}C_1v80.lib' for t in (25,100)}
    seen = set()
    with archive.open('rb') as raw, zstandard.ZstdDecompressor().stream_reader(raw) as stream:
        with tarfile.open(fileobj=stream,mode='r|') as tar:
            for member in tar:
                if member.name not in wanted:
                    continue
                if not member.isfile() or member.name in seen:
                    raise ValueError('invalid or duplicate bundle member')
                seen.add(member.name); data = tar.extractfile(member).read()
                path = args.bundle/member.name
                if path.exists() and path.read_bytes()!=data:
                    raise ValueError('installed member differs from pinned archive')
                if not path.exists():
                    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
    if seen!=wanted:
        raise ValueError('missing expected bundle members')
    root = args.bundle/'sky130A/libs.ref/sky130_fd_sc_hd'
    text = (root/'spice/sky130_fd_sc_hd.spice').read_text()
    block = re.search(r'(?ims)^\.subckt\s+sky130_fd_sc_hd__buf_8\b.*?^\.ends[^\n]*', text)[0]
    original = (args.probe/'buf_8_original.spice').read_text()
    source = re.search(r'(?ims)^\.subckt\s+sky130_fd_sc_hd__buf_8\b.*?^\.ends[^\n]*', original)[0]
    result = dict(archive_url='https://github.com/chipfoundry/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/sky130_fd_sc_hd.tar.zst', archive_sha256=digest(archive),
                  source_sha256=digest(__file__), archive_members_verified=True,
                  installed_buf_netlist_equals_probe=block.split()==source.split(), tables=[],
                  physical_qualified=False,
                  scope='bundle identity only; not original characterization PEX or primitive-model provenance')
    for temp in (25,100):
        lib = root/f'lib/sky130_fd_sc_hd__tt_{temp:03d}C_1v80.lib'
        source_lib = Path(f'local/pdk-v03/sky_buf_8_tt_{temp:03d}C_1v80.json')
        pin = unique_group(unique_group(lib.read_text(),'cell','sky130_fd_sc_hd__buf_8'),'pin','X')
        original_tables = json.loads(source_lib.read_text())['pin,X']['timing']
        for name in ('cell_rise','cell_fall','rise_transition','fall_transition'):
            axes, values = read_table(pin, name); old = original_tables[name+',del_1_7_7']
            equal = all(np.array_equal(a,old[f'index_{i}']) for i,a in enumerate(axes,1)) and np.array_equal(values,old['values'])
            result['tables'].append(dict(temperature_c=temp,table=name,exact_axes_values_equal=bool(equal),
                                        installed_lib_sha256=digest(lib),probe_lib_sha256=digest(source_lib)))
    result['all_compared_inputs_identical'] = result['installed_buf_netlist_equals_probe'] and all(r['exact_axes_values_equal'] for r in result['tables'])
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
