# Troubleshooting

## Fan runs 100% after ESP/daemon failure

That is expected fail-safe behavior.

Possible causes:

- daemon stopped
- serial cable/controller unavailable
- ESP watchdog expired
- GPU query failed
- critical temperature triggered
- ESP stall recovery active
- service restart/stop path requested fail-safe speed

Check:

```bash
journalctl -u v100-fan-controller -n 100 --no-pager
```

and controller status with the daemon stopped if necessary.

## RPM is always zero

Check:

- TACH wiring is on D2/GPIO4, not GPIO16/D0
- 10 kOhm pull-up is on the fan-side TACH node
- 2.2 kOhm series resistor is between that node and GPIO4
- grounds are common
- TACH voltage was verified before GPIO connection
- `tach_pulses_per_rev` is appropriate

The final reference design moved TACH to GPIO4 because it supports the normal external interrupt path required by the firmware.

## `STALLS` is non-zero after calibration

The counter is cumulative until MCU reset. Historical calibration stalls are not automatically an active fault.

Look for the count **increasing** during normal operation.

## Service cannot find controller

Check:

```bash
ls -l /dev/serial/by-id/
```

Then verify the configured path or temporarily use `port = auto`.

If a controller responds with an older `V100FAN <n>` protocol version, flash the protocol-v3 firmware.

## Service repeatedly reconnects

Inspect journal for:

- command-reply timeouts
- stale/unsupported serial traffic
- USB disconnects
- invalid runtime `CFG`

The daemon already retries commands in the same open serial session before reconnecting.

## `--check` works but service does not

`--check` only validates config and GPU selection; it does not open the ESP serial port.

Check controller connection and permissions/device path separately.

## Fan pitch still changes noticeably

First determine whether workload power is changing.

A large RPM wave can be a correct response to large GPU power swings. For tuning, capture both:

```text
fan daemon journal
GPU power/utilization/temperature
```

The current deadband mainly suppresses small target changes. It deliberately does not block a real 5-10 percentage-point thermal request.

## Temperature remains high with fan at 100%

Do not keep tuning software parameters. Inspect the physical cooling system:

- airflow path
- blower direction
- heatsink contact
- obstruction/dust
- applied fan voltage
- PWM wiring
- actual RPM
- GPU power level

The host critical threshold forces fan speed; it does not guarantee that the cooling hardware can dissipate the load.

## Fan does not start reliably at the configured minimum

Raise `minimum_percent` and/or the low fan-curve plateau. A running minimum is not necessarily a reliable starting minimum.

Use `tools/calibrate_fan.py` with the daemon stopped.
