# Serial Protocol v3

> **Compatibility:** the wire-level greeting remains `V100FAN 3`. The repository was renamed to `sxm2-pcie-fan-controller`, but changing the protocol identifier would break compatibility with deployed v3 firmware/host code and is therefore intentionally out of scope for v0.11.0.

Transport:

```text
115200 baud
ASCII lines
LF terminated
```

The controller may print boot/status messages asynchronously, so the host validates replies by command type rather than assuming the next received line belongs to the last command.

## Boot banner

```text
V100FAN READY 3
```

This is informational and is not the HELLO reply.

## `HELLO`

Request:

```text
HELLO
```

Reply:

```text
V100FAN 3
```

The host treats `V100FAN <other-version>` as an explicit unsupported-protocol error.

## `CFG`

Request fields:

```text
CFG WATCHDOG_MS STALL_MS RECOVERY_MS RPM_MS PPR
```

Example:

```text
CFG 30000 3000 5000 1000 2
```

Reply:

```text
OK CFG WATCHDOG_MS=30000 STALL_MS=3000 RECOVERY_MS=5000 RPM_MS=1000 PPR=2
```

Firmware validates ranges before applying the values.

`CFG` does **not** feed/re-arm the watchdog.

## `CONFIG`

Request:

```text
CONFIG
```

Reply:

```text
CONFIG WATCHDOG_MS=30000 STALL_MS=3000 RECOVERY_MS=5000 RPM_MS=1000 PPR=2
```

`CONFIG` does not feed/re-arm the watchdog.

## `SET n`

Range: `0..100`.

Example:

```text
SET 28
```

Reply:

```text
OK TARGET=28 FAN=28 RPM=2640 WATCHDOG=OK STALL=OK STALLS=0
```

Fields:

- `TARGET`: requested target retained by firmware
- `FAN`: currently applied output; may be 100 during stall recovery even when TARGET is lower
- `RPM`: most recent TACH-derived RPM
- `WATCHDOG`: `OK` or `FAILSAFE`
- `STALL`: `OK` or `RECOVERY`
- `STALLS`: cumulative stall-event count since MCU reset

`SET` feeds/re-arms the watchdog.

`SET 0` is intentionally allowed for calibration/manual testing and does not trigger no-TACH stall logic.

## `STATUS`

Request:

```text
STATUS
```

Reply:

```text
STATUS TARGET=28 FAN=28 RPM=2640 WATCHDOG=OK STALL=OK STALLS=0
```

`STATUS` does not feed/re-arm the watchdog.

## `MAX`

Request:

```text
MAX
```

Reply:

```text
OK TARGET=100 FAN=100 RPM=... WATCHDOG=OK STALL=OK STALLS=0
```

`MAX` feeds/re-arms the watchdog.

## Error replies

Examples:

```text
ERR SET expects 0..100
ERR CFG expects WATCHDOG_MS STALL_MS RECOVERY_MS RPM_MS PPR
ERR unknown command
ERR line too long
```

The host deliberately does not treat an arbitrary stale `ERR` line as the response to a new `SET`/`CFG`. It waits for a reply that matches the current command or until the reply deadline expires.

## Asynchronous firmware messages

Examples:

```text
FAILSAFE serial timeout -> FAN=100
STALL no TACH -> FAN=100 for recovery, count=1
STALL recovery complete -> retry TARGET=10
```

Host code must tolerate these interleaved with command/reply traffic.
