# Linux Host Daemon

Source: `daemon/v100_fan_daemon.py`

## Responsibilities

The daemon:

- selects the intended NVIDIA GPU
- reads GPU core temperature with `nvidia-smi`
- smooths cooling-side temperature changes
- computes a piecewise-linear fan-curve target
- suppresses small target changes with an asymmetric deadband
- applies fast-rise / hold / slow-fall shaping
- sends `SET n` to the ESP8266
- validates controller replies
- monitors TACH/stall fields
- forces fail-safe speed on GPU-query or thermal failure
- reconnects automatically after serial errors

## GPU selection

`[gpu] selector` accepts:

- NVIDIA index, e.g. `0`
- full GPU UUID, e.g. `GPU-...`
- a unique substring of the GPU name, e.g. `V100`

For a permanent single-GPU deployment, a full UUID is the least ambiguous. Avoid publishing your machine-specific UUID if you do not want it in a public repository.

The daemon currently queries:

```text
index, uuid, name, temperature.gpu
```

It intentionally does not use power draw or HBM temperature as control inputs.

## Serial connection

The daemon can use:

- a configured `/dev/serial/by-id/...` path, or
- `port = auto`, which probes available serial ports and looks for the protocol-v3 HELLO reply.

After connecting it:

1. performs `HELLO`
2. rejects unsupported protocol versions explicitly
3. pushes `CFG` values from `[controller]`
4. verifies the controller runtime configuration
5. sends fail-safe speed during connection setup
6. performs an immediate initial safe synchronization to the current GPU/curve target

## Temperature smoothing

`temperature_smoothing_seconds` implements an exponential low-pass filter.

With:

```ini
temperature_rise_bypass = true
```

raw increases pass immediately while cooling is smoothed. This is useful with a relatively slow host poll because it avoids adding extra delay to a real temperature rise.

## Fan curve

The curve is piecewise linear. Example:

```ini
curve = 30:10,55:10,60:15,65:25,70:40,75:60,80:100
```

The daemon interpolates between points. For example the reference curve produces about:

```text
65 C -> 25%
66 C -> 28%
67 C -> 31%
68 C -> 34%
69 C -> 37%
70 C -> 40%
```

## Target deadband

The deadband is applied after curve calculation and before rise/fall shaping.

Reference values:

```ini
target_deadband_percent = 3
deadband_rapid_rise_c = 2
deadband_bypass_temperature_c = 70
```

The deadband reduces audible fan-pitch wandering by allowing small target changes to be ignored.

Examples:

```text
current 28%, curve 31% -> may hold 28%
current 28%, curve 34% -> pass 34%
```

A small upward request is released immediately when raw temperature rises by at least 2 C in one sample or raw temperature is at least 70 C.

A fail-safe request always bypasses the deadband.

## Rise/fall shaping

Reference profile:

```ini
rise_rate_percent_per_second = 100
fall_hold_seconds = 16
fall_rate_percent_per_second = 0.5
```

The intent is:

- rapid upward response
- resist short workload dips
- slow, smooth RPM reduction after genuine cooling

At an 8-second poll interval, a 0.5 percentage-point/s fall rate corresponds to at most about 4 percentage points per control step after the hold expires.

## Critical temperature

The daemon checks the **raw** GPU temperature against `critical_temperature_c` before normal filtering/shaping.

At or above the threshold it:

- logs CRITICAL
- requests `failure_percent` immediately
- bypasses deadband and normal ramping

This action increases fan speed only. It does not shut down the host or GPU.

## GPU-query failure

If `nvidia-smi` fails, times out or produces unusable data, the daemon requests `failure_percent` immediately.

## Stall tracking

The ESP reply includes:

```text
STALL=OK|RECOVERY
STALLS=<cumulative count>
```

The daemon compares the cumulative count to the previous value and treats only an increase as a new event.

With a live GPU, repeated new stalls below fail-safe speed can trigger the persistent host-side stall lock:

```ini
stall_lock_events = 2
```

When locked, the daemon holds `failure_percent` until the service is restarted after inspection.

## Serial reply validation

The daemon is intentionally strict because delayed serial lines can otherwise de-synchronize control:

- `SET n` accepts only an `OK` reply whose `TARGET=n`
- `CFG` accepts only a reply matching the requested runtime values
- stale `ERR` lines are ignored while waiting for the current command's valid reply
- delayed boot/HELLO lines do not satisfy unrelated commands

Same-session command retries are attempted before closing/reopening the port.

## Watchdog timing budget

The daemon warns if the configured ESP watchdog leaves too little margin over a conservative host delay estimate:

```text
poll_seconds
+ nvidia_smi_timeout_seconds
+ command_retries * command_reply_timeout_seconds
+ 1 s warning margin
```

For the reference profile:

```text
8.0 + 2.0 + 2 * 1.2 = 12.4 s
```

A 30-second controller watchdog therefore leaves ample margin.

## systemd behavior

Unit: `systemd/v100-fan-controller.service`

Key behavior:

- `Restart=always`
- `RestartSec=2`
- start-limit disabling so repeated startup failures do not permanently strand the unit
- stop path requests fail-safe fan speed

The installer enables but does not start the service automatically on first installation.

## Logging

Normal INFO logs are intentionally sparse: the daemon logs when the effective target changes. Deadband success can therefore show up as fewer INFO lines.

Useful command:

```bash
journalctl -u v100-fan-controller -f
```

Longer tuning capture:

```bash
journalctl \
  -u v100-fan-controller \
  --since "60 min ago" \
  -o short-iso-precise \
  > v100-fan-60min.log
```
