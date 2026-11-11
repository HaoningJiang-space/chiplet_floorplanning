"""Ideal passive channel controls, separate from production STA and pad models.

SI units at the boundary. The independent state solver uses ns and 50*I as
coordinates to improve conditioning; its output is converted back to SI.
"""

from dataclasses import asdict, dataclass

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.signal import lsim


EPSILON_0 = 8.8541878128e-12
MU_0 = 1.25663706212e-6
VDD = 3.3
STOP_S = 8e-9
GATES = dict(charge=1e-5, local_charge=1e-3, energy=5e-4,
             waveform_v=0.00033, crossing_ps=0.1,
             refinement_absolute_ps=0.1, refinement_relative=0.0025,
             frequency_absolute=5e-4, algebraic_frequency_absolute=1e-9)
FREQUENCIES_HZ = np.array([1e7, 1e8, 1e9, 3e9, 1e10])


@dataclass(frozen=True)
class Channel:
    length_mm: float
    driver_ohm: float
    slew_10_90_ps: float
    load_f: float = 1.117215037e-12
    width_m: float = 10e-6
    thickness_m: float = 1e-6
    return_spacing_m: float = 1e-6
    epsilon_r: float = 3.9
    resistivity_ohm_m: float = 1.68e-8

    def __post_init__(self):
        if any(not np.isfinite(x) or x <= 0 for x in asdict(self).values()):
            raise ValueError('finite positive channel parameters required')

    @property
    def name(self):
        return f'l{self.length_mm:g}_r{self.driver_ohm:g}_s{self.slew_10_90_ps:g}'

    @property
    def per_m(self):
        return (self.resistivity_ohm_m / (self.width_m * self.thickness_m),
                EPSILON_0 * self.epsilon_r * self.width_m / self.return_spacing_m,
                MU_0 * self.return_spacing_m / self.width_m)

    @property
    def pwl(self):
        ramp = self.slew_10_90_ps * 1e-12 / 0.8
        return np.array([0., 1e-9, 1e-9 + ramp, 4e-9, 4e-9 + ramp, STOP_S]), np.array([0., 0., VDD, VDD, 0., 0.])


def network(channel, segments, model):
    if isinstance(segments, bool) or int(segments) != segments or segments < 1 or model not in ('RC', 'RLC'):
        raise ValueError('positive integer segments and RC/RLC model required')
    rp, cp, lp = channel.per_m
    dx = channel.length_mm * 1e-3 / segments
    capacitance = np.full(segments + 1, cp * dx)
    capacitance[[0, -1]] *= 0.5
    capacitance[-1] += channel.load_f
    resistance = np.full(segments, rp * dx)
    inductance = np.full(segments, lp * dx if model == 'RLC' else 0.)
    incidence = np.zeros((segments + 1, segments))
    for j in range(segments):
        incidence[j, j], incidence[j + 1, j] = 1., -1.
    return capacitance, resistance, inductance, incidence


def state_system(capacitance, resistance, inductance, incidence, driver_ohm):
    c, r, l, b = map(np.asarray, (capacitance, resistance, inductance, incidence))
    if (np.any(c <= 0) or np.any(r <= 0) or np.any(l < 0) or driver_ohm <= 0
            or not all(np.all(np.isfinite(x)) for x in (c, r, l, b))
            or not np.isfinite(driver_ohm) or len(r) != len(l)
            or b.shape != (len(c), len(r)) or (np.any(l > 0) and np.any(l == 0))):
        raise ValueError('invalid passive circuit')
    count = len(c)
    conductance = np.zeros((count, count))
    conductance[0, 0] = 1 / driver_ohm
    drive = np.zeros(count)
    drive[0] = 1 / (driver_ohm * c[0])
    if not np.any(l):
        a = -(conductance + (b / r) @ b.T) / c[:, None]
    else:
        a = np.block([[-conductance / c[:, None], -b / (50 * c[:, None])],
                      [50 * b.T / l[:, None], -np.diag(r / l)]])
        drive = np.r_[drive, np.zeros(len(r))]
    return a * 1e-9, drive * 1e-9


