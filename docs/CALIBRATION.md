# Fan Calibration

Tool: `tools/calibrate_fan.py`

Calibration is used to measure the actual blower rather than assuming a safe low PWM percentage.

## Before calibration

1. Keep the V100 idle and monitor temperature independently.
2. Stop the daemon so two processes do not fight for the same serial controller.
3. Use the stable `/dev/serial/by-id/...` path if available.
4. Be prepared for the blower to stop during `SET 0` startup testing.

```bash
sudo systemctl stop v100-fan-controller
```

## Run

From the repository root:

```bash
python3 tools/calibrate_fan.py \
  /dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_XXXX-if00-port0 \
  --config ./config/config.ini
```

The calibration tool pushes the controller runtime `CFG`, verifies it, then tests running and startup behavior.

## What it measures

The tool reports:

- minimum stable running PWM
- minimum reliable startup PWM
- RPM at tested points
- new stall events during tests
- recommended minimum with configurable safety margin
- current fan-curve floor and effective automatic minimum

By default it only prints recommendations.

To write results into a config:

```bash
python3 tools/calibrate_fan.py /dev/serial/by-id/usb-... \
  --config ./config/config.ini \
  --write-config
```

To intentionally lower only the existing low fan-curve plateau as well:

```bash
python3 tools/calibrate_fan.py /dev/serial/by-id/usb-... \
  --config ./config/config.ini \
  --write-config \
  --apply-curve-floor
```

Config backups are timestamped.

## Reference blower measurements

The physical blower used in the reference system was characterized manually and with the controller tools.

| Commanded PWM | Observed behavior |
|---:|---|
| 20% | about 2070 RPM |
| 10% | about 1170-1200 RPM once settled; reliable startup |
| 9% | about 1110-1140 RPM; reliable startup |
| 8% | about 1080-1140 RPM while running; one cold-start failure and one slower successful start were observed |
| 7% | unstable/lumpy behavior; sometimes around 750-870 RPM before recovering |
| 6% | stalls; ESP recovery is triggered |

Cold-start observations on this blower:

- 9-10%: reliable, roughly 1.8 s startup in the observed tests
- 8%: mixed result; one failure and one slower successful start around 3.8 s

The selected automatic floor is therefore:

```ini
minimum_percent = 10
```

This is intentionally conservative. A fan that can *continue running* at a low duty does not necessarily *start reliably* at that same duty.

## Very-low PWM caveat

The ESP8266 firmware accepts 0..100% so the physical blower can be explored. Values below roughly 5% should be treated as commanded test points rather than laboratory-accurate electrical duty unless the 25 kHz waveform is verified with an oscilloscope or logic analyzer.

Normal automatic operation in the reference profile never goes below 10%.

## Historical `STALLS`

`STALLS` is cumulative until the MCU resets. Old calibration stalls are not active current faults. When interpreting test output, look for **new increases** in the counter.

## After calibration

Restart the daemon:

```bash
sudo systemctl start v100-fan-controller
sudo journalctl -u v100-fan-controller -f
```
