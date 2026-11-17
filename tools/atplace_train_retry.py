"""ATPlace thermal training with redraws of failed training-layout samples (plan: docs/atplace-comparison-v3-plan.md).

Usage, from the ATPlace_pub root in its own env: python atplace_train_retry.py ATTEMPTS run_thermal_training.py ARGS...
ATPlace draws random quarter turns and target positions per training layout, then solves a MILP for the nearest legal
layout; on the dense Case8-10 some draws find no legal layout within the time limit and training stops. A failed draw
is redrawn from the same rng (so the run stays deterministic) up to ATTEMPTS times; sampler, ATSim labels, model and
training are otherwise ATPlace's own. Python 3.9 compatible.
"""
import runpy
import sys


def with_redraws(sample, attempts):
    def sample_layout(system, params, rng):
        last = None
        for k in range(attempts):
            try:
                return sample(system, params, rng)
            except RuntimeError as error:
                print(f'training sample redraw {k + 1}/{attempts}: {error}', flush=True)
                last = error
        raise last
    return sample_layout


if __name__ == '__main__':
    attempts, script = int(sys.argv[1]), sys.argv[2]
    sys.argv = [script] + sys.argv[3:]
    sys.path.insert(0, '.')
    import src.thermal.training as training
    training.sample_layout = with_redraws(training.sample_layout, attempts)
    runpy.run_path(script, run_name='__main__')
