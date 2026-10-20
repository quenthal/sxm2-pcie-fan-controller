# Configuration Reference

Installed configuration path:

```text
/etc/v100-fan-controller/config.ini
```

Repository reference config:

```text
config/config.ini
```

The repository config uses generic `port = auto` and `selector = V100`; a permanent deployment should normally use a stable serial by-id path and an unambiguous GPU selector.

## Full reference profile

```ini
[serial]
port = auto
baud = 115200
timeout_seconds = 0.25
command_reply_timeout_seconds = 1.2
command_retries = 2
reconnect_seconds = 2.0

[gpu]
selector = V100
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

[logging]
level = INFO
```

## `[serial]`

### `port`

`auto` probes serial devices for a protocol-v3 controller. For a fixed installation prefer `/dev/serial/by-id/...`.

### `baud`

Firmware protocol baud rate. Reference firmware uses 115200.

### `timeout_seconds`

PySerial per-operation timeout.

### `command_reply_timeout_seconds`

How long one host command waits for a matching reply.

### `command_retries`

Number of same-session retries before the daemon closes/reopens the serial port.

### `reconnect_seconds`

Delay before retrying after a controller/serial failure.

## `[gpu]`

### `selector`

GPU index, full UUID, or unique name substring.

### `poll_seconds`

Host temperature/control interval. The reference profile uses 8 seconds to reduce repeated `nvidia-smi` process launches while remaining fast enough for observed V100 temperature changes.

### `nvidia_smi_timeout_seconds`

Maximum duration of one GPU query.

### `temperature_smoothing_seconds`

Exponential low-pass time constant. `0` disables filtering.

### `temperature_rise_bypass`

When true, a temperature increase bypasses smoothing and is used immediately. Cooling remains smoothed.

## `[fan]`

### `curve`

Comma-separated `temperature_C:fan_percent` points. The daemon sorts and linearly interpolates them.

Reference curve:

```text
30 C -> 10%
55 C -> 10%
60 C -> 15%
65 C -> 25%
70 C -> 40%
75 C -> 60%
80 C -> 100%
```

### `minimum_percent`

Automatic floor after curve interpolation. This cannot force the output below the lowest fan-curve point.

Reference value 10% was selected because the physical blower was reliably startable there; lower values were less reliable.

### `failure_percent`

Fan target used by host safety paths. Reference: 100%.

### `rise_rate_percent_per_second`

Maximum normal upward PWM change. `0` means immediate. Safety requests are immediate regardless.

### `fall_hold_seconds`

How long a lower target must persist before normal fan reduction begins. This helps bridge short workload-power dips.

Because control decisions occur only at poll boundaries, values close to the poll interval should be interpreted in that discrete-time context.

### `fall_rate_percent_per_second`

Maximum downward change after the hold. At 8-second polling, `0.5` is roughly 4 percentage points per control step.

### `target_deadband_percent`

Small curve-target differences at or below this magnitude can be held at the current command. Reference: 3 percentage points.

Set `0` to disable.

### `deadband_rapid_rise_c`

Small **upward** target changes bypass the deadband when raw temperature increased by at least this many degrees since the previous poll. Reference: 2 C/sample.

Set `0` to disable this bypass.

### `deadband_bypass_temperature_c`

Small upward target changes bypass the deadband at or above this raw temperature. Reference: 70 C.

Set `0` to disable this bypass.

## `[controller]`

These values are sent to the ESP with `CFG` after every serial reconnect.

### `watchdog_timeout_seconds`

Maximum time without `SET`/`MAX` before the ESP forces 100% fan.

Reference: 30 seconds.

### `stall_timeout_seconds`

How long a non-zero target can lack TACH activity before local stall recovery starts.

### `stall_recovery_seconds`

How long firmware holds 100% during recovery before retrying the requested target.

### `rpm_sample_seconds`

TACH accumulation interval used for RPM calculation.

### `tach_pulses_per_rev`

Reference blower uses the standard 2 pulses/revolution assumption.

## `[safety]`

### `stall_lock_events`

Number of new no-TACH stalls with a live GPU before the host permanently locks the target to `failure_percent` until service restart. `0` disables host-side persistent lock while leaving ESP recovery active.

### `critical_temperature_c`

Raw GPU temperature threshold for immediate host fail-safe target. `0` disables.

The reference profile uses 80 C because the reference V100 reported 83 C as GPU Max Operating Temp. Verify your own card rather than copying this blindly.

## `[logging]`

### `level`

Python logging level. `INFO` is the normal reference setting.

## Validation

Before restarting the service after editing config:

```bash
/opt/v100-fan-controller/venv/bin/python \
  /opt/v100-fan-controller/v100_fan_daemon.py \
  --config /etc/v100-fan-controller/config.ini \
  --check
```
