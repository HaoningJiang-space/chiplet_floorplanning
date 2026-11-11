"""Analytic event reference; no STA/Liberty parsing or production timing imports.

This is a fixed-delay, single-clock, opposite-edge semantic experiment, not a
transistor waveform model or a calibrated chiplet interface.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Contract:
    period_ns: float = 10.0
    fall_ns: float = 4.0
    cq_ns: tuple = (0.7, 0.9)
    data_ns: tuple = (1.3, 1.2)
    clock_ns: tuple = (0.9, 1.1)
    inverter_ns: tuple = (0.4, 0.8)
    setup_ns: tuple = (0.2, 0.35)
    hold_ns: tuple = (0.15, 0.1)


def expected_paths(contract, early=None):
    """Enumerate ideal events first, then apply fixed delays without re-pairing.

    Capturing a positive edge after an inverter means a falling source edge.
    Setup uses the next such edge; hold protects the preceding capture against
    this launch. All times are relative to the same launch edge at t=0. A clock
    delay longer than a period must NOT silently change the logical edge pair.
    """
    c = contract
    early = early or c
    if not 0 < c.fall_ns < c.period_ns:
        raise ValueError("falling edge must lie strictly inside the period")
    capture_events = [cycle * c.period_ns + c.fall_ns for cycle in range(-2, 3)]
    next_capture = min(t for t in capture_events if t > 0)
    previous_capture = max(t for t in capture_events if t < 0)
    # Output rise is caused by the forward clock's FALL, not its rise.
    result = {}
    for check, edge in (("setup", next_capture), ("hold", previous_capture)):
        data_model = c if check == "setup" else early
        clock_model = early if check == "setup" else c
        capture_latency = clock_model.clock_ns[1] + clock_model.inverter_ns[0]
        for index, transition in enumerate(("rise", "fall")):
            arrival = data_model.cq_ns[index] + data_model.data_ns[index]
            capture = edge + capture_latency
            required = (capture - c.setup_ns[index] if check == "setup"
                        else capture + early.hold_ns[index])
            slack = required - arrival if check == "setup" else arrival - required
            result[f"{check}_{transition}"] = dict(
                launch_edge_ns=0.0, capture_edge_ns=edge,
                data_arrival_ns=arrival, capture_arrival_ns=capture,
                required_ns=required, slack_ns=slack)
    return result


def experiments():
    base = Contract()
    add = lambda values, delta: tuple(v + delta for v in values)
    return {
        "nominal": base,
        "data_only": replace(base, data_ns=add(base.data_ns, 0.5)),
        "clock_only": replace(base, clock_ns=add(base.clock_ns, 0.5)),
        "common_delay": replace(base, data_ns=add(base.data_ns, 0.5),
                                clock_ns=add(base.clock_ns, 0.5)),
        "inverter_only": replace(base, inverter_ns=add(base.inverter_ns, 0.5)),
        "period_12": replace(base, period_ns=12.0),
        "fall_at_6": replace(base, fall_ns=6.0),
        "setup_violation": replace(base, data_ns=add(base.data_ns, 4.0)),
        "hold_violation": replace(base, clock_ns=add(base.clock_ns, 7.0)),
    }


def early_corner(late):
    """Distinct early delays; setup/hold constraints deliberately stay fixed."""
    return replace(late, cq_ns=(0.3, 0.5), data_ns=(0.8, 0.7),
                   clock_ns=(0.4, 0.6), inverter_ns=(0.2, 0.5))
