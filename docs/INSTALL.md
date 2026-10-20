# Installation

## 1. Validate hardware first

Before connecting ESP GPIOs to the blower:

1. identify +12 V, GND, PWM and TACH correctly
2. read [WIRING.md](WIRING.md)
3. perform both TACH voltage checks with GPIO4 disconnected
4. verify common ground
5. verify that ESP/Q1 off releases the PWM input and the blower runs full speed

Do not rely on wire colors or assumed transistor pin order.

## 2. Flash the ESP8266

Firmware:

```text
firmware/v100_fan_controller.ino
```

Use an ESP8266 Arduino environment with the appropriate NodeMCU / ESP-12E board definition.

After flashing, open the serial port at 115200 and confirm:

```text
V100FAN READY 3
```

Then send:

```text
HELLO
```

Expected reply:

```text
V100FAN 3
```

## 3. Install Linux prerequisites

Debian/Ubuntu-style host:

```bash
sudo apt update
sudo apt install python3 python3-venv
```

The installer creates a dedicated venv and installs `pyserial`.

## 4. Run host regression tests

Before installation or upgrade:

```bash
python3 tests/test_regressions.py
python3 -m py_compile daemon/v100_fan_daemon.py tools/calibrate_fan.py tools/v100fanctl.py
```

Expected regression result for this snapshot:

```text
Ran 13 tests
OK
```

## 5. Install

```bash
sudo ./install.sh
```

The installer:

- installs daemon to `/opt/v100-fan-controller/v100_fan_daemon.py`
- creates `/opt/v100-fan-controller/venv`
- installs `pyserial`
- installs reference config/example under `/etc/v100-fan-controller/`
- installs the systemd unit
- enables the unit
- does **not** start it automatically on first install

If `/etc/v100-fan-controller/config.ini` already exists, it is preserved.

## 6. Identify serial controller

```bash
ls -l /dev/serial/by-id/
```

Use the stable CP2102 path in production when possible, for example:

```ini
[serial]
port = /dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_XXXX-if00-port0
```

`port = auto` is useful during setup but less deterministic on a host with multiple serial devices.

## 7. Identify the GPU

```bash
./tools/list_gpus.sh
```

or:

```bash
nvidia-smi --query-gpu=index,uuid,name,temperature.gpu --format=csv
```

For a fixed installation, use the full UUID locally:

```ini
[gpu]
selector = GPU-...
```

## 8. Review thermal limits

On the target GPU:

```bash
nvidia-smi -q -d TEMPERATURE
```

Do not assume the reference card's limits are identical to every V100.

Set `critical_temperature_c` below the card's reported maximum operating temperature with appropriate margin.

## 9. Edit config

```bash
sudoedit /etc/v100-fan-controller/config.ini
```

The repository default represents the current reference tuning. See [CONFIGURATION.md](CONFIGURATION.md).

## 10. Run `--check`

```bash
/opt/v100-fan-controller/venv/bin/python \
  /opt/v100-fan-controller/v100_fan_daemon.py \
  --config /etc/v100-fan-controller/config.ini \
  --check
```

A reference-style result looks like:

```text
GPU index=0 name=Tesla V100-SXM2-32GB uuid=GPU-...
temperature=63C curve_target=21%
control=poll 8s, nvidia-smi timeout 2s, temp smoothing 5s (rise_bypass=True), rise 100%/s, fall hold 16s, fall 0.5%/s, deadband 3%, rapid-rise bypass 2C/sample, high-temp bypass 70C
serial=reply timeout 1.2s, retries 2, reconnect 2s
controller=watchdog 30s, stall 3s, recovery 5s, rpm sample 1s, tach 2 pulse/rev, stall lock events 2, critical 80C
```

## 11. Start service

```bash
sudo systemctl start v100-fan-controller
sudo systemctl status v100-fan-controller
```

Monitor:

```bash
sudo journalctl -u v100-fan-controller -f
```

On connection you should see protocol/config confirmation and a fan target with:

```text
WATCHDOG=OK STALL=OK
```

## 12. Verify fail-safe behavior

Before trusting the system unattended, deliberately test the layers you can safely test:

- service stop requests fail-safe speed
- serial-controller disconnect eventually causes ESP watchdog full fan
- reconnect restores normal control
- manual low-duty calibration does not create unexpected stall behavior
- critical threshold logic can be reviewed/tested without intentionally overheating the GPU

Do not intentionally overheat hardware to test the thermal threshold.

## Upgrade procedure

1. keep a copy of `/etc/v100-fan-controller/config.ini`
2. run regression tests on the new source
3. run `sudo ./install.sh`
4. review `/etc/v100-fan-controller/config.ini.example` for new options
5. merge new options into the existing config
6. run `--check`
7. restart the service
8. monitor journal

```bash
sudo systemctl restart v100-fan-controller
sudo journalctl -u v100-fan-controller -n 50 --no-pager
```

## Manual controller CLI

Stop the daemon before taking over the serial port manually:

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

The simple manual CLI opens/closes the serial port for one command and is not intended as the normal persistent watchdog-feeding control loop.
