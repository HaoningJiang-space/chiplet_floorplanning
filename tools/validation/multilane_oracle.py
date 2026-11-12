"""Independent edge-time reference for a shared-clock multi-chiplet fixture.

Delays are synthetic constants. No STA report or generated Liberty is read here.
The only correlated uncertainty is an explicitly equal additive root delay on
both polarities. It is not a statistical variation or jitter model.
"""

from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class Network:
    receivers: int = 1
    lanes: int = 8
    period_ns: float = 10.
    fall_ns: float = 4.
    root_ns: tuple = (.4, .6)
    trunk_ns: tuple = (.8, 1.)
    bank_ns: tuple = (.2, .3)
    inverter_ns: tuple = (.4, .8)
    cq_ns: tuple = (.7, .9)
    setup_ns: tuple = (.2, .35)
    hold_ns: tuple = (.15, .1)
    selected_data_shift_ns: float = 0.
    selected_branch_shift_ns: float = 0.

    def __post_init__(self):
        if type(self.receivers) is not int or not 1 <= self.receivers <= 15 or type(self.lanes) is not int or not 1 <= self.lanes <= 8:
            raise ValueError('fixture supports 1..15 receivers and 1..8 lanes each')
        if not 0 < self.fall_ns < self.period_ns or not math.isfinite(self.period_ns):
            raise ValueError('invalid source clock')
        for name in ('root_ns', 'trunk_ns', 'bank_ns', 'inverter_ns', 'cq_ns', 'setup_ns', 'hold_ns'):
            if len(getattr(self, name)) != 2 or any(not math.isfinite(x) or x <= 0 for x in getattr(self, name)):
                raise ValueError('positive finite rise/fall values required: '+name)
        if any(not math.isfinite(x) or x < 0 for x in (self.selected_data_shift_ns, self.selected_branch_shift_ns)):
            raise ValueError('nonnegative finite perturbations required')

    def data(self, receiver, lane):
        delta = self.selected_data_shift_ns if (receiver, lane) == (0, 0) else 0.
        return (1.+.07*lane+.03*receiver+delta, 1.2+.05*lane+.02*receiver+delta)

    def branch(self, receiver):
        delta = self.selected_branch_shift_ns if receiver == 0 else 0.
        return (.3+.05*receiver+delta, .4+.05*receiver+delta)


def delay_pair(c, name, early=False):
    values = getattr(c, name+'_ns')
    if early and name == 'root':
        # A single common parameter delta in [0, .2] ns moves both polarities.
        if min(values) <= .2:
            raise ValueError('root early bound must remain positive')
        return tuple(v-.2 for v in values)
    return tuple(.7*v for v in values) if early else values


def expected(c, receiver, lane, check, transition, min_max=False, correlated=False):
    if check not in ('setup', 'hold') or transition not in ('rise', 'fall'):
        raise ValueError('unsupported event')
    if not 0 <= receiver < c.receivers or not 0 <= lane < c.lanes:
        raise ValueError('unknown physical endpoint')
    data_early = min_max and check == 'hold'
    capture_early = min_max and check == 'setup'
    scale_data, scale_clock = (.7 if data_early else 1.), (.7 if capture_early else 1.)
    index = ('rise', 'fall').index(transition)
    edge = c.fall_ns if check == 'setup' else c.fall_ns-c.period_ns
    root_launch = delay_pair(c, 'root', data_early)[0]
    root_capture = delay_pair(c, 'root', capture_early)[1]
    launch = root_launch+delay_pair(c, 'bank', data_early)[0]
    data = launch+delay_pair(c, 'cq', data_early)[index]+scale_data*c.data(receiver, lane)[index]
    capture = edge+root_capture+delay_pair(c, 'trunk', capture_early)[1]+scale_clock*c.branch(receiver)[1]+delay_pair(c, 'inverter', capture_early)[0]
    correction = .2 if min_max and correlated else 0.
    required = (capture-c.setup_ns[index]+correction if check == 'setup'
                else capture+c.hold_ns[index]-correction)
    slack = required-data if check == 'setup' else data-required
    # Independently enumerate one shared root parameter, rather than pretending
    # its early launch and late capture values can occur simultaneously.
    enumeration = []
    if min_max:
        for delta in (0., .2):
            common_launch = c.root_ns[0]-.2+delta
            common_capture = c.root_ns[1]-.2+delta
            a = data-root_launch+common_launch
            k = capture-root_capture+common_capture
            enumeration.append(k-c.setup_ns[index]-a if check == 'setup' else a-k-c.hold_ns[index])
    return dict(launch_edge_ns=0., capture_edge_ns=edge,
                launch_arrival_ns=launch, data_arrival_ns=data, capture_arrival_ns=capture,
                required_ns=required, slack_ns=slack, common_path_correction_ns=correction,
                correlated_root_enumerated_slack_ns=min(enumeration) if enumeration else slack)


def scenarios():
    base = Network()
    shifted = lambda pair, delta:tuple(v+delta for v in pair)
    return {
        'one_lane':(replace(base, lanes=1), False, False),
        **{f'chiplets_{n}':(replace(base, receivers=n-1), False, False) for n in (2, 4, 8, 16)},
        'one_data_shift':(replace(base, selected_data_shift_ns=.5), False, False),
        'one_receiver_shift':(replace(base, receivers=3, selected_branch_shift_ns=.5), False, False),
        'shared_clock_shift':(replace(base, trunk_ns=shifted(base.trunk_ns, .5)), False, False),
        'common_root_shift':(replace(base, root_ns=shifted(base.root_ns, .5)), False, False),
        'root_duty_distortion':(replace(base, root_ns=(.4, 1.1)), False, False),
        'setup_failure':(replace(base, selected_data_shift_ns=7.), False, False),
        'hold_failure':(replace(base, trunk_ns=shifted(base.trunk_ns, 7.)), False, False),
        'early_late_uncorrected':(base, True, False),
        'early_late_correlated':(base, True, True),
        'chiplets_16_correlated':(replace(base, receivers=15), True, True),
    }
