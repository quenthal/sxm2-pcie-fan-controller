#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo ./install.sh" >&2
  exit 1
fi

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d /opt/v100-fan-controller /etc/v100-fan-controller
install -m 0755 "$BASE_DIR/daemon/v100_fan_daemon.py" /opt/v100-fan-controller/v100_fan_daemon.py
python3 -m venv /opt/v100-fan-controller/venv
/opt/v100-fan-controller/venv/bin/pip install --upgrade pip
/opt/v100-fan-controller/venv/bin/pip install pyserial

install -m 0644 "$BASE_DIR/config/config.ini" /etc/v100-fan-controller/config.ini.example
if [ ! -f /etc/v100-fan-controller/config.ini ]; then
  install -m 0644 "$BASE_DIR/config/config.ini" /etc/v100-fan-controller/config.ini
else
  echo "Keeping existing /etc/v100-fan-controller/config.ini"
  echo "New defaults/options are available in /etc/v100-fan-controller/config.ini.example"
  echo "v0.11.0: review docs/WIRING.md before connecting TACH; GPIO4 stays disconnected during both voltage checks."
  echo "Legacy [fan] stall_lock_events is still accepted if [safety] does not define it."
fi

install -m 0644 "$BASE_DIR/systemd/v100-fan-controller.service" /etc/systemd/system/v100-fan-controller.service
systemctl daemon-reload
systemctl enable v100-fan-controller.service

echo "Installed and enabled, but not started."
echo "Next: edit /etc/v100-fan-controller/config.ini and follow docs/INSTALL.md."
