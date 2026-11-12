"""Build source pad cells and check a bounded local-access geometry subset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import klayout.db as db
from build_tap_ihp_endpoints import source_bytes,verify as verify_endpoints
from freeze_tap_ihp_geometry import placed_pad,geometry_proxy
from freeze_tap_geometry import verify as verify_placement


LAYERS={'opening':(9,35),'tm2':(134,0),'tm1':(126,0),'m5':(67,0),'tv2':(133,0),'tv1':(125,0)}


def units():
    from bump_mirror import CuPillarGenerator,BumpLocation
    generator=CuPillarGenerator()
    generator.add_bumps([BumpLocation('UNIT','PAD',0,0)],body_diameter_um=44)
    layout=generator.layout;pad=generator.top_cell;pad.name='PAD_UNIT'
    access=layout.create_cell('SIGNAL_ACCESS')
    access.insert(db.CellInstArray(pad.cell_index(),db.Trans()))
    for layer,rect in [('tv2',(-450,-450,450,450)),('tv1',(-210,-210,210,210)),
                       ('tm1',(-950,-950,37500,950)),('m5',(-310,-310,310,37500))]:
        access.shapes(layout.layer(*LAYERS[layer])).insert(db.Box(*rect))
    return layout,pad,access


def regions(layout,cell):
    return {name:db.Region(cell.begin_shapes_rec(layout.layer(*pair))).merged() for name,pair in LAYERS.items()}


def circle_signature(polygon):
    centre=polygon.bbox().center()
    return tuple((p.x-centre.x,p.y-centre.y) for p in polygon.each_point_hull())


def check(layout,cell,expected_signals,expected_pads,circle_templates):
    r=regions(layout,cell);findings={}
    for layer,space in [('opening',39990),('tm2',2000),('tm1',1640),('m5',210),('tv2',1060),('tv1',420)]:
        findings[f'{layer}_space']=r[layer].space_check(space).count()
    for layer,width in [('tm1',1640),('m5',200)]:
        findings[f'{layer}_width']=r[layer].width_check(width).count()
    for outer,inner,distance in [('tm2','opening',7490),('tm2','tv2',500),('tm1','tv2',500),
                                  ('tm1','tv1',420),('m5','tv1',100)]:
        findings[f'{outer}_encloses_{inner}']=r[outer].enclosing_check(r[inner],distance).count()
        findings[f'{inner}_outside_{outer}']=(r[inner]-r[outer]).count()
    for layer,width in [('tv2',900),('tv1',420)]:
        findings[f'{layer}_cut_shape']=sum(p.bbox().width()!=width or p.bbox().height()!=width or p.area()!=width*width for p in r[layer].each())
        findings[f'{layer}_count']=int(r[layer].count()!=expected_signals)
    findings['opening_count']=int(r['opening'].count()!=expected_pads)
    # With one cut of each type at each signal and a connected stub on each
    # lower layer, these containment checks witness the local conductive chain.
    findings['tm1_component_count']=int(r['tm1'].count()!=expected_signals)
    findings['m5_component_count']=int(r['m5'].count()!=expected_signals)
    offgrid=0;exempt=0
    for layer in ('tm2','opening','tm1','m5','tv1','tv2'):
        for polygon in r[layer].each():
            if layer in circle_templates and circle_signature(polygon)==circle_templates[layer]:
                # Narrower than the PDK get_circle exemption: only exact
                # translated copies of the source-generated circles qualify.
                exempt+=1
                continue
            offgrid+=sum(v.x%5!=0 or v.y%5!=0 for v in polygon.each_point_hull())
    findings['vertices_off_5nm_grid']=offgrid
    return dict(status='local_geometry_subset_passed' if not any(findings.values()) else 'local_geometry_subset_failed',
                findings=findings,signal_count=expected_signals,pad_count=expected_pads,
                source_circle_grid_exemptions=exempt,
                full_fabrication_drc=False,global_routed=False,pdn_connected=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--endpoints',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    os.environ['INTERCONNECT_PDK_ROOT']=str(Path('local/upstream/IHP-Interconnect-IntM4TM2').resolve())
    sys.path.insert(0,str((args.runtime/'libs.tech/klayout/python').resolve()))
    layout,pad,access=units();tile=layout.create_cell('NEIGHBOUR_TILE')
    circle_templates={name:circle_signature(next(regions(layout,pad)[name].each())) for name in ('tm2','opening')}
    for x in (-75000,0,75000):
        for y in (-75000,0,75000):tile.insert(db.CellInstArray(access.cell_index(),db.Trans(x,y)))
    path=args.output/'local-tile.gds';layout.write(str(path))
    reread=db.Layout();reread.read(str(path))
    tile_report=check(reread,reread.cell('NEIGHBOUR_TILE'),9,9,circle_templates)
    # A broken cut enclosure must fail the same checker after a GDS-independent mutation.
    broken=db.Layout();broken.read(str(path));broken.cell('SIGNAL_ACCESS').shapes(broken.layer(*LAYERS['tv1'])).clear()
    broken.cell('SIGNAL_ACCESS').shapes(broken.layer(*LAYERS['tv1'])).insert(db.Box(790,-210,1210,210))
    negative=check(broken,broken.cell('NEIGHBOUR_TILE'),9,9,circle_templates)
    if negative['status']!='local_geometry_subset_failed':raise ValueError('Displaced via negative control accepted')
    result=dict(klayout_version=db.__version__,local_tile=tile_report,displaced_via_negative=negative,
                runtime_patch=json.loads((args.runtime/'windows-path-fix.json').read_text()),cases=[])
    if tile_report['status']=='local_geometry_subset_passed':
        source=json.loads(source_bytes('docs/evidence/tap-geometry-domains.json'))['cases']
        geometry=json.loads(source_bytes('docs/evidence/tap-ihp-geometry.json'))['cases']
        manifests=json.loads(source_bytes('docs/evidence/tap-ihp-endpoints.json'))['cases']
        for entry,placement_record,manifest in zip(source,geometry,manifests,strict=True):
            raw=(args.endpoints/manifest['artifact']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('Endpoint digest mismatch')
            endpoints=json.loads(raw);verify_endpoints(entry['domain'],endpoints)
            placement=placement_record['witness']['placement']
            verify_placement(geometry_proxy(entry['domain'],endpoints),placement)
            ly,pa,ac=units();top=ly.create_cell('ASSEMBLY_ACCESS');signals=0;populated=0;expected_instances={};access_map=[]
            for chip,placed in zip(endpoints['chips'],placement,strict=True):
                for terminal in chip['pads']:
                    if terminal['role']=='unpopulated':continue
                    x,y=placed_pad(chip,placed,terminal)
                    signal=terminal['role']=='signal';signals+=signal;populated+=1
                    top.insert(db.CellInstArray((ac if signal else pa).cell_index(),db.Trans(x,y)))
                    if (x,y) in expected_instances:raise ValueError('Coincident assembly pads')
                    expected_instances[x,y]='SIGNAL_ACCESS' if signal else 'PAD_UNIT'
                    if signal:access_map.append(dict(chip_id=chip['id'],wire=terminal['wire'],direction=terminal['direction'],
                                                     pad_nm=[x,y],tm1_port_nm=[x+37500,y],m5_port_nm=[x,y+37500]))
            path=args.output/f"{entry['domain']['name']}.gds";ly.write(str(path))
            reread=db.Layout();reread.read(str(path))
            saved_top=reread.cell('ASSEMBLY_ACCESS');actual_instances={}
            for instance in saved_top.each_inst():
                transform=instance.trans
                if transform.angle or transform.is_mirror():raise ValueError('Access cell was rotated/mirrored')
                key=(transform.disp.x,transform.disp.y)
                if key in actual_instances:raise ValueError('Duplicate GDS access instance')
                actual_instances[key]=reread.cell(instance.cell_index).name
            if actual_instances!=expected_instances:raise ValueError('GDS instances do not match endpoint identities')
            report=check(reread,saved_top,signals,populated,circle_templates)
            map_path=args.output/f"{entry['domain']['name']}-access-map.json"
            map_path.write_text(json.dumps(access_map,separators=(',',':')),encoding='utf-8')
            report.update(identity_matched_gds_instances=len(actual_instances),
                          access_map_sha256=hashlib.sha256(map_path.read_bytes()).hexdigest())
            report.update(case=entry['domain']['name'],gds_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            result['cases'].append(report)
            print(report['case'],report['status'],flush=True)
    result['contract_sha256']=hashlib.sha256(source_bytes('docs/tap-ihp-local-access-contract.md')).hexdigest()
    (args.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(tile_report),flush=True)


if __name__=='__main__':main()
