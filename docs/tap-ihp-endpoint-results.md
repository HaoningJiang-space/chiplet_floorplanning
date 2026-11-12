# Constructive attachment geometry and independent placement witnesses

Following the incompatible-source result, the frozen
[endpoint contract](tap-ihp-endpoint-contract.md) constructs a new mechanism
family with explicit terminal identities and PDN reservations. This is the
alternative of redesigning endpoints, not claiming an existing TAP product
uses IHP attachment or has a compatible PHY. The geometry contracts were written
before their respective generation/search runs. No temperature or route score
selected any parameter.

## Local construction and replay

| Source family | Dies | Signal endpoints | Reserved PDN sites | Unpopulated even sites | Whole-system geometry |
| --- | ---: | ---: | ---: | ---: | --- |
| Ascend910 | 6 | 4,896 | 5,336 | 440 | witnessed |
| Micro150 | 8 | 20,480 | 22,384 | 1,904 | witnessed |
| MultiGPU | 6 | 13,824 | 15,360 | 1,536 | witnessed |

Each original conductor has exactly one source and one target identity; endpoint
counts are twice the directed source wire totals. All 20 original core sizes and
powers are retained. The 50% checkerboard reservation is a declared design policy,
not measured PHY/PDN data. Reserved sites have no invented rail current or voltage.

Every map was saved, reloaded, and independently checked for unique integer
lattice sites, envelope/core containment, PDN reservations, exact conductor
coverage, unchanged power and minimum ring rows. Distinct lattice sites have
at least 75 um centre separation and 40 um nominal opening gap. The 50 um landing
envelope stays at least 12.5 um from die edges. These are geometric envelopes,
not fabricated solid-metal pad artwork or a substitute for the PDK PCell/DRC.

The cost of compatible geometry is visible: Ascend CPU's new envelope is
15.150 x 32.025 mm, with four ring rows. Micro150's four larger-demand chips
need 13 rows and 10.200 x 10.950 mm envelopes. This area is charged before
placement rather than hiding attachment overhead inside an unlimited port.

The [new independent geometry contract](tap-ihp-geometry-contract.md) retains
all individual positions and four rotations. The 50 mm research carrier and
1 mm grid are explicit inherited choices; the 200 um gap comes from the pinned
ADK default. Its axis-aligned separation test conservatively excludes some
diagonal arrangements. Full three-case first-fit witnesses passed exact integer
boundary and pair checks, followed by transformed landing containment checks.
The old 77 thermal classes and old thermal results are not reused.

[Endpoint evidence](evidence/tap-ihp-endpoints.json) records all per-die dimensions,
role counts, input hashes and full-map hashes. [Geometry evidence](evidence/tap-ihp-geometry.json)
records the independent domain sizes and complete placement witnesses. Full pad
maps are reproducible local artifacts, not independently reviewed external
certificates. The first generated maps and the later portable-hash run have
identical map contents; text-source digests now normalize CRLF to LF explicitly.

## Sourcing decision and outstanding physical work

The additional pinned AIB candidate is
[chipsalliance/aib-phy-hardware a0295cd](https://github.com/chipsalliance/aib-phy-hardware/tree/a0295cd2b90768c6cfd0795e5754e86dc2b6f747).
Its `docs/AIB_Usage_Note_v1_2_3.pdf`, page 20 section 8.1, says the supplied bump
spreadsheet is the Leader pinout and requests an issue for the Follower pinout.
It therefore does not supply a verified pair of physical endpoints here.
The [OpenHBI 1.0 specification](https://www.opencompute.org/documents/odsa-openhbi-v1-0-spec-rc-final-1-pdf),
section 6.1, defines a virtual bump target and permits physical implementation
differences subject to routing, timing and SI. Neither source justifies relabeling
these TAP conductors as that PHY or combining them with the IHP process.

Next freeze layer usage, actual pad escape and track/via allocation for this
declared family, using the compatible PDK rules already pinned. Keep PDN wiring,
clock/PHY mapping, electrical load/current, thermal stack/cooling and fabrication
qualification open until they have evidence. In particular, geometric fit does
not establish routability or a thermally valid complete package. HiTS remains
the thermal route; no thermal solve or optimizer is motivated by this stage alone.

## Reproduce

```powershell
. ./tools/windows_env.ps1
python tools/build_tap_ihp_endpoints.py --output results/tap-ihp-fresh --evidence results/tap-ihp-fresh-evidence.json
python tools/freeze_tap_ihp_geometry.py --endpoints results/tap-ihp-fresh --output results/tap-ihp-fresh-geometry.json
python -m unittest discover -s tests -p '*_unittest.py' -v
chiplet-floorplanning evaluate examples/two_chiplets.json --output results/tap-ihp-basic-fresh
```

The geometry command binds the new maps to the published endpoint evidence and
uses pinned ADK rule bytes. No remote computation is involved. The five new
tests cover parity-sensitive capacities, all source families, six corruption
controls, four assembly-view rotations and all three geometry witnesses.
All 275 tests passed locally; the documented two-chiplet CLI validated and
evaluated at 3 W and 34.1886 C reference peak (uncalibrated, timing not run).
This endpoint/geometry increment is not yet separately Chat-reviewed; the next
stage review should cover it together with the source admission and detailed
escape/resource contract once that contract is concrete.
