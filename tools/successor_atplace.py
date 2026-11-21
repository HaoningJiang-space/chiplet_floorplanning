"""Cold-start the pinned author's trainer and warm-start its placer at the shared coordinates."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np

from atplace_compare import from_atplace
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from chiplet_floorplanning.placement.search import layout_key
from chiplet_floorplanning.placement import thermal_projection
from compare_atplace_margin import write
from compare_successors import ROOT, audit, measure, result, shared_repair
from import_atplace_cases import PIN


def external_arm(p,start,reach,cap,base,encoded,args):
    upstream = args.upstream.resolve()
    assert subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()==PIN
    sub = (args.work/p.name).resolve()
    sub.mkdir(parents=True,exist_ok=False)
    (sub/'source.json').write_bytes(encoded)
    write(sub/'input.json', dict(name=p.name,cap_m=cap,names=p.names,start_um=start.centre_um.tolist(),
          angles=start.rotation_deg.tolist(),powers_w=p.power_w.tolist(),source_sha256=sha256(encoded).hexdigest(),
          upstream=PIN,fv_fingerprint=sha256(Path(thermal_projection.__file__).read_bytes()).hexdigest()))
    extra = []
    if p.name in ('Stagger12','Stagger12P'):
        params = json.loads((upstream/'cases/Case7/Thermal-aware.json').read_bytes())
        params['opt']['case_dir'] = str((ROOT/'examples'/p.name).resolve())
        write(sub/'params.json',params)
        extra = ['--param-file',str(sub/'params.json')]
    stages = {}
    for phase in ('train','shared'):
        t = perf_counter()
        cmd = [str(args.atpython.resolve()),str(ROOT/'tools/atplace_shared_fv.py'),str(upstream),
               str(sub),phase,sys.executable,'--projected-labels','--native-limit-s','30',*extra]
        log = sub/f'{phase}.log'
        with log.open('w',encoding='utf8') as handle:
            code = subprocess.run(cmd,stdout=handle,stderr=subprocess.STDOUT).returncode
        stages[phase] = dict(exit=code,seconds=perf_counter()-t)
        if code:
            stages[phase]['error'] = log.read_text(encoding='utf8',errors='replace').strip().splitlines()[-1]
            if phase=='train':
                break
    rows, handling = [base], 'no target'
    labels_file = sub/'labels.npy'
    labels = len(np.load(labels_file,mmap_mode='r')) if labels_file.exists() else 0
    raw_row = None
    chosen = None
    cell = PinReachCell(p,start,100,reach,cap)
    if (sub/'shared.json').exists():
        pose = from_atplace(p,json.loads((sub/'shared.json').read_bytes()))
        chosen,raw_row,handling = shared_repair(p,pose,cell,reach,cap)
    elif 'shared' in stages:
        model_id = sha256((sub/'shared-fv.pt').read_bytes()).hexdigest()
        target_file = sub/f'shared-before-legalization-{model_id}.npz'
        if target_file.exists():
            terminal = np.load(target_file)
            names = np.load(sub/'sampled.npz')['names'].tolist()
            order = [names.index(name) for name in p.names]
            xy = np.c_[terminal['x'],terminal['y']][order]
            # Pre-legal coordinates have no legal exported rotation. Project positions
            # with the common-start orientations, retaining the original target for audit.
            chosen = cell.toward(xy)
            raw_row = dict(prelegal_xy_um=xy.tolist())
            handling = 'projected pre-legalization target'
    if chosen is not None:
        if not audit(p,chosen,reach,cap)['admitted']:
            chosen = None
    if chosen is not None:
        halfway = cell.toward((start.centre_um+chosen.centre_um)/2)
        seen = {layout_key(start)}
        for origin,pose in [(handling,chosen),('halfway in start cell',halfway)]:
            if pose is None or layout_key(pose) in seen:
                continue
            seen.add(layout_key(pose))
            row = audit(p,pose,reach,cap)
            if row['admitted']:
                rows.append(dict(measure(p,pose,row),origin=origin))
    training = sub/'training.json'
    return dict(result(rows,base,len(rows)-1),stages=stages,reduced_labels=labels,
                training=json.loads(training.read_bytes()) if training.exists() else None,
                raw=raw_row,handling=handling)
