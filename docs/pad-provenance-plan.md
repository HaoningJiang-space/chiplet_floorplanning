# Pad source provenance and revision controls

Frozen before new pad transient execution, 2026-11-11. Start: local `50046cb`,
successful fetch, remote `c124aa9`, no new remote commits. Local experiments only.

Trace the original characterization contract before changing models. In the
audited snapshots, SKY's library names HSPICE H-2013.03 and `snps_predriver`,
but neither label specifies a complete stimulus/PEX/load contract. GF's public
issue 11 distinguishes its LVS CDL from a simulation netlist. Neither platform
has an established original characterization netlist/PEX mapping here.

One source-supported correction warrants a controlled experiment before further
waveform sweeps: open_pdks commit `11af1927` explicitly corrects two pFET `m`
values in `hvsbt_nor`; later `2d935092` supplies the full corrected IO source.
Its GPIO reachable definitions differ from the installed source in exactly
three blocks, also agreeing with the corresponding blocks of SKY IO PR5.

## Frozen experiment

- Preserve all original model and Liberty files. Copy only named upstream
  definitions into separate derived files, with source/derived SHA-256 receipts.
- Variants: `nor_only`; `reachable_updates` (NOR plus `gpiov2_ctl_hld` and
  `top_gpiov2`). This does not isolate the two resistor changes from one another.
- Three existing SKY RX configurations: nominal (1 ns, 0.022799 pF), actual-STA
  rise anchor (0.630287647 ns, 0.014307999 pF), fall anchor
  (0.607017577 ns, 0.01297 pF). Each run measures both transitions.
- Keep 25 C, TT, 1.8/3.3 V supplies, control pins, load, linear input waveform,
  50% crossings, 20–80% slew, measurement code and ngspice 42 binary fixed.
- Run both variants at 5/2.5 ps maximum steps: 12 new transients. Reuse six
  baseline runs only after byte-hash, simulator/model identity, exact generated
  baseline deck and repeated source-defined measurement checks.
- Archive internal `net16` waveforms for all ten reachable NOR instances.
  Their range alone does not prove causal participation or absence thereof.
- Retain the previous halfstep screen max(2 ps, 0.5%) and four-metric nominal
  comparison max(20 ps, 10%). Report signed changes and each pair's observed
  endpoint step changes; neither is a physical error bound.
- Separately probe the actual model's `m`/`mult` semantics and resistor L/W
  response. Textual differences alone are insufficient evidence of behavior.

No offsets, fitted loads, hot-pad tables, lane error bounds or hardware claims.
Missing original PEX/stimulus remains a dependency even if nominal agreement
improves. Source provenance investigation is bounded to explicitly recorded
snapshots, archives and commit histories, not a claim of global nonexistence.
