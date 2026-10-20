# Architecture

## Purpose

The project controls a 12 V 4-wire blower that belongs to an SXM2-to-PCIe adapter/cooling assembly. In the reference deployment that assembly cools a Tesla V100-SXM2-32GB connected through OCuLink/PCIe. The blower receives +12 V and GND directly from the adapter/SFX supply; the ESP8266 only controls PWM and reads TACH.

The control system is split into two layers:

- **ESP8266 firmware**: electrical PWM generation, TACH/RPM measurement, serial watchdog, stall recovery.
- **Linux daemon**: GPU temperature acquisition, fan curve, filtering, deadband, response shaping, safety policy, logging.

This split is deliberate: the MCU still has local safety behavior if the host daemon disappears.

## Data path

```text
nvidia-smi
   |
   | GPU core temperature
   v
Linux daemon
   |
   | 1. optional temperature smoothing
   | 2. piecewise-linear curve
   | 3. PWM target deadband
   | 4. asymmetric rise/fall shaping
   | 5. safety overrides
   v
USB serial: SET n
   |
   v
ESP8266
   |
   | 25 kHz inverted GPIO PWM -> Q1 open-collector stage
   v
blower PWM input

blower TACH -> 10k pull-up -> 2.2k series -> GPIO4 interrupt -> RPM
```

## Host control pipeline

For each host poll:

1. `nvidia-smi` reads the selected GPU's core temperature.
2. Raw temperature is checked against `critical_temperature_c` before normal shaping.
3. Normal temperature is low-pass filtered on cooling. With `temperature_rise_bypass = true`, rising temperature passes through immediately.
4. The fan curve is linearly interpolated.
5. `apply_target_deadband()` suppresses small PWM target changes.
6. Upward deadband is bypassed on rapid heating or above the configured high-temperature threshold.
7. `shape_fan_target()` applies fast-rise / hold / slow-fall behavior.
8. The target is rounded and sent with `SET n`.
9. The ESP reply is validated and TACH/stall fields are inspected.
10. The daemon sleeps for `poll_seconds` and repeats.

## Current reference policy

```text
poll                         8 s
temperature smoothing        5 s
rise bypass                  enabled
curve                        30:10,55:10,60:15,65:25,70:40,75:60,80:100
rise rate                    100 percentage points/s
fall hold                    16 s
fall rate                    0.5 percentage points/s
target deadband              3 percentage points
rapid-rise deadband bypass   +2 C/sample
high-temp deadband bypass    70 C
critical temperature         80 C
```

The goal is acoustic stability without delaying urgent upward response.

## Deadband semantics

Let `current` be the current shaped command and `requested` be the curve target.

- If `|requested - current| > target_deadband_percent`, the request is passed through.
- If the difference is small, the current target is held.
- A downward request to the configured minimum is not held forever; it is allowed through.
- A small upward request is allowed through immediately when:
  - raw temperature rose by at least `deadband_rapid_rise_c` since the previous sample, or
  - raw temperature is at least `deadband_bypass_temperature_c`.
- `force_immediate` safety requests bypass deadband entirely.

With a 3-point deadband, `28 -> 31` can be held, while `28 -> 34` is passed. If temperature rises by 2 C in one 8-second sample, even the smaller upward request is released.

## Fan-response shaping

Normal response is asymmetric:

```text
requested >= current
    -> reset fall hold
    -> rise toward request at rise_rate_percent_per_second

requested < current
    -> begin/continue fall hold
    -> after hold, fall toward request at fall_rate_percent_per_second
```

Safety requests use `force_immediate=True` and jump directly to the requested fail-safe percentage.

## Firmware responsibilities

The ESP8266 firmware does not know GPU temperature. It implements:

- 25 kHz PWM output
- inverted output required by the NPN pull-down topology
- TACH interrupt counting
- RPM calculation
- protocol v3 serial parser
- watchdog timeout to 100%
- no-TACH stall recovery to 100%
- cumulative stall count

The host pushes watchdog/stall/RPM/PPR values with `CFG` after each serial reconnect.

## Why core temperature is the control sensor

On the reference V100, HBM temperature was observed to be at or below core temperature during the tested workloads. The current daemon therefore uses core temperature only. HBM remains a useful monitoring/sanity-check sensor but is not presently part of the control law.

Power draw is likewise not used as feed-forward. It can be useful for analysis because workload power changes explain much of the thermal wave seen during agent/LLM workloads.

## Failure paths

```text
nvidia-smi error --------------------> host failure_percent immediately
critical raw temperature -----------> host failure_percent immediately
repeated ESP stalls with live GPU --> host stall lock -> failure_percent
host stops sending SET/MAX ---------> ESP watchdog -> 100%
nonzero target + no TACH -----------> ESP recovery -> 100% -> retry target
ESP/GPIO/Q1 off/reset --------------> PWM released -> full fan (standard 4-wire behavior)
```

## Deliberate scope boundaries

The current project does not implement:

- PSU `PS_ON#` control
- host shutdown on overtemperature
- redundant external hardware watchdog
- PID/PI temperature control
- dynamic polling intervals
- power-draw feed-forward
- HBM-driven fan control