def oracle(channel, segments, model, step_ps=0.125):
    c, r, l, b = network(channel, segments, model)
    a, drive = state_system(c, r, l, b, channel.driver_ohm)
    t = np.linspace(0., STOP_S, round(STOP_S / (step_ps * 1e-12)) + 1)
    u = np.interp(t, *channel.pwl)
    # lsim uses a matrix exponential with a piecewise linear forcing term.
    # Every source breakpoint is represented exactly on this uniform grid.
    if any(np.min(np.abs(t - p)) > 1e-20 for p in channel.pwl[0]):
        raise ValueError('oracle grid must include every source breakpoint')
    output = np.zeros((2, len(drive)))
    output[0, 0], output[1, segments] = 1., 1.
    _, v, _ = lsim((a, drive[:, None], output, np.zeros((2, 1))), U=u, T=t * 1e9)
    return t, v


def crossings(t, voltage, channel):
    """Retain both crossing directions in each stimulus window, including recrossings."""
    answer = {}
    ramp = channel.slew_10_90_ps * 1e-12 / .8
    for edge, start, stop, direction in [('rise', 1e-9, 4e-9, 1), ('fall', 4e-9, STOP_S, -1)]:
        levels = {}
        for fraction in (.1, .5, .9):
            threshold = fraction * VDD
            events = []
            for sign in (1, -1):
                idx = np.flatnonzero((sign * (voltage[:-1] - threshold) < 0)
                                     & (sign * (voltage[1:] - threshold) >= 0))
                for i in idx:
                    x = t[i] + (threshold - voltage[i]) * (t[i+1] - t[i]) / (voltage[i+1] - voltage[i])
                    if start <= x < stop:
                        events.append(dict(time_ps=float(x * 1e12), direction='rise' if sign == 1 else 'fall'))
            events.sort(key=lambda x: x['time_ps'])
            levels[str(fraction)] = events
        unique = all(len(v) == 1 and v[0]['direction'] == edge for v in levels.values())
        reference_ps = (start + .5 * ramp) * 1e12
        answer[edge] = dict(levels=levels, scalar_unambiguous=unique,
                            delay_50_ps=levels['0.5'][0]['time_ps'] - reference_ps if unique else None,
                            slew_10_90_ps=abs(levels['0.9'][0]['time_ps'] - levels['0.1'][0]['time_ps']) if unique else None)
    return answer


def crossing_difference(left, right):
    differences = []
    for edge in ('rise', 'fall'):
        for level in ('0.1', '0.5', '0.9'):
            x, y = left[edge]['levels'][level], right[edge]['levels'][level]
            if not x or len(x) != len(y) or [p['direction'] for p in x] != [p['direction'] for p in y]:
                return None
            differences.extend(abs(p['time_ps'] - q['time_ps']) for p, q in zip(x, y))
    return max(differences)


def ledger(t, u, v, source_current, branch_current, c, r, l, b, driver_ohm):
    """Integral balances at EVERY recorded time, not just the settled endpoint."""
    if not np.all(np.diff(t) > 0):
        raise ValueError('strictly increasing waveform time required')
    integrate = lambda y: cumulative_trapezoid(y, t, axis=0, initial=0.)
    source_charge = integrate(source_current)
    local_flow = -branch_current @ b.T
    local_flow[:, 0] += source_current
    dq = (v - v[0]) * c
    q_error = dq.sum(axis=1) - source_charge
    local_error = dq - integrate(local_flow)
    electric = .5 * ((v * v) @ c)
    magnetic = .5 * ((branch_current * branch_current) @ l)
    total = electric + magnetic
    input_energy = integrate(u * source_current)
    driver_loss = integrate(driver_ohm * source_current**2)
    wire_loss = integrate((branch_current**2) @ r)
    error = total - total[0] + driver_loss + wire_loss - input_energy
    channel_error = total - total[0] + wire_loss - integrate(v[:, 0] * source_current)
    scale = c.sum() * VDD**2
    metrics = dict(charge=float(np.max(abs(q_error)) / (c.sum() * VDD)),
                   local_charge=float(np.max(abs(local_error) / (c * VDD))),
                   energy=float(np.max(abs(error)) / scale))
    return dict(normalized_max_residual=metrics,
                gates_passed=all(metrics[k] <= GATES[k] for k in metrics),
                channel_energy_max_normalized=float(np.max(abs(channel_error)) / scale),
                source_energy_j=float(input_energy[-1]), driver_heat_j=float(driver_loss[-1]),
                wire_heat_j=float(wire_loss[-1]), final_electric_j=float(electric[-1]),
                final_magnetic_j=float(magnetic[-1]), peak_magnetic_j=float(magnetic.max()),
                min_source_power_w=float(np.min(u * source_current)),
                final_energy_residual_j=float(error[-1]),
                maximum_energy_residual_j=float(np.max(abs(error))))


