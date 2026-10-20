# Thermal and Acoustic Tuning

This document records the tuning rationale for the reference SXM2-to-PCIe adapter blower with a V100-SXM2-32GB as the heat source. The values are not universal fan specifications.

## Current profile

```ini
[gpu]
poll_seconds = 8.0
nvidia_smi_timeout_seconds = 2.0
temperature_smoothing_seconds = 5.0
temperature_rise_bypass = true

[fan]
curve = 30:10,55:10,60:15,65:25,70:40,75:60,80:100
minimum_percent = 10
failure_percent = 100
rise_rate_percent_per_second = 100
fall_hold_seconds = 16
fall_rate_percent_per_second = 0.5
target_deadband_percent = 3
deadband_rapid_rise_c = 2
deadband_bypass_temperature_c = 70
```

## Why 8-second polling

Early testing used a 1-second host poll. The GPU's thermal dynamics did not require that many separate `nvidia-smi` process launches.

The reference profile moved to 8 seconds while retaining:

- raw-temperature critical checking
- immediate temperature-rise bypass of the low-pass filter
- rapid upward fan response
- 30-second ESP watchdog margin

Observed workload transitions still showed enough reaction time at 8 seconds. Longer intervals were not adopted because the tested workload could change core temperature by several degrees within one 8-second sample.

## Why the current curve

Reference curve:

```text
30-55 C  -> 10% plateau
60 C     -> 15%
65 C     -> 25%
70 C     -> 40%
75 C     -> 60%
80 C     -> 100%
```

The low plateau stays at 10% because that is the selected reliable-start floor for the physical blower.

The upper curve becomes progressively steeper so there is substantial reserve before the reference card's reported 83 C maximum operating temperature.

## Observed thermal behavior

During the tested LLM/agent workload with the GPU commonly drawing roughly 170-200 W (200 W cap), the reference unit usually stayed around:

```text
65-68 C core
25-34% fan target
```

70 C excursions were uncommon in the observed sessions.

HBM temperature was observed to track the core or remain a few degrees below it. No HBM-specific fan control was justified by the measured behavior.

## Workload power oscillation matters

A repeating thermal wave does not automatically mean the fan controller is oscillating.

Agent/LLM workloads can vary GPU power substantially between prompt processing, generation, synchronization, CPU-bound portions and idle gaps. When power drops, core temperature can fall quickly even while the fan is still spinning down from the previous target.

For this reason, diagnose control oscillation with both:

- fan-daemon journal, and
- GPU power/utilization if the workload itself is not steady.

## Temperature smoothing

Reference:

```ini
temperature_smoothing_seconds = 5
temperature_rise_bypass = true
```

This creates asymmetric filtering:

- rising raw temperature is used immediately
- falling temperature is smoothed

With 8-second polling, this avoids combining a slow poll with additional upward thermal lag.

## Slow fall

Earlier settings allowed large target drops per 8-second step. The current profile uses:

```ini
fall_hold_seconds = 16
fall_rate_percent_per_second = 0.5
```

After the hold expires, 8-second polling yields roughly 4 percentage points of maximum downward change per step.

This reduces abrupt audible RPM/pitch shifts and helps bridge short workload-power dips.

## Target deadband

Reference:

```ini
target_deadband_percent = 3
deadband_rapid_rise_c = 2
deadband_bypass_temperature_c = 70
```

The main acoustic goal is to prevent repeated small changes such as:

```text
25 -> 28 -> 31 -> 28 -> 31
```

from constantly shifting fan pitch.

A 3-point change may be held, but a larger request passes. Upward responsiveness remains protected by the two bypass rules.

## Fan lifetime considerations

For this brushless blower, the project prioritizes:

- reliable non-stalling operation
- no normal stop/start cycling
- a conservative minimum above the unreliable-start region
- avoiding unnecessary full-speed operation
- reducing needless target hunting

Small PWM changes are not considered a major wear mechanism by themselves. Average RPM, bearing conditions, temperature and repeated stop/start or stall behavior are more relevant practical concerns.

## Collect a tuning log

Fan-only analysis:

```bash
journalctl \
  -u v100-fan-controller \
  --since "60 min ago" \
  -o short-iso-precise \
  > v100-fan-60min.log
```

For a workload whose power varies strongly, collect GPU telemetry too:

```bash
nvidia-smi \
  --query-gpu=timestamp,temperature.gpu,power.draw,utilization.gpu,memory.used \
  --format=csv,noheader,nounits \
  -l 2 > gpu.csv
```

## Tune one variable at a time

Recommended order:

1. establish a reliable `minimum_percent`
2. establish a thermally safe curve
3. choose host poll interval/watchdog margin
4. tune cooling smoothing
5. tune fall hold/rate
6. tune target deadband
7. only then consider new control-law features

The current v0.11.0 feature set should allow most future tuning through `config.ini` without source changes.
