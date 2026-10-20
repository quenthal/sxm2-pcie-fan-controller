# Safety Model and Residual Risks

This project intentionally uses layered fail-safe behavior, but it is still an experimental custom hardware controller.

## Layer 1 - electrical PWM release

Q1 is an NPN pull-down on the blower PWM input.

```text
ESP GPIO LOW / ESP off / reset
    -> Q1 off
    -> PWM input released
    -> standard 4-wire fan behavior: full speed
```

This is the most important hardware-level behavior because it does not depend on Python, USB serial or a running Linux service.

Verify this behavior on the actual blower before relying on it.

## Layer 2 - ESP serial watchdog

Only `SET` and `MAX` re-arm the watchdog.

If host commands stop for the configured interval, firmware forces 100% fan.

Reference runtime value:

```text
30 s
```

Firmware compile-time default is 8 s; the daemon pushes 30 s after connecting.

## Layer 3 - ESP no-TACH stall recovery

For a non-zero target, lack of TACH activity for the stall timeout forces 100% for the recovery interval, then retries the original target.

Reference:

```text
stall timeout   3 s
recovery        5 s
```

`SET 0` is excluded because zero RPM is expected during calibration/manual tests.

## Layer 4 - host stall lock

The daemon watches increases in the cumulative firmware `STALLS` count.

Reference:

```ini
stall_lock_events = 2
```

Repeated new stalls while the GPU is live and the daemon is intentionally requesting less than fail-safe speed lock the host output to `failure_percent` until service restart.

This condition intentionally excludes an unpowered/missing eGPU from being mistaken for a persistent live-GPU fan fault.

## Layer 5 - GPU query failure

Any failure to obtain a usable GPU temperature causes an immediate `failure_percent` request.

This includes `nvidia-smi` process failure or timeout.

## Layer 6 - critical raw GPU temperature

The critical check uses raw temperature before normal smoothing/deadband/fall shaping.

Reference:

```ini
critical_temperature_c = 80
failure_percent = 100
```

At/above the threshold the daemon immediately requests 100% and logs CRITICAL.

**This is fan control only. It does not power off or shut down the host.**

## Reference GPU thermal limits

The reference Tesla V100-SXM2-32GB reported:

```text
GPU Max Operating Temp     83 C
Memory Max Operating Temp  85 C
GPU Slowdown Temp          87 C
GPU Shutdown Temp          90 C
```

These were read from the actual card with:

```bash
nvidia-smi -q -d TEMPERATURE
```

Do not assume every card/firmware combination reports identical limits. Check the target GPU.

## TACH electrical safety

The direct TACH-to-GPIO topology is valid only after verifying that the fan TACH behaves as an open-collector/open-drain source with a safe 3.3 V pull-up.

Two voltage checks are required with GPIO4 disconnected; see [WIRING.md](WIRING.md).

A 2.2 kOhm series resistor is not a substitute for correct logic-level validation.

## Watchdog margin

With the current reference host settings:

```text
poll                         8.0 s
nvidia-smi timeout           2.0 s
2 serial retries x 1.2 s     2.4 s
----------------------------------
conservative host budget    12.4 s
```

The 30-second controller watchdog leaves substantial timing margin.

## Residual risks

The current design does not protect against every possible failure mode.

Examples:

- an MCU failure mode that somehow leaves a valid low-speed PWM waveform running indefinitely
- incorrect fan pin identification
- non-standard TACH/PWM electrical behavior
- mechanical airflow obstruction despite 100% fan command
- GPU cooling failure unrelated to blower command
- host thermal failure while the fan controller itself still operates normally

There is no independent external hardware watchdog in the current design.

## If temperature remains high at 100% fan

Treat that as a cooling-system problem, not a controller-tuning problem. Inspect airflow, blower direction, heatsink contact, obstruction, power and the actual applied PWM/RPM.
