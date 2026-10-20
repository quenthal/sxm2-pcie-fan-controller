# Reference Deployment

This document records the specific system used to develop and tune the project. It is a reference, not a requirement.

## Hardware

```text
Host            AOOSTAR GEM12+ running Linux
GPU             Tesla V100-SXM2-32GB
GPU connection  external PCIe through OCuLink adapter
GPU/blower power SFX PSU through adapter
Controller      ESP8266 NodeMCU / ESP-12E, CP2102 USB-UART
Blower          adapter/cooling-assembly 12 V 4-wire blower
```

The GPU workload runs in an LXC environment and is typically driven through `llama.cpp` / Open WebUI. The fan daemon itself runs on the Linux host so it can access `nvidia-smi` and the USB serial controller directly.

## Signal wiring

```text
D1/GPIO5 -> 2.2k -> BC337 base
BC337 base -> 100k -> GND
BC337 emitter -> common GND
BC337 collector -> blower PWM

blower TACH node -> 10k -> ESP 3V3
blower TACH node -> 2.2k -> D2/GPIO4

blower +12 V/GND -> adapter fan power path
ESP power -> host USB
all grounds common
```

A raw fan-side TACH measurement of about 0.105 V without the added pull-up supported the open-collector/open-drain interpretation used by the final direct TACH topology.

## Serial device

The reference controller appears as a Silicon Labs CP2102 device. For publication and portability, the repository does not hard-code the exact unit serial identifier. Use:

```bash
ls -l /dev/serial/by-id/
```

and configure the matching stable path locally.

## GPU selector

The reference deployment uses a full GPU UUID in the installed config for unambiguous selection. The public repository uses `selector = V100` instead so it does not publish a machine-specific identifier.

Discover your selector with:

```bash
nvidia-smi --query-gpu=index,uuid,name,temperature.gpu --format=csv
```

## Reference GPU thermal data

The card reported:

```text
GPU Max Operating Temp     83 C
Memory Max Operating Temp  85 C
GPU Slowdown Temp          87 C
GPU Shutdown Temp          90 C
```

HBM temperature was observed to stay at or below core temperature in the tested workloads, often a few degrees lower and sometimes lagging short core-temperature spikes.

## Reference fan characterization

```text
20%  ~2070 RPM
10%  ~1170-1200 RPM
9%   ~1110-1140 RPM
8%   ~1080-1140 RPM while running, but cold start not fully reliable
7%   unstable/lumpy behavior
6%   stalls
```

The installed minimum is therefore 10%.

## Current reference host configuration

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

[controller]
watchdog_timeout_seconds = 30.0
stall_timeout_seconds = 3.0
stall_recovery_seconds = 5.0
rpm_sample_seconds = 1.0
tach_pulses_per_rev = 2

[safety]
stall_lock_events = 2
critical_temperature_c = 80
```

## Observed workload behavior

During tested workloads where GPU power was commonly in the roughly 170-200 W range under a 200 W cap:

- core temperature commonly sat around 65-68 C
- 70 C crossings were uncommon
- normal fan targets were commonly around 25-34%
- HBM was not hotter than core in the observed samples
- `WATCHDOG=OK`, `STALL=OK`, `STALLS=0` during normal production tests

Workload power itself can oscillate substantially, so large temperature/fan waves during agent use should not automatically be interpreted as control-loop oscillation.

## Machine-specific values intentionally omitted from the public example

- exact GPU UUID
- exact CP2102 serial identifier
- local hostnames
- workload/model identifiers

These belong in the installed `/etc/v100-fan-controller/config.ini`, not in a reusable public repository.
