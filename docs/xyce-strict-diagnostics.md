# Strict diagnostic identity and rejected-observation records

Starting main was `c40c3687082da6c60af236c0ab1bb5c6bd26176a`; origin was
successfully fetched with no divergence. This stage addresses the remaining
Chat findings about warning-prefix/substring acceptance and missing records
when a successful process produces an invalid observation.

The actual-cell probe now scans warning markers without assuming a particular
prefix or case. Only complete whitespace-normalized messages from the observed
Netlist diagnostic families enter its allowlist. A recognized phrase followed
by an extra diagnostic is rejected. Unknown prefixes and the simulator's
warning-suppression message are rejected too. This is conservative parsing of
declared diagnostics, not a proof that arbitrary undocumented log formats are
understood. Known model substitutions are not declared physically harmless.

After execution, missing output, mismatched CSV headers, nonfinite waveforms
and measurement failures produce `invalid_observation`. The report retains
case identity, exception type and reason, hashes of all available artifacts,
`complete=false` and `forwarding_controls_pass=false`; it then propagates the
error. Earlier successful cases remain in the incomplete report.

## Newly exposed warning suppression

The stricter scan found `Maximum warning count has been exceeded and will no
longer be displayed` in all old buffer/flip-flop controls and in the cold/hot
complete-fabric logs. Therefore the earlier statement that those logs contained
only known warnings was too strong: displayed model warnings were known, but
the rest were suppressed. This does not establish that an undisplayed warning
changed the circuit; it does mean complete diagnostic admission was unproven.

The shared probe executor now uses the local executable's documented
`-max-warnings 100000` option. This changes logging only. If the new limit is
reached, the scanner still rejects the suppression notice. Twelve local
controls were rerun with unchanged circuits and stimuli:

| Cell | Cases | Warnings per case | Unknown/suppressed diagnostics | Metric change from prior runs |
|---|---:|---:|---:|---:|
| buf_8 | 6 | 177 | 0 | 0 ps |
| dfxtp_1 | 6 | 193 | 0 | 0 ps |

Both temperature-forwarding controls pass. Existing inverter logs also pass
strict replay. The full cold/hot fabric was **not** rerun merely for this patch;
its historical waveform differences remain numerical diagnostics with incomplete
warning coverage. Future full-fabric uniform and layout comparisons must use
complete logs before making a stronger model-admission claim. The stricter
gate currently applies to the actual-cell probe; other diagnostic entry points
still need consistent execution/observation failure accounting and admission.

[Compact evidence](evidence/local-xyce-strict-diagnostics.json) includes complete
normalized diagnostic counts for every new control, exact metric comparisons,
receipt/log hashes, and the old suppression findings. Raw logs remain local.

## Validation

New negative cases reject a known substring with an extra diagnostic, unfamiliar
warning prefixes, and suppressed diagnostics. Wrapped known messages are
accepted only after exact normalization. Observation tests verify structured
failure for missing CSV, wrong headers and nonfinite values. Both affected test
files now configure their tool import path and run independently (10 and 5
tests); this no longer depends on discovery order. The full suite passed 228
tests and the documented two-chiplet CLI passed locally.

This closes these two probe implementation gaps locally, pending another Chat
closure review. It does not close full-fabric uniform controls, multi-layout
temperature interactions, physical receiver constraints or real package/Pad
qualification. Goal 01 remains active.
