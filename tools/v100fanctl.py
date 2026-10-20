#!/usr/bin/env python3
"""Small manual CLI for the ESP8266 adapter-blower controller."""

import argparse
import sys
import time

import serial


def read_reply(ser: serial.Serial, timeout: float = 1.5) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line and line.startswith(("OK ", "STATUS ", "CONFIG ", "ERR ", "V100FAN ")):
            return line
    raise TimeoutError("No controller reply")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("port")
    p.add_argument("command", choices=["status", "config", "set", "max"])
    p.add_argument("value", nargs="?", type=int)
    p.add_argument("--baud", type=int, default=115200)
    args = p.parse_args()

    if args.command == "set" and (args.value is None or not 0 <= args.value <= 100):
        p.error("set requires value 0..100")

    with serial.Serial(args.port, args.baud, timeout=0.3, write_timeout=1.0) as ser:
        time.sleep(2.0)
        ser.reset_input_buffer()
        if args.command == "status":
            wire = "STATUS"
        elif args.command == "config":
            wire = "CONFIG"
        elif args.command == "max":
            wire = "MAX"
        else:
            wire = f"SET {args.value}"
        ser.write((wire + "\n").encode("ascii"))
        ser.flush()
        print(read_reply(ser))
    return 0


if __name__ == "__main__":
    sys.exit(main())
