"""Independent whole-deck contract for the frozen cold-to-hot fabric export."""
from collections import Counter
import hashlib
from pathlib import Path


def hot_model_root(output):
    return Path(__file__).resolve().parents[2]/'local'/(
        'xt-'+hashlib.sha256(str(Path(output).resolve()).encode()).hexdigest()[:8])


def verify_hot_deck(cold_text, hot_text, hot_elements, output):
    """Permit only declared model references, temperature cells and hot RC.

    The caller independently derives and checks hot_elements against STA/SPEF.
    All other lines, including supplies, stimuli and solver/output controls,
    must survive unchanged. Match the export's physical-element relocation.
    """
    output = Path(output)
    lines = cold_text.splitlines()
    if lines.count('.end') != 1 or sum(l.startswith('.lib ') for l in lines) != 1:
        raise ValueError('unexpected cold deck structure')
    names = [Path(l.split('"')[1]).name for l in lines if l.startswith('.include ')]
    if Counter(names) != Counter(['buf_8.spice', 'inv_1.spice', 'dfxtp_1.spice']):
        raise ValueError('unexpected cold cell include domain')
    expected = []
    for line in lines:
        if line.startswith(('X_', 'R_', 'C_')):
            continue
        if line.startswith('.lib '):
            line = f'.lib "{(hot_model_root(output)/"libs.tech/ngspice/sky130.lib.spice").as_posix()}" tt'
        elif line.startswith('.include '):
            name = Path(line.split('"')[1]).name
            line = f'.include "{(output/name).resolve().as_posix()}"'
        if line == '.end':
            expected.extend(hot_elements)
        expected.append(line)
    if hot_text.splitlines() != expected:
        raise ValueError('hot deck changed stimulus, supply, controls, model references or declared fabric')

