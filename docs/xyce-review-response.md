# Response to the Chat review through 4c6f3cf

The external read-only GitHub review identified observation-column identity,
structured execution failures and warning inventory as concrete validation
gaps. These are fixed without changing the physical circuit or production STA.

- Xyce waveform readers now require the complete CSV header to match TIME and
  the expected voltage/current names in exact order. Same-shaped reordered or
  duplicated headers are rejected. A header check cannot detect maliciously
  relabeled data; saved waveform hashes remain necessary.
- The actual-cell temperature probe writes `complete=false`, a failed
  forwarding status, case identity, execution status and deck/log hashes when
  execution times out or exits nonzero. Partial logs remain on disk.
- Warning messages are retained and classified. New/unrecognized warning
  messages prevent the forwarding experiment from passing. Known model-version,
  junction and conductance warnings remain explicit implementation differences;
  their physical harmlessness is never asserted.

Six new regression tests cover reordered/duplicate headers, valid columns,
partial timeout output, nonzero exit and changed warning type with equal count.
Both failure types were also injected through the actual probe entry point;
its structured incomplete reports were inspected. Existing eighteen cell
experiments and both complete-fabric time steps passed retrospective header
checks. The cell logs contained only the declared warning categories. A new
six-case inverter run passed the strengthened checks. These replays do not
constitute new physical measurements.

[Compact failure/header evidence](evidence/local-xyce-review-controls.json).
The full 221-test suite and documented two-chiplet CLI passed.

The review's additional decision-baseline concern remains open: electrical
admissibility cost must be separated from pure timing cost before interpreting
positive temperature penalties. The four previously reported zero-cost cases
do not resolve that general distinction. Likewise, whole-fabric uniform hot
controls, multiple-layout thermal interaction and receiver setup/hold
characterization remain outstanding; single-cell temperature equivalence is
not a substitute for those acceptance items.
