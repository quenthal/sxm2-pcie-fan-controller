# Validation Status

This document distinguishes software regression coverage from physical hardware validation.

## Host regression tests

Run:

```bash
python3 tests/test_regressions.py
```

This v0.11.0 snapshot has 13 tests covering:

- delayed duplicate `SET` reply not de-synchronizing the next command
- legacy `[fan] stall_lock_events` fallback
- `[safety] stall_lock_events` precedence
- deadband holding small up/down target changes
- deadband release at the configured minimum
- rapid-rise deadband bypass
- high-temperature deadband bypass
- force-immediate deadband bypass
- calibration handshake ignoring the boot banner
- stale `ERR` not satisfying a `SET`
- calibration `CFG` ignoring late HELLO/stale ERR traffic
- daemon old-protocol detection
- calibration old-protocol detection

Expected:

```text
Ran 13 tests
OK
```

## Python syntax validation

```bash
python3 -m py_compile \
  daemon/v100_fan_daemon.py \
  tools/calibrate_fan.py \
  tools/v100fanctl.py
```

## Shell syntax validation

```bash
sh -n install.sh
sh -n package.sh
sh -n tools/list_gpus.sh
```

## Config parsing validation

The daemon validates ranges and reports config errors without an unhandled traceback.

On a real NVIDIA host:

```bash
/opt/v100-fan-controller/venv/bin/python \
  /opt/v100-fan-controller/v100_fan_daemon.py \
  --config /etc/v100-fan-controller/config.ini \
  --check
```

## Physically validated on the reference system

The development process physically observed:

- V100-SXM2-32GB enumeration and temperature reporting
- CP2102 serial control
- 25 kHz PWM control through the NPN stage
- TACH reading on GPIO4
- RPM values at multiple PWM targets
- unreliable/stall region below the chosen 10% automatic floor
- ESP no-TACH recovery behavior during low-duty tests
- normal daemon operation with `WATCHDOG=OK`, `STALL=OK`
- reference thermal behavior under sustained/oscillating LLM workloads
- host deadband and slow-fall behavior through journal logs
- reference card thermal limits via `nvidia-smi -q -d TEMPERATURE`

## Reference thermal observations

Under observed workloads around 170-200 W GPU power:

```text
core usually      about 65-68 C
70 C crossings    uncommon
fan target        commonly about 25-34%
HBM               at/below core in observed samples
```

These observations are not guarantees for another case, blower, ambient temperature, power limit, heatsink or GPU.

## Not automatically validated by the regression suite

The Python tests do not prove:

- correct physical pin identification
- safe TACH voltage on another blower
- actual PWM waveform accuracy at very low duty
- airflow direction or heatsink contact
- behavior of another V100 variant
- external PSU/adapter startup behavior
- thermal safety of a new physical build

## Firmware build

The repository contains the complete `.ino` source. Firmware compilation requires an ESP8266 Arduino toolchain; it is not part of the Python regression suite.

## Release checklist

```text
[ ] Python regression tests pass
[ ] Python files compile
[ ] shell scripts pass sh -n
[ ] config example parses
[ ] README/config version notes agree
[ ] wiring diagram matches WIRING.md
[ ] no machine-specific GPU UUID is in the public config
[ ] no private logs/hostnames/serial identifiers are accidentally included
[ ] LICENSE choice has been made if the repository is public
[ ] release ZIP and SHA256 generated
```
