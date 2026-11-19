"""Read four physical hotspot steps per cooling system and transfer a fixed site choice."""

import argparse
import json
from pathlib import Path

import numpy as np

from cut_traffic import digest
from measured_row_heating import SAMPLE_HZ


GROUPS = ["heatsink", "heatsink_with_fan"]
TIMES = [0.5, 2, 10, 20]


def step(path, nominal_on_w):
    raw = np.loadtxt(path)
    assert raw.ndim == 2 and raw.shape[1] == 49 and np.isfinite(raw).all()
    power = raw[:, :16] * raw[:, 16:32]
    temperature = raw[:, 32:48]
    active = power.sum(1) > (nominal_on_w + 16 * 0.2) / 2
    edges = np.diff(np.r_[False, active, False].astype(int))
    begins, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
    longest = np.argmax(ends - begins)
    start, stop = int(begins[longest]), int(ends[longest])
    assert start >= SAMPLE_HZ and stop - start >= max(TIMES) * SAMPLE_HZ
    base = slice(start - SAMPLE_HZ, start)
    idle_w, idle_c = power[base].mean(0), temperature[base].mean(0)
    return start, idle_w, idle_c, power - idle_w, temperature - idle_c


def read_trace(path):
    start, idle_w, idle_c, power, temperature = step(path, 10.0)
    location = int(np.argmax(power[start : start + 200].mean(0)))
    readings = []
    for seconds in TIMES:
        end = start + round(seconds * SAMPLE_HZ)
        window = slice(max(start, end - 5), end)
        delta = power[window].mean(0)
        rise = temperature[window].mean(0)
        hottest = int(rise.argmax())
        readings.append(
            dict(
                seconds=seconds,
                delta_total_w=float(delta.sum()),
                delta_heater_w=float(delta[location]),
                hottest_sensor_1_based=hottest + 1,
                rise_k=float(rise[hottest]),
                max_measured_c=float((temperature[window].mean(0) + idle_c).max()),
                response_k_w=float(rise[hottest] / delta.sum()),
            )
        )
    return dict(
        file=path.name,
        sha256=digest(path),
        switch_sample=start,
        heater_1_based=location + 1,
        pre_step_w=float(idle_w.sum()),
        samples=readings,
    )


def four_heaters(directory, selected):
    path = directory / "four.csv"
    begin, _, _, target_power, target_temp = step(path, 14.4)
    target_power = target_power[begin : begin + 200]
    target_temp = target_temp[begin : begin + 200]
    weight = []
    actual_power = target_power.mean(0)
    power_sum = np.zeros_like(target_power)
    full, local = np.zeros_like(target_temp), np.zeros_like(target_temp)
    sensitivity = []
    sources = []
    for i in range(1, 5):
        filename = directory / f"hotspot_{i}.csv"
        t, _, _, p, rise = step(filename, 10.0)
        j = int(np.argmax(p[t : t + 200].mean(0)))
        scale = float(actual_power[j] / p[t : t + 200, j].mean())
        weight.append(scale)
        sources.append(j)
        power_sum += scale * p[t : t + 200]
        full += scale * rise[t : t + 200]
        local[:, j] += scale * rise[t : t + 200, j]
        sensitivity.append(
            [
                float(
                    rise[t + shift : t + shift + 5].mean(0).max()
                    / p[t + shift : t + shift + 5].mean(0).sum()
                )
                for shift in (-1, 0, 1)
            ]
        )
    assert set(sources) == set(np.argsort(actual_power)[-4:])

    def metrics(estimate):
        err = estimate - target_temp
        worst_step, worst_sensor = np.unravel_index(np.abs(err).argmax(), err.shape)
        peak20 = float(estimate[-5:].mean(0).max())
        return dict(
            rmse_k=float(np.sqrt((err**2).mean())),
            heated_sensors_rmse_k=float(np.sqrt((err[:, sources] ** 2).mean())),
            max_abs_k=float(abs(err).max()),
            worst_step=int(worst_step),
            worst_sensor_1_based=int(worst_sensor) + 1,
            peak20_k=peak20,
            peak20_error_k=peak20 - float(target_temp[-5:].mean(0).max()),
        )

    ratios = np.array(sensitivity)
    return dict(
        file=path.name,
        sha256=digest(path),
        start=begin,
        heater_1_based=[j + 1 for j in sources],
        weights=weight,
        input_relative_l2=float(
            np.linalg.norm(power_sum.mean(0) - actual_power) / np.linalg.norm(actual_power)
        ),
        measured_rise20_k=float(target_temp[-5:].mean(0).max()),
        local=metrics(local),
        full=metrics(full),
        early_window_shifts_samples=[-1, 0, 1],
        early_window_best_hotspots_1_based=(1 + ratios.argmin(0)).tolist(),
        early_window_loss_at_6p8w_k=(6.8 * (ratios[selected] - ratios.min(0))).tolist(),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", type=Path, required=True, help="TTV-1202 Zenodo 3345878 v2 release folder")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    trials = {g: [read_trace(args.release / g / f"hotspot_{i}.csv") for i in range(1, 5)] for g in GROUPS}
    locations = [r["heater_1_based"] for r in trials[GROUPS[0]]]
    assert len(set(locations)) == 4 and locations == [r["heater_1_based"] for r in trials[GROUPS[1]]]
    chosen = min(range(4), key=lambda i: trials[GROUPS[0]][i]["samples"][-1]["response_k_w"])
    checks = []
    for group, records in trials.items():
        for k, t in enumerate(TIMES):
            samples = [r["samples"][k] for r in records]
            normalized = [s["response_k_w"] for s in samples]
            raw = [s["rise_k"] for s in samples]
            best = int(np.argmin(normalized))
            checks.append(
                dict(
                    group=group,
                    seconds=t,
                    chosen=chosen + 1,
                    best_response=best + 1,
                    best_raw=int(np.argmin(raw)) + 1,
                    normalized_loss_k_w=normalized[chosen] - normalized[best],
                    loss_at_6p8w_k=6.8 * (normalized[chosen] - normalized[best]),
                    actual_rise_loss_k=raw[chosen] - min(raw),
                )
            )
    four = {g: four_heaters(args.release / g, chosen) for g in GROUPS}
    out = dict(
        source="Terraneo, Leva & Fornaciari, SAMOS 2019, Zenodo 3345878 v2, CC BY",
        sample_hz=SAMPLE_HZ,
        chosen_hotspot_filename=f"hotspot_{chosen + 1}.csv",
        trials=trials,
        comparisons=checks,
        simultaneous_heaters=four,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
