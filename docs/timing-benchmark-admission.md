# Timing-critical benchmark admission, v0.7

**No timing-critical physical benchmark is admitted yet.** The 20 ns GPIO
period remains a demonstration control. A smaller period chosen from the
observed slack would manufacture the requested bottleneck rather than establish
an application requirement. Negative setup in the existing 2 ns unit/prototype
control only checks failure reporting.

## Sources reviewed

| Candidate | Traceable evidence | Admission decision |
| --- | --- | --- |
| Current GF180 TX → SKY130 RX GPIO lane | Real TT25 pad/core Liberty, explicit voltage/mode/load constraints; synthetic endpoint circuit and 20 ns requirement | Useful geometry control; no workload/protocol-derived pressure; v0.6 nominal SPICE agreement also failed |
| PULP `serial_link` | Pinned original RTL and README already in `tools/sources.lock.json`; parameterized source-synchronous interface and CDC | Existing transport test uses locally selected clocks. It has not been mapped into the GPIO timing lane; its testbench periods are not a specification |
| Basilisk / `cheshire-ihp130-o` | Published silicon results plus pinned IHP backend SDC, instance selectors and post-CTS constraints | Stronger candidate for a subsequent endpoint implementation; not a drop-in constraint for two other PDKs, and not yet demonstrated timing-critical across a package |

The [PULP README](https://github.com/pulp-platform/serial_link) describes
parameterized SDR/DDR operation and a forwarded TX clock divided from the
system clock. Its flexibility does not define one mandatory physical frequency.

The [Basilisk silicon paper, arXiv:2505.10060v1](https://arxiv.org/html/2505.10060v1)
reports an IHP 130 nm SoC, 62 MHz operation at nominal 1.2 V, and a 62 Mb/s C2C
link. A measured core frequency is not a package-path timing requirement.
Aggregate link throughput cannot be converted into a lane clock without the
lane count, DDR/SDR mode and divider configuration.

## Concrete SDC audit

Reference commit: `560f00f1c14a7f2f22861df6bb4816eacf7f2e7e`.
Four source files are SHA-256 locked and downloaded by
`tools/bootstrap_validation.py` into `local/open-cases/basilisk-reference/`.
They are read-only admission references, not constraints executed by our lane.
This repository snapshot is not asserted to be the paper's tapeout revision.

In the pinned [basilisk.sdc](https://github.com/pulp-platform/cheshire-ihp130-o/blob/560f00f1c14a7f2f22861df6bb4816eacf7f2e7e/target/ihp13/openroad/src/basilisk.sdc):

- The executable system period is 11 ns (about 90.9 MHz), despite a nearby
  comment referring to 80 MHz. Neither should be replaced by the paper's
  measured silicon frequency; these are different evidence items.
- The incoming serial-link period is four system periods, hence 44 ns in
  this snapshot. Generated TX data/forwarded clocks use distinct edge lists
  with a quarter-cycle phase relation. This differs from the current GPIO
  demonstration's half-cycle sampling contract.
- Serial outputs have 4–16 pF loads. Clock uncertainty is 0.1 ns. Separate
  rising/falling input/output delays and setup/hold exceptions are present.
- Pin selection is tied to the synthesized hierarchy in `basilisk_instances.sdc`;
  the post-CTS file propagates clocks. Copying only the period loses this contract.

These source details identify what must be reproduced; they do not establish
that the upstream C2C path is timing-critical. The pinned SDC's load assumptions
also do not qualify the GF180/SKY130 GPIO pads at those loads.

## Next admission artifact

1. Freeze an endpoint RTL/configuration and its dependency versions, operating
   mode, lane count, divider and workload requirement. Trace required edges and
   uncertainty to the implementation specification.
2. Reproduce its real mapped endpoint and pad constraints in the **same PDK**,
   including min/max loads, clock generation, clock trees and path exceptions.
   Check every selected pin and that the intended capture paths remain timed.
3. Connect two endpoints through an explicitly qualified package/channel model;
   compare expansion of data and capture-clock paths against the local reference.
4. At the unchanged justified requirement, determine whether thermal-optimal
   placement actually violates setup/hold. A feasible outcome is valid evidence
   against necessity in that operating regime, not a reason to retune frequency.

Steps 1–4 are pending implementation. No Basilisk synthesis, IHP timing result,
full-PVT qualification or hot-pad result is claimed by this admission review.
