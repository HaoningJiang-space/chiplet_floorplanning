"""Construct a declared TAP-derived endpoint geometry; no PHY qualification."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


PITCH_NM = 75000


def source_bytes(path):
    """Portable digest input for checked-in UTF-8 text on Windows/Linux."""
    return Path(path).read_bytes().replace(b'\r\n',b'\n')


def terminals(domain):
    result = [[] for _ in domain['chiplets']]
    if len(domain['connection_wire_demands']) != len(result):
        raise ValueError('Demand shape mismatch')
    for s, row in enumerate(domain['connection_wire_demands']):
        if len(row) != len(result):
            raise ValueError('Demand shape mismatch')
        for t, amount in enumerate(row):
            if amount < 0 or amount != int(amount) or (s == t and amount):
                raise ValueError('Expected nonnegative integral inter-die conductors')
            for bit in range(int(amount)):
                wire = [s,t,bit]
                result[s].append(dict(wire=wire, direction='source'))
                result[t].append(dict(wire=wire, direction='target'))
    return result


def ring_cells(nx, ny, rows):
    for y in range(ny+2*rows):
        for x in range(nx+2*rows):
            if not (rows <= x < rows+nx and rows <= y < rows+ny):
                yield x,y


def signal_capacity(nx,ny,rows):
    # Exact checkerboard-even count = even rectangle minus even core cells.
    # The core offset is (rows,rows), whose parity is even.
    return ((nx+2*rows)*(ny+2*rows)+1)//2 - (nx*ny+1)//2


def build(domain):
    ends = terminals(domain); chips = []
    for i,c in enumerate(domain['chiplets']):
        w,h = c['core_width_um']*1000,c['core_height_um']*1000
        nx,ny = (w+PITCH_NM-1)//PITCH_NM,(h+PITCH_NM-1)//PITCH_NM
        rows = 1
        while signal_capacity(nx,ny,rows) < len(ends[i]):
            rows += 1
        width,height = (nx+2*rows)*PITCH_NM,(ny+2*rows)*PITCH_NM
        pads = []; assigned = iter(ends[i])
        for x,y in ring_cells(nx,ny,rows):
            record = dict(x_nm=(2*x+1)*PITCH_NM//2, y_nm=(2*y+1)*PITCH_NM//2)
            if (x+y)%2:
                record['role'] = 'reserved_pdn'
            else:
                terminal = next(assigned,None)
                record.update(dict(role='signal',**terminal) if terminal else dict(role='unpopulated'))
            pads.append(record)
        chips.append(dict(id=i,core_width_nm=w,core_height_nm=h,core_power_w=c['power_w'],
                          width_nm=width,height_nm=height,core_x_nm=(width-w)//2,
                          core_y_nm=(height-h)//2,ring_rows=rows,pads=pads))
    return dict(case=domain['name'],pitch_nm=PITCH_NM,opening_diameter_nm=35000,
                opening_spacing_nm=40000,landing_diameter_nm=50000,chips=chips,
                physical_qualified=False,phy_qualified=False)


def verify(domain, result):
    """Check geometry and conductor coverage without using generated state."""
    expected = terminals(domain)
    if result['pitch_nm'] != PITCH_NM or result['opening_diameter_nm'] != 35000 or result['opening_spacing_nm'] != 40000 or result['landing_diameter_nm'] != 50000:
        raise ValueError('Attachment contract mismatch')
    if len(result['chips']) != len(expected):
        raise ValueError('Missing chip')
    seen = set(); summary = []
    for chip in result['chips']:
        i = chip['id']
        if i in seen or not 0 <= i < len(expected):
            raise ValueError('Invalid chip identity')
        seen.add(i); source = domain['chiplets'][i]
        w,h = source['core_width_um']*1000,source['core_height_um']*1000
        nx,ny = (w+PITCH_NM-1)//PITCH_NM,(h+PITCH_NM-1)//PITCH_NM
        rows = chip['ring_rows']; width,height = chip['width_nm'],chip['height_nm']
        if type(rows) is not int or rows < 1 or (width,height) != ((nx+2*rows)*PITCH_NM,(ny+2*rows)*PITCH_NM):
            raise ValueError('Envelope mismatch')
        if (chip['core_width_nm'],chip['core_height_nm'],chip['core_x_nm'],chip['core_y_nm'],chip['core_power_w']) != (w,h,(width-w)//2,(height-h)//2,source['power_w']):
            raise ValueError('Source core changed')
        if rows > 1 and signal_capacity(nx,ny,rows-1) >= len(expected[i]):
            raise ValueError('Ring not minimal')
        sites = set(); actual = Counter(); counts = Counter()
        for pad in chip['pads']:
            x,y = pad['x_nm'],pad['y_nm']
            if type(x) is not int or type(y) is not int or (x%PITCH_NM,y%PITCH_NM) != (PITCH_NM//2,)*2:
                raise ValueError('Off-lattice pad')
            if (x,y) in sites:
                raise ValueError('Duplicate pad')
            sites.add((x,y))
            if not (25000 <= x <= width-25000 and 25000 <= y <= height-25000):
                raise ValueError('Landing outside die')
            cx,cy = x//PITCH_NM,y//PITCH_NM
            if rows <= cx < rows+nx and rows <= cy < rows+ny:
                raise ValueError('Pad inside core')
            role = pad['role']; counts[role] += 1
            if (cx+cy)%2:
                if role != 'reserved_pdn':raise ValueError('PDN reservation lost')
            elif role not in ('signal','unpopulated'):
                raise ValueError('Invalid signal-site role')
            if role == 'signal':
                actual[(tuple(pad['wire']),pad['direction'])] += 1
            elif 'wire' in pad or 'direction' in pad:
                raise ValueError('Non-signal carries a conductor')
        if len(sites) != (nx+2*rows)*(ny+2*rows)-nx*ny:
            raise ValueError('Incomplete ring')
        if actual != Counter((tuple(t['wire']),t['direction']) for t in expected[i]):
            raise ValueError('Conductor endpoint coverage mismatch')
        summary.append(dict(id=i,ring_rows=rows,width_um=width/1000,height_um=height/1000,
                            core_power_w=chip['core_power_w'],sites_by_role=dict(counts)))
    return dict(case=domain['name'],status='attachment_geometry_and_endpoint_identity_verified',
                minimum_all_site_distance_um=75,minimum_opening_gap_um=40,
                landing_edge_clearance_um=12.5,chips=summary,
                physical_qualified=False,phy_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    geometry=source_bytes('docs/evidence/tap-geometry-domains.json')
    contract=source_bytes('docs/tap-ihp-endpoint-contract.md')
    admission=source_bytes('docs/evidence/ihp-tap-attachment-audit.json')
    source_method=next(m for m in json.loads(admission)['methods'] if m['method']=='cupillar_opt1')
    if (source_method['opening_um'],source_method['spacing_um']) != (35,40):
        raise ValueError('Source attachment rules changed')
    reports=[]
    for entry in json.loads(geometry)['cases']:
        domain=entry['domain']; result=build(domain)
        path=args.output/f"{domain['name']}.json"
        path.write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
        report=verify(domain,json.loads(path.read_text(encoding='utf-8')))
        report.update(artifact=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        reports.append(report)
    evidence=dict(source_hash_convention='UTF-8 text with CRLF normalized to LF; artifact hashes use original bytes',
                  geometry_sha256=hashlib.sha256(geometry).hexdigest(),
                  contract_sha256=hashlib.sha256(contract).hexdigest(),
                  attachment_audit_sha256=hashlib.sha256(admission).hexdigest(),cases=reports)
    with args.evidence.open('x',encoding='utf-8') as f:
        json.dump(evidence,f,indent=2);f.write('\n')
    print(json.dumps([dict(case=r['case'],chips=len(r['chips'])) for r in reports]))


if __name__=='__main__':main()
