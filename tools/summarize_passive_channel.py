"""Verify archived channel evidence and emit a compact, bounded interpretation."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from validation.sources import write_json
from validate_passive_channel import finest_records


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def summarize(root):
    report = json.loads((root / 'report.json').read_text())
    rows = report['records']
    verified = []
    for row in rows:
        directory = root / row['name']
        if json.loads((directory / 'measurement.json').read_text()) != row:
            raise ValueError(f'measurement/report mismatch: {directory}')
        for filename, field in [('deck.sp', 'deck_sha256'), ('ngspice.log', 'log_sha256'),
                                ('endpoints.npz', 'endpoints_sha256'), ('waveform.txt.gz', 'waveform_gzip_sha256')]:
            if row.get(field) and sha(directory / filename) != row[field]:
                raise ValueError(f'archive changed: {directory / filename}')
        if row.get('waveform_sha256'):
            with gzip.open(directory / 'waveform.txt.gz', 'rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['waveform_sha256']:
                    raise ValueError(f'lossless archive mismatch: {directory}')
        if row.get('waveform_sha256'):
            verified.append(row['name'])
    fine = finest_records(rows)
    complete = [x for x in rows if x['completed']]
    frequency = report['frequency']
    fine_frequency = [x for x in frequency if x['segments'] == 32]
    refinements = report['refinement']
    controls = next((x['negative_controls'] for x in fine if 'negative_controls' in x), {})
    effects = report['channel_effects']
    for e in effects:
        e['rlc_minus_rc_delay_ps'] = {edge: None if e['rlc_delay_ps'][edge] is None or e['rc_delay_ps'][edge] is None else e['rlc_delay_ps'][edge]-e['rc_delay_ps'][edge] for edge in ('rise', 'fall')}
        e['rlc_minus_rc_skew_ps'] = {edge: None if e['same_edge_skew_ps']['RLC'][edge] is None or e['same_edge_skew_ps']['RC'][edge] is None else e['same_edge_skew_ps']['RLC'][edge]-e['same_edge_skew_ps']['RC'][edge] for edge in ('rise', 'fall')}
        e['conditional_setup_contribution_ps'] = {edge: None if x is None else -x for edge, x in e['rlc_minus_rc_skew_ps'].items()}
        e['conditional_hold_contribution_ps'] = dict(e['rlc_minus_rc_skew_ps'])
    scalar = lambda key: [abs(x) for e in effects for x in e[key].values() if x is not None]
    counts = dict(requested_records=96, new_runs=len(rows)-len(report.get('reused', [])),
                  reused_runs=len(report.get('reused', [])), completed=len(complete), waveform_archives_verified=len(verified),
                  numerical_gates_passed=sum(x['numerical_gates_passed'] for x in rows),
                  fine_numerical_gates_passed=sum(x['numerical_gates_passed'] for x in fine),
                  temporal_passed=sum(x.get('temporal', {}).get('passed', False) for x in refinements),
                  spatial_passed=sum(x.get('spatial', {}).get('passed', False) for x in refinements),
                  frequency_cascade_passed=sum(x['algebraic_passed'] for x in frequency),
                  fine_frequency_sampled_passed=sum(x['continuum_sampled_passed'] for x in fine_frequency),
                  fine_scalar_unambiguous=sum(all(x['crossings'][e]['scalar_unambiguous'] for e in ('rise', 'fall')) for x in fine),
                  negative_controls_detected=sum(x['detected'] for x in controls.values()))
    limits = ['Constructed constant-RLGC channel; no independently calibrated electromagnetic model.',
              'External L only; return/internal/skin/proximity/dielectric loss, bumps and coupling omitted.',
              'Thevenin driver and constant receiver capacitance are declared assumptions, not actual pad dynamics.',
              'Five frequency samples do not certify a band or bound transient error.',
              'Refinement differences are empirical screens, not rigorous error bounds.',
              'Same-edge channel skew only; real PHY setup/hold, temperature feedback and optimizer admission remain open.']
    maxima = dict(charge=max(x['ledger']['normalized_max_residual']['charge'] for x in complete),
                  local_charge=max(x['ledger']['normalized_max_residual']['local_charge'] for x in complete),
                  energy=max(x['ledger']['normalized_max_residual']['energy'] for x in complete),
                  oracle_endpoint_error_v=max(x['oracle_endpoint_max_error_v'] for x in complete),
                  oracle_crossing_error_ps=max(x['oracle_crossing_max_error_ps'] for x in complete if x['oracle_crossing_max_error_ps'] is not None),
                  temporal_metric_change_ps=max(m['difference_ps'] for x in refinements for m in x.get('temporal', {}).get('metrics', [])),
                  spatial_metric_change_ps=max(m['difference_ps'] for x in refinements for m in x.get('spatial', {}).get('metrics', [])),
                  fine_frequency_absolute_error=max(y['continuum_absolute_error'] for x in fine_frequency for y in x['records']),
                  algebraic_frequency_absolute_error=max(y['algebraic_absolute_error'] for x in frequency for y in x['records']),
                  rlc_minus_rc_delay_absolute_ps=max(scalar('rlc_minus_rc_delay_ps'), default=None),
                  rlc_minus_rc_skew_absolute_ps=max(scalar('rlc_minus_rc_skew_ps'), default=None))
    return dict(scope='ideal same-geometry RC/RLC mechanism comparison', counts=counts, maxima=maxima,
                physical_model_qualified=False, real_phy_timing_qualified=False, limitations=limits,
                input_report_sha256=sha(root / 'report.json'),
                frozen_inputs=report['frozen_inputs'], refinements=refinements,
                fine_frequency=fine_frequency, channel_effects=effects,
                negative_controls=controls, fine_records=fine,
                failed_numerical_runs=[x['name'] for x in rows if not x['numerical_gates_passed']],
                waveform_archive_bytes=sum(x.get('waveform_gzip_bytes', 0) for x in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.input)
    write_json(args.output, summary)
    print(json.dumps({k: summary[k] for k in ('counts', 'maxima', 'failed_numerical_runs')}, indent=2))


if __name__ == '__main__':
    main()