def continuum_transfer(channel, model, frequency_hz):
    rp, cp, lp = channel.per_m
    s = 2j * np.pi * frequency_hz
    if frequency_hz == 0:
        return 1 + 0j
    z, y = rp + s * (lp if model == 'RLC' else 0), s * cp
    gamma, impedance = np.sqrt(z * y), np.sqrt(z / y)
    distance = channel.length_mm * 1e-3
    a = np.cosh(gamma * distance)
    sinh = np.sinh(gamma * distance)
    bb, cc = impedance * sinh, sinh / impedance
    load = s * channel.load_f
    return 1 / (a + bb * load + channel.driver_ohm * (cc + a * load))


def frequency_checks(channel, segments, model):
    c, r, l, incidence = network(channel, segments, model)
    a, drive = state_system(c, r, l, incidence, channel.driver_ohm)
    cp = channel.per_m[1] * channel.length_mm * 1e-3 / segments
    records = []
    for f in FREQUENCIES_HZ:
        s = 2j * np.pi * f
        mna = np.linalg.solve(s * 1e-9 * np.eye(len(drive)) - a, drive)[segments]
        # An independently cascaded symmetric pi two-port, no incidence matrix.
        shunt = np.array([[1., 0.], [s * cp / 2, 1.]])
        series = np.array([[1., r[0] + s * l[0]], [0., 1.]])
        chain = np.linalg.matrix_power(shunt @ series @ shunt, segments)
        aa, bb, cc, dd = chain.ravel()
        cascade = 1 / (aa + bb*s*channel.load_f + channel.driver_ohm*(cc + dd*s*channel.load_f))
        continuum = continuum_transfer(channel, model, f)
        records.append(dict(frequency_hz=float(f), ladder_real=float(mna.real), ladder_imag=float(mna.imag),
                            continuum_real=float(continuum.real), continuum_imag=float(continuum.imag),
                            algebraic_absolute_error=float(abs(mna-cascade)),
                            continuum_absolute_error=float(abs(mna-continuum))))
    return dict(records=records,
                algebraic_passed=max(x['algebraic_absolute_error'] for x in records) <= GATES['algebraic_frequency_absolute'],
                continuum_sampled_passed=max(x['continuum_absolute_error'] for x in records) <= GATES['frequency_absolute'])


def deck(channel, segments, model, max_step_ps, integration='trap'):
    if integration not in ('trap', 'gear'):
        raise ValueError('unsupported integration method')
    c, r, l, _ = network(channel, segments, model)
    times, values = channel.pwl
    lines = ['Declared ideal passive channel; no PDK or real PHY',
             'VS src 0 PWL(' + ' '.join(f'{t:.16g} {v:.16g}' for t, v in zip(times, values)) + ')',
             f'RD src n0 {channel.driver_ohm:.16g}']
    for j in range(segments):
        lines += [f'VP{j} n{j} p{j} 0', f'RW{j} p{j} ' + (f'q{j}' if model == 'RLC' else f'n{j+1}') + f' {r[j]:.16g}']
        if model == 'RLC':
            lines += [f'LW{j} q{j} n{j+1} {l[j]:.16g}']
    lines += [f'C{j} n{j} 0 {cap:.16g}' for j, cap in enumerate(c)]
    vectors = ['v(src)', 'i(vs)'] + [f'v(n{j})' for j in range(segments+1)] + [f'i(vp{j})' for j in range(segments)]
    options = f'.options reltol=1e-7 abstol=1e-14 vntol=1e-9 method={integration}'
    if integration == 'gear':
        options += ' maxord=2'
    lines += [options, '.control',
              'set numdgt=15', 'set wr_singlescale', 'set wr_vecnames',
              f'tran {max_step_ps*1e-12:.16g} {STOP_S:.16g} 0 {max_step_ps*1e-12:.16g}',
              'wrdata waveform.txt ' + ' '.join(vectors), 'quit', '.endc', '.end']
    return '\n'.join(lines) + '\n'
