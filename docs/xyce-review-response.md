# Response to the Chat review through 4c6f3cf

The external read-only GitHub review identified observation-column identity,
structured execution failures and warning inventory as concrete validation
gaps. The first two are fixed; warning classification is an initial partial
fix, as confirmed by the follow-up review below. The physical circuit and
production STA are unchanged.

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

## Follow-up Chat verdict on b5ac635

The existing Chat review session confirmed reading commit
`b5ac635f42f92416cc19019021dd2f7c30b57958` and its seven-file patch via GitHub.
It accepted the header and timeout/nonzero-exit fixes, but marked warning
classification only partially closed. Specific remaining items are:

- Scan all diagnostic prefixes and use complete normalized-message matching;
  the current Netlist-warning prefix and keyword-substring rules are too narrow.
- Persist `invalid_observation` when execution succeeds but header or waveform
  validation fails. Other Xyce entry points also need consistent failure records.
- Keep the electrical-versus-incremental-timing cost baseline issue open.
- Make new tests independently importable instead of depending on another
  discovered test modifying `sys.path`.

The review inspected GitHub code and compact evidence, not local waveforms or
test execution. Its closure does not constitute independent physical replication.

Subsequent local fix: [cost baseline version 2](decision-cost-baselines.md)
now separates electrical, incremental timing and combined routing-to-timing
costs and replays the frozen benchmark. This implementation has not yet
received a new Chat closure review; the remaining warning/observation items
above are unchanged.

Further local follow-up: [strict diagnostic handling](xyce-strict-diagnostics.md)
replaces warning substring admission, records invalid observations, and fixes
independent test imports. It also exposes previously suppressed warnings;
the old statement that every cell log contained only known diagnostics must
be limited to the displayed messages. New complete buffer/flip-flop control
logs are available, while old full-fabric diagnostic coverage remains incomplete.
