#!/usr/bin/env python3
"""Small stdlib regression tests for bugs fixed through v0.11.0."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Allow importing project modules on systems where pyserial is not installed.
serial_mod = types.ModuleType("serial")
serial_mod.Serial = object
serial_tools = types.ModuleType("serial.tools")
list_ports = types.ModuleType("serial.tools.list_ports")
list_ports.comports = lambda: []
serial_tools.list_ports = list_ports
sys.modules.setdefault("serial", serial_mod)
sys.modules.setdefault("serial.tools", serial_tools)
sys.modules.setdefault("serial.tools.list_ports", list_ports)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


daemon = load_module("v100_fan_daemon_test", ROOT / "daemon" / "v100_fan_daemon.py")
cal = load_module("calibrate_fan_test", ROOT / "tools" / "calibrate_fan.py")


class DelayedReplySerial:
    def __init__(self):
        self.events: list[tuple[float, bytes]] = []
        self.write_count: dict[str, int] = {}

    def write(self, data: bytes) -> int:
        cmd = data.decode().strip()
        self.write_count[cmd] = self.write_count.get(cmd, 0) + 1
        now = time.monotonic()
        if cmd == "SET 82":
            delay = 0.070 if self.write_count[cmd] == 1 else 0.040
            self.events.append(
                (now + delay, b"OK TARGET=82 FAN=82 RPM=5330 WATCHDOG=OK STALL=OK STALLS=0\n")
            )
        elif cmd == "SET 74":
            self.events.append(
                (now + 0.050, b"OK TARGET=74 FAN=74 RPM=4810 WATCHDOG=OK STALL=OK STALLS=0\n")
            )
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        end = time.monotonic() + 0.005
        while time.monotonic() < end:
            self.events.sort(key=lambda item: item[0])
            if self.events and self.events[0][0] <= time.monotonic():
                return self.events.pop(0)[1]
            time.sleep(0.001)
        return b""




class StaleErrThenSetSerial:
    def __init__(self):
        self.lines = [
            b"ERR stale previous command\n",
            b"OK TARGET=42 FAN=42 RPM=3200 WATCHDOG=OK STALL=OK STALLS=0\n",
        ]

    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""


class LateHelloBeforeCfgSerial:
    def __init__(self):
        self.lines = [
            b"V100FAN 3\n",
            b"ERR stale previous command\n",
            b"OK CFG WATCHDOG_MS=8000 STALL_MS=3000 RECOVERY_MS=5000 RPM_MS=1000 PPR=2\n",
        ]

    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""



class OldProtocolSerial:
    def __init__(self, version: str = "2"):
        self.version = version
        self.lines = [f"V100FAN {version}\n".encode()]

    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""

    def reset_input_buffer(self) -> None:
        pass

class BannerSerial:
    def __init__(self):
        self.lines = [b"V100FAN READY 3\n", b"V100FAN 3\n"]

    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""


def settings():
    return daemon.Settings(
        port="x",
        baud=115200,
        serial_timeout=0.01,
        command_reply_timeout_seconds=0.05,
        command_retries=2,
        reconnect_seconds=1,
        gpu_selector="V100",
        poll_seconds=1,
        nvidia_smi_timeout_seconds=2,
        temperature_smoothing_seconds=3,
        temperature_rise_bypass=True,
        curve=[(30, 10), (80, 100)],
        minimum_percent=10,
        failure_percent=100,
        rise_rate_percent_per_second=100,
        fall_rate_percent_per_second=3,
        fall_hold_seconds=8,
        target_deadband_percent=3,
        deadband_rapid_rise_c=2,
        deadband_bypass_temperature_c=70,
        stall_lock_events=2,
        critical_temperature_c=85,
        watchdog_timeout_seconds=8,
        stall_timeout_seconds=3,
        stall_recovery_seconds=5,
        rpm_sample_seconds=1,
        tach_pulses_per_rev=2,
        log_level="INFO",
    )


class RegressionTests(unittest.TestCase):
    def test_delayed_duplicate_reply_does_not_desync_next_set(self):
        ser = DelayedReplySerial()
        _, first = daemon.set_fan(ser, 82, settings())
        _, second = daemon.set_fan(ser, 74, settings())
        self.assertEqual(first["TARGET"], "82")
        self.assertEqual(second["TARGET"], "74")

    def test_legacy_fan_stall_lock_fallback(self):
        text = """[serial]\nport=auto\n[gpu]\nselector=V100\n[fan]\ncurve=30:10,80:100\nstall_lock_events=0\n[controller]\n[logging]\n"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.ini"
            path.write_text(text)
            self.assertEqual(daemon.load_settings(path).stall_lock_events, 0)

    def test_safety_stall_lock_overrides_legacy_location(self):
        text = """[serial]\nport=auto\n[gpu]\nselector=V100\n[fan]\ncurve=30:10,80:100\nstall_lock_events=0\n[safety]\nstall_lock_events=3\n[controller]\n[logging]\n"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.ini"
            path.write_text(text)
            self.assertEqual(daemon.load_settings(path).stall_lock_events, 3)

    def test_target_deadband_holds_small_changes(self):
        s = settings()
        up, up_note = daemon.apply_target_deadband(31, 28.0, 67, 66, s)
        down, down_note = daemon.apply_target_deadband(25, 28.0, 66, 66, s)
        self.assertEqual(up, 28.0)
        self.assertEqual(down, 28.0)
        self.assertIsNotNone(up_note)
        self.assertIsNotNone(down_note)

    def test_target_deadband_releases_at_minimum(self):
        s = settings()
        target, note = daemon.apply_target_deadband(10, 13.0, 54, 54, s)
        self.assertEqual(target, 10.0)
        self.assertIsNone(note)

    def test_target_deadband_bypasses_rapid_rise(self):
        s = settings()
        target, note = daemon.apply_target_deadband(31, 28.0, 67, 65, s)
        self.assertEqual(target, 31.0)
        self.assertIsNone(note)

    def test_target_deadband_bypasses_high_temperature(self):
        s = settings()
        target, note = daemon.apply_target_deadband(31, 28.0, 70, 69, s)
        self.assertEqual(target, 31.0)
        self.assertIsNone(note)

    def test_target_deadband_force_immediate_bypasses_hold(self):
        s = settings()
        target, note = daemon.apply_target_deadband(
            29, 28.0, 60, 60, s, force_immediate=True
        )
        self.assertEqual(target, 29.0)
        self.assertIsNone(note)

    def test_calibration_handshake_ignores_boot_banner(self):
        cal.handshake(BannerSerial())

    def test_stale_err_does_not_satisfy_set_reply(self):
        ser = StaleErrThenSetSerial()
        _, fields = daemon.set_fan(ser, 42, settings())
        self.assertEqual(fields["TARGET"], "42")

    def test_calibration_cfg_ignores_late_hello_and_stale_err(self):
        ser = LateHelloBeforeCfgSerial()
        line, fields = cal.command(ser, "CFG 8000 3000 5000 1000 2")
        self.assertTrue(line.startswith("OK CFG "))
        self.assertEqual(fields["WATCHDOG_MS"], "8000")

    def test_daemon_handshake_reports_old_protocol(self):
        old_sleep = daemon.time.sleep
        daemon.time.sleep = lambda _seconds: None
        try:
            with self.assertRaises(daemon.UnsupportedControllerProtocol) as ctx:
                daemon.handshake(OldProtocolSerial("2"))
            self.assertIn("protocol v2", str(ctx.exception))
            self.assertIn("protocol v3 is required", str(ctx.exception))
        finally:
            daemon.time.sleep = old_sleep

    def test_calibration_handshake_reports_old_protocol(self):
        with self.assertRaises(RuntimeError) as ctx:
            cal.handshake(OldProtocolSerial("2"), attempts=1)
        self.assertIn("protocol v2", str(ctx.exception))
        self.assertIn("protocol v3 is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
