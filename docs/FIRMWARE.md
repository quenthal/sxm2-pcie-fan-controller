# ESP8266 Firmware

Source: `firmware/v100_fan_controller.ino`

## Role

The ESP8266 provides the real-time electrical fan interface and local safety behavior. It does not read GPU temperature and does not require Wi-Fi.

## Pins

```cpp
PWM_PIN  = GPIO5  // D1
TACH_PIN = GPIO4  // D2
```

## PWM

- frequency: 25 kHz
- Arduino PWM range: 0..255
- fan command range: 0..100%
- output is inverted because the ESP drives an NPN pull-down stage

The firmware interprets fan percentage as the percentage of time the blower PWM input should be released HIGH. Q1 is ON when the ESP output is HIGH, so GPIO duty is `100 - requested_fan_percent`.

## Boot behavior

`setup()` establishes the electrical fail-safe before other initialization:

1. PWM GPIO becomes output.
2. GPIO is driven LOW -> Q1 OFF -> PWM line released.
3. firmware applies 100% fan.
4. TACH interrupt is attached on falling edges.
5. Wi-Fi is disabled.
6. serial starts at 115200 baud.
7. controller prints:

```text
V100FAN READY 3
```

## Protocol version

The firmware implements **protocol v3**.

Handshake:

```text
HELLO
V100FAN 3
```

A host daemon expecting v3 rejects an older `V100FAN <n>` protocol explicitly.

## Runtime controller configuration

Firmware compile-time defaults are intentionally safe:

```text
watchdog            8000 ms
stall timeout       3000 ms
stall recovery      5000 ms
RPM sample          1000 ms
TACH pulses/rev     2
```

The Linux daemon pushes its configured runtime values after every reconnect with:

```text
CFG WATCHDOG_MS STALL_MS RECOVERY_MS RPM_MS PPR
```

The current reference host profile sends:

```text
CFG 30000 3000 5000 1000 2
```

No firmware reflash is needed when only these host-configured runtime values change.

## Watchdog

Only active fan-control commands feed the watchdog:

- `SET n`
- `MAX`

These do **not** feed it:

- `HELLO`
- `STATUS`
- `CONFIG`
- `CFG`

If no `SET`/`MAX` arrives before `commandTimeoutMs`, firmware calls `forceMaximumFan()` and prints:

```text
FAILSAFE serial timeout -> FAN=100
```

## TACH and RPM

TACH pulses increment an interrupt counter on GPIO4 falling edges.

Every configured RPM window:

```text
RPM = pulses * 60000 / (elapsed_ms * pulses_per_rev)
```

The reference fan is configured for 2 pulses/revolution. With a 1-second window this naturally quantizes readings in approximately 30 RPM steps.

## Stall guard

Stall detection applies only when:

- watchdog is not active, and
- requested target is non-zero.

If a non-zero target has had enough startup time and no TACH activity is seen for the stall timeout:

1. cumulative `STALLS` counter increments
2. fan is forced to 100%
3. controller enters recovery for `stallRecoveryMs`
4. after recovery it retries the original requested target

Example messages:

```text
STALL no TACH -> FAN=100 for recovery, count=1
STALL recovery complete -> retry TARGET=10
```

`SET 0` is treated as an intentional calibration/manual stop and does not trigger stall recovery.

## Cumulative stall count

`STALLS` is cumulative for the current MCU uptime. It does not reset merely because a later target succeeds. A host-side daemon should treat an increase in the counter as a new event rather than treating any non-zero historical count as an active fault.

## Commands

See [PROTOCOL.md](PROTOCOL.md) for the complete command/reply contract.

## Flashing

Use an ESP8266 Arduino-compatible environment and select the board definition matching the NodeMCU / ESP-12E development board in use.

The firmware depends only on the ESP8266 Arduino core and the standard Arduino APIs used in the source. Wi-Fi is explicitly disabled at runtime.

After flashing, confirm the USB serial boot banner before connecting the fan-control signals.
