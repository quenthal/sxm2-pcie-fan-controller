# Host Tools

## `tools/list_gpus.sh`

Lists candidate NVIDIA GPUs using the same key fields used for selection:

```bash
./tools/list_gpus.sh
```

Output format:

```text
index, uuid, name, temperature
```

Use the full UUID in a fixed installation when you want unambiguous selection.

## `tools/v100fanctl.py`

Simple one-command serial CLI.

Stop the daemon first so only one process owns the serial port:

```bash
sudo systemctl stop v100-fan-controller
```

Examples:

```bash
python3 tools/v100fanctl.py /dev/serial/by-id/usb-... status
python3 tools/v100fanctl.py /dev/serial/by-id/usb-... config
python3 tools/v100fanctl.py /dev/serial/by-id/usb-... set 20
python3 tools/v100fanctl.py /dev/serial/by-id/usb-... max
```

This tool opens the port, sends one command, prints a reply and closes the port. It is not a persistent watchdog-feeding load-test tool.

## `tools/calibrate_fan.py`

Measures the blower's practical low-duty limits.

```bash
python3 tools/calibrate_fan.py /dev/serial/by-id/usb-... \
  --config ./config/config.ini
```

Important options can be viewed with:

```bash
python3 tools/calibrate_fan.py --help
```

The tool can:

- test multiple running-duty points
- test repeated cold starts after `SET 0`
- read RPM and new stall counts
- add a safety margin
- write measured/recommended values to config
- optionally adjust the low curve plateau
- create timestamped config backups

See [CALIBRATION.md](CALIBRATION.md).

## Service/journal commands

Status:

```bash
systemctl status v100-fan-controller
```

Follow logs:

```bash
journalctl -u v100-fan-controller -f
```

Last 50 lines:

```bash
journalctl -u v100-fan-controller -n 50 --no-pager
```

One-hour tuning capture:

```bash
journalctl -u v100-fan-controller \
  --since "60 min ago" \
  -o short-iso-precise \
  > v100-fan-60min.log
```

## GPU telemetry

Quick interactive view:

```bash
watch -n 5 'nvidia-smi --query-gpu=temperature.gpu,temperature.memory,power.draw,utilization.gpu,memory.used --format=csv,noheader'
```

Longer CSV capture:

```bash
nvidia-smi \
  --query-gpu=timestamp,temperature.gpu,power.draw,utilization.gpu,memory.used \
  --format=csv,noheader,nounits \
  -l 2 > gpu.csv
```

Not every driver/GPU exposes every optional `nvidia-smi` query field; check the target system.
