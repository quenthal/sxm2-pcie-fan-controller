#!/usr/bin/env python3
"""NVIDIA GPU temperature -> ESP8266 adapter-blower PWM daemon.

The host reads NVIDIA GPU temperature with nvidia-smi and sends a fan target
percentage over USB serial. The ESP8266 independently fails to 100% if serial
commands stop and temporarily forces 100% when a non-zero target has no TACH.
"""

from __future__ import annotations

import argparse
import configparser
import logging
import math
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import serial
from serial.tools import list_ports

LOG = logging.getLogger("v100-fan")
STOP = False


@dataclass(frozen=True)
class GpuInfo:
    index: str
    uuid: str
    name: str
    temperature: int


@dataclass
class Settings:
    port: str
    baud: int
    serial_timeout: float
    command_reply_timeout_seconds: float
    command_retries: int
    reconnect_seconds: float
    gpu_selector: str
    poll_seconds: float
    nvidia_smi_timeout_seconds: float
    temperature_smoothing_seconds: float
    temperature_rise_bypass: bool
    curve: list[tuple[int, int]]
    minimum_percent: int
    failure_percent: int
    rise_rate_percent_per_second: float
    fall_rate_percent_per_second: float
    fall_hold_seconds: float
    target_deadband_percent: float
    deadband_rapid_rise_c: float
    deadband_bypass_temperature_c: float
    stall_lock_events: int
    critical_temperature_c: float
    watchdog_timeout_seconds: float
    stall_timeout_seconds: float
    stall_recovery_seconds: float
    rpm_sample_seconds: float
    tach_pulses_per_rev: int
    log_level: str


def parse_curve(value: str) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            t_s, p_s = item.split(":", 1)
            t, p = int(t_s), int(p_s)
        except ValueError as exc:
            raise ValueError(f"Invalid curve point {item!r}; expected TEMP:PERCENT") from exc
        if not (0 <= p <= 100):
            raise ValueError(f"Fan percentage out of range in {item!r}")
        points.append((t, p))
    points.sort()
    if len(points) < 2:
        raise ValueError("Fan curve needs at least two points")
    if len({t for t, _ in points}) != len(points):
        raise ValueError("Fan curve temperatures must be unique")
    return points


def load_settings(path: Path) -> Settings:
    cfg = configparser.ConfigParser()
    if not cfg.read(path):
        raise FileNotFoundError(f"Config not found: {path}")

    return Settings(
        port=cfg.get("serial", "port", fallback="auto").strip(),
        baud=cfg.getint("serial", "baud", fallback=115200),
        serial_timeout=cfg.getfloat("serial", "timeout_seconds", fallback=0.25),
        command_reply_timeout_seconds=cfg.getfloat(
            "serial", "command_reply_timeout_seconds", fallback=1.2
        ),
        command_retries=cfg.getint("serial", "command_retries", fallback=2),
        reconnect_seconds=cfg.getfloat("serial", "reconnect_seconds", fallback=2.0),
        gpu_selector=cfg.get("gpu", "selector", fallback="V100").strip(),
        poll_seconds=cfg.getfloat("gpu", "poll_seconds", fallback=1.0),
        nvidia_smi_timeout_seconds=cfg.getfloat(
            "gpu", "nvidia_smi_timeout_seconds", fallback=2.0
        ),
        temperature_smoothing_seconds=cfg.getfloat(
            "gpu", "temperature_smoothing_seconds", fallback=3.0
        ),
        temperature_rise_bypass=cfg.getboolean(
            "gpu", "temperature_rise_bypass", fallback=True
        ),
        curve=parse_curve(cfg.get("fan", "curve")),
        minimum_percent=cfg.getint("fan", "minimum_percent", fallback=10),
        failure_percent=cfg.getint("fan", "failure_percent", fallback=100),
        rise_rate_percent_per_second=cfg.getfloat(
            "fan", "rise_rate_percent_per_second", fallback=100.0
        ),
        fall_rate_percent_per_second=cfg.getfloat(
            "fan", "fall_rate_percent_per_second", fallback=3.0
        ),
        fall_hold_seconds=cfg.getfloat("fan", "fall_hold_seconds", fallback=8.0),
        target_deadband_percent=cfg.getfloat(
            "fan", "target_deadband_percent", fallback=0.0
        ),
        deadband_rapid_rise_c=cfg.getfloat(
            "fan", "deadband_rapid_rise_c", fallback=0.0
        ),
        deadband_bypass_temperature_c=cfg.getfloat(
            "fan", "deadband_bypass_temperature_c", fallback=0.0
        ),
        stall_lock_events=(
            cfg.getint("safety", "stall_lock_events")
            if cfg.has_option("safety", "stall_lock_events")
            else cfg.getint("fan", "stall_lock_events", fallback=2)
        ),
        critical_temperature_c=cfg.getfloat(
            "safety", "critical_temperature_c", fallback=85.0
        ),
        watchdog_timeout_seconds=cfg.getfloat(
            "controller", "watchdog_timeout_seconds", fallback=8.0
        ),
        stall_timeout_seconds=cfg.getfloat(
            "controller", "stall_timeout_seconds", fallback=3.0
        ),
        stall_recovery_seconds=cfg.getfloat(
            "controller", "stall_recovery_seconds", fallback=5.0
        ),
        rpm_sample_seconds=cfg.getfloat(
            "controller", "rpm_sample_seconds", fallback=1.0
        ),
        tach_pulses_per_rev=cfg.getint(
            "controller", "tach_pulses_per_rev", fallback=2
        ),
        log_level=cfg.get("logging", "level", fallback="INFO").upper(),
    )


def validate_settings(s: Settings) -> list[str]:
    errors: list[str] = []
    if not 0 <= s.minimum_percent <= 100:
        errors.append("minimum_percent must be 0..100")
    if not 0 <= s.failure_percent <= 100:
        errors.append("failure_percent must be 0..100")
    if s.rise_rate_percent_per_second < 0:
        errors.append("rise_rate_percent_per_second must be >= 0")
    if s.fall_rate_percent_per_second < 0:
        errors.append("fall_rate_percent_per_second must be >= 0")
    if s.fall_hold_seconds < 0:
        errors.append("fall_hold_seconds must be >= 0")
    if not 0 <= s.target_deadband_percent <= 20:
        errors.append("target_deadband_percent must be 0..20")
    if not 0 <= s.deadband_rapid_rise_c <= 20:
        errors.append("deadband_rapid_rise_c must be 0..20")
    if (
        s.deadband_bypass_temperature_c != 0
        and not 30 <= s.deadband_bypass_temperature_c <= 120
    ):
        errors.append("deadband_bypass_temperature_c must be 0 (disabled) or 30..120")
    if s.stall_lock_events < 0:
        errors.append("stall_lock_events must be >= 0")
    if s.poll_seconds <= 0:
        errors.append("poll_seconds must be > 0")
    if not 0.2 <= s.nvidia_smi_timeout_seconds <= 30:
        errors.append("nvidia_smi_timeout_seconds must be 0.2..30")
    if s.temperature_smoothing_seconds < 0:
        errors.append("temperature_smoothing_seconds must be >= 0")
    if not 0.1 <= s.serial_timeout <= 5:
        errors.append("serial timeout_seconds must be 0.1..5")
    if not 0.2 <= s.command_reply_timeout_seconds <= 10:
        errors.append("command_reply_timeout_seconds must be 0.2..10")
    if not 0 <= s.command_retries <= 10:
        errors.append("command_retries must be 0..10")
    if s.reconnect_seconds < 0:
        errors.append("reconnect_seconds must be >= 0")
    if not 0.5 <= s.watchdog_timeout_seconds <= 60:
        errors.append("watchdog_timeout_seconds must be 0.5..60")
    if not 0.25 <= s.stall_timeout_seconds <= 60:
        errors.append("stall_timeout_seconds must be 0.25..60")
    if not 0.25 <= s.stall_recovery_seconds <= 60:
        errors.append("stall_recovery_seconds must be 0.25..60")
    if not 0.1 <= s.rpm_sample_seconds <= 5:
        errors.append("rpm_sample_seconds must be 0.1..5")
    if not 1 <= s.tach_pulses_per_rev <= 16:
        errors.append("tach_pulses_per_rev must be 1..16")
    if s.critical_temperature_c != 0 and not 30 <= s.critical_temperature_c <= 120:
        errors.append("critical_temperature_c must be 0 (disabled) or 30..120")
    return errors


def fan_percent_for_temp(temp: float, curve: list[tuple[int, int]], minimum: int) -> int:
    """Piecewise-linear interpolation through the configured curve."""
    if temp <= curve[0][0]:
        return max(minimum, curve[0][1])
    if temp >= curve[-1][0]:
        return max(minimum, curve[-1][1])

    for (t0, p0), (t1, p1) in zip(curve, curve[1:]):
        if t0 <= temp <= t1:
            fraction = (temp - t0) / (t1 - t0)
            p = round(p0 + fraction * (p1 - p0))
            return max(minimum, min(100, p))
    return 100


def smooth_temperature(
    raw_temp: float,
    previous: float | None,
    dt: float,
    smoothing_seconds: float,
    rise_bypass: bool,
) -> float:
    if previous is None or smoothing_seconds <= 0:
        return float(raw_temp)
    if rise_bypass and raw_temp >= previous:
        return float(raw_temp)
    if dt <= 0:
        return previous
    alpha = 1.0 - math.exp(-dt / smoothing_seconds)
    return previous + alpha * (float(raw_temp) - previous)


def shape_fan_target(
    requested: int,
    current: float,
    dt: float,
    now: float,
    fall_hold_started: float | None,
    settings: Settings,
    *,
    force_immediate: bool = False,
) -> tuple[float, float | None]:
    requested = max(0, min(100, requested))
    if force_immediate:
        return float(requested), None
    if requested >= current:
        fall_hold_started = None
        if settings.rise_rate_percent_per_second <= 0:
            return float(requested), fall_hold_started
        step = settings.rise_rate_percent_per_second * max(0.0, dt)
        return min(float(requested), current + step), fall_hold_started
    if fall_hold_started is None:
        fall_hold_started = now
    if now - fall_hold_started < settings.fall_hold_seconds:
        return current, fall_hold_started
    if settings.fall_rate_percent_per_second <= 0:
        return float(requested), fall_hold_started
    step = settings.fall_rate_percent_per_second * max(0.0, dt)
    return max(float(requested), current - step), fall_hold_started


def apply_target_deadband(
    requested: int,
    current: float,
    raw_temperature: float | None,
    previous_raw_temperature: float | None,
    settings: Settings,
    *,
    force_immediate: bool = False,
) -> tuple[float, str | None]:
    """Suppress small target changes while keeping upward safety escapes immediate."""
    requested_f = float(max(0, min(100, requested)))
    if force_immediate or settings.target_deadband_percent <= 0:
        return requested_f, None

    delta = requested_f - current
    if abs(delta) < 1e-9 or abs(delta) > settings.target_deadband_percent:
        return requested_f, None

    # Do not let the deadband keep the fan permanently above its configured floor.
    if delta < 0 and requested_f <= settings.minimum_percent:
        return requested_f, None

    if delta > 0 and raw_temperature is not None:
        if (
            settings.deadband_bypass_temperature_c > 0
            and raw_temperature >= settings.deadband_bypass_temperature_c
        ):
            return requested_f, None
        if (
            settings.deadband_rapid_rise_c > 0
            and previous_raw_temperature is not None
            and raw_temperature - previous_raw_temperature >= settings.deadband_rapid_rise_c
        ):
            return requested_f, None

    return current, f"deadband hold {int(round(current))}%"


def query_gpus(timeout_seconds: float) -> list[GpuInfo]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    gpus: list[GpuInfo] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",", 3)]
        if len(parts) != 4:
            continue
        index, uuid, name, temp_s = parts
        gpus.append(GpuInfo(index=index, uuid=uuid, name=name, temperature=int(temp_s)))
    if not gpus:
        raise RuntimeError("nvidia-smi returned no GPUs")
    return gpus


def select_gpu(gpus: Iterable[GpuInfo], selector: str) -> GpuInfo:
    items = list(gpus)
    selector = selector.strip()
    if selector.isdigit():
        matches = [g for g in items if g.index == selector]
    elif selector.upper().startswith("GPU-"):
        matches = [g for g in items if g.uuid.upper() == selector.upper()]
    else:
        needle = selector.lower()
        matches = [g for g in items if needle in g.name.lower()]
    if not matches:
        names = "; ".join(f"{g.index}: {g.name} [{g.uuid}]" for g in items)
        raise RuntimeError(f"GPU selector {selector!r} matched nothing. Available: {names}")
    if len(matches) > 1:
        names = "; ".join(f"{g.index}: {g.name} [{g.uuid}]" for g in matches)
        raise RuntimeError(f"GPU selector {selector!r} is ambiguous: {names}")
    return matches[0]


def read_nonempty_line(ser: serial.Serial, deadline: float) -> str | None:
    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        if line:
            return line
    return None


class UnsupportedControllerProtocol(RuntimeError):
    """An ESP fan controller answered, but with an unsupported protocol version."""

    def __init__(self, version: str):
        self.version = version
        super().__init__(
            f"ESP fan controller protocol v{version} detected; protocol v3 is required. "
            "Flash firmware/v100_fan_controller.ino from this package."
        )


def handshake(ser: serial.Serial) -> bool:
    # Opening common NodeMCU/Wemos USB-UART bridges can reset the ESP.
    time.sleep(2.0)
    ser.reset_input_buffer()
    for _ in range(3):
        ser.write(b"HELLO\n")
        ser.flush()
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            line = read_nonempty_line(ser, deadline)
            if line is None:
                break
            match = re.fullmatch(r"V100FAN\s+(\d+)", line)
            if match:
                version = match.group(1)
                if version == "3":
                    return True
                raise UnsupportedControllerProtocol(version)
            # Ignore boot banners such as "V100FAN READY 3" and unrelated text.
        time.sleep(0.2)
    return False


def candidate_ports(preferred: str) -> list[str]:
    if preferred.lower() != "auto":
        return [preferred]

    candidates: list[str] = []
    by_id = Path("/dev/serial/by-id")
    if by_id.is_dir():
        candidates.extend(str(p) for p in sorted(by_id.iterdir()))
    candidates.extend(p.device for p in list_ports.comports())

    # /dev/serial/by-id/foo and /dev/ttyUSB0 can be the same device. Probe it once,
    # preferring the stable by-id spelling when available.
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        real = os.path.realpath(candidate)
        key = real or candidate
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def connect_controller(settings: Settings) -> serial.Serial:
    last_error: Exception | None = None
    unsupported: list[tuple[str, str]] = []
    ports = candidate_ports(settings.port)
    if not ports:
        raise RuntimeError("No serial ports found")

    for port in ports:
        try:
            LOG.info("Trying fan controller on %s", port)
            ser = serial.Serial(
                port=port,
                baudrate=settings.baud,
                timeout=settings.serial_timeout,
                write_timeout=settings.serial_timeout,
            )
            try:
                ser.dtr = False
                ser.rts = False
            except OSError:
                pass
            try:
                if handshake(ser):
                    LOG.info("Connected to ESP fan controller on %s", port)
                    return ser
            except UnsupportedControllerProtocol as exc:
                unsupported.append((port, exc.version))
                LOG.error(
                    "ESP fan controller found on %s with protocol v%s; protocol v3 is required. "
                    "Flash firmware/v100_fan_controller.ino from this package.",
                    port,
                    exc.version,
                )
            ser.close()
        except Exception as exc:
            last_error = exc
            LOG.debug("Serial probe failed on %s: %s", port, exc)

    if unsupported:
        details = ", ".join(f"{port}=protocol v{version}" for port, version in unsupported)
        raise RuntimeError(
            f"ESP fan controller found, but firmware is incompatible ({details}). "
            "Protocol v3 is required; flash firmware/v100_fan_controller.ino from this package."
        )
    if last_error:
        raise RuntimeError(f"Fan controller not found; last serial error: {last_error}")
    raise RuntimeError("Fan controller not found")


def send_command(
    ser: serial.Serial,
    command: str,
    *,
    expect_reply: bool = True,
    reply_timeout: float = 1.2,
    retries: int = 0,
    reply_validator: Callable[[str], bool] | None = None,
) -> str | None:
    """Send an idempotent controller command, retrying in the same open session.

    A delayed reply from an earlier command may arrive after a retry.  The optional
    validator lets the caller reject stale-but-well-formed replies and keep reading
    until the current command's deadline.  This prevents the serial response stream
    from becoming permanently one command out of phase.
    """
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        ser.write((command.strip() + "\n").encode("ascii"))
        ser.flush()
        if not expect_reply:
            return None

        deadline = time.monotonic() + reply_timeout
        while time.monotonic() < deadline:
            line = read_nonempty_line(ser, deadline)
            if line is None:
                break
            if not line.startswith(("OK ", "STATUS ", "CONFIG ", "ERR ", "V100FAN ")):
                continue
            if reply_validator is not None and not reply_validator(line):
                LOG.debug("Ignoring stale/unmatched controller reply for %r: %s", command, line)
                continue
            return line

        if attempt < attempts:
            LOG.warning(
                "No matching reply to %r (attempt %d/%d); retrying without reopening serial",
                command,
                attempt,
                attempts,
            )
    raise TimeoutError(f"No matching reply to {command!r} after {attempts} attempt(s)")


def parse_status_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    return fields


def controller_command(
    ser: serial.Serial,
    settings: Settings,
    command: str,
    *,
    reply_validator: Callable[[str], bool] | None = None,
) -> str:
    response = send_command(
        ser,
        command,
        reply_timeout=settings.command_reply_timeout_seconds,
        retries=settings.command_retries,
        reply_validator=reply_validator,
    )
    if response is None:
        raise RuntimeError(f"No controller response for {command!r}")
    return response


def set_fan(ser: serial.Serial, percent: int, settings: Settings) -> tuple[str, dict[str, str]]:
    expected_target = str(percent)

    def matches_set_reply(line: str) -> bool:
        # Host-side validation guarantees SET is in range. Do not accept a generic
        # ERR as belonging to this request: without request IDs it could be a late
        # error from an earlier command and would reintroduce response-stream desync.
        if not line.startswith("OK "):
            return False
        return parse_status_fields(line).get("TARGET") == expected_target

    response = controller_command(
        ser,
        settings,
        f"SET {percent}",
        reply_validator=matches_set_reply,
    )
    if not response.startswith("OK "):
        raise RuntimeError(f"Unexpected controller reply: {response!r}")
    fields = parse_status_fields(response)
    if fields.get("TARGET") != expected_target:
        raise RuntimeError(
            f"Controller acknowledged wrong target: requested={percent}, reply={response!r}"
        )
    return response, fields


def configure_controller(ser: serial.Serial, settings: Settings) -> str:
    watchdog_ms = round(settings.watchdog_timeout_seconds * 1000)
    stall_ms = round(settings.stall_timeout_seconds * 1000)
    recovery_ms = round(settings.stall_recovery_seconds * 1000)
    rpm_ms = round(settings.rpm_sample_seconds * 1000)
    expected = {
        "WATCHDOG_MS": str(watchdog_ms),
        "STALL_MS": str(stall_ms),
        "RECOVERY_MS": str(recovery_ms),
        "RPM_MS": str(rpm_ms),
        "PPR": str(settings.tach_pulses_per_rev),
    }

    def matches_cfg_reply(line: str) -> bool:
        # As with SET, ignore generic ERR lines because protocol v3 has no request
        # ID and a delayed ERR from an older command cannot be safely attributed.
        if not line.startswith("OK CFG "):
            return False
        fields = parse_status_fields(line)
        return all(fields.get(key) == value for key, value in expected.items())

    response = controller_command(
        ser,
        settings,
        f"CFG {watchdog_ms} {stall_ms} {recovery_ms} {rpm_ms} {settings.tach_pulses_per_rev}",
        reply_validator=matches_cfg_reply,
    )
    if not response.startswith("OK CFG "):
        raise RuntimeError(
            "Controller did not accept runtime configuration; flash protocol v3 firmware "
            f"(reply={response!r})"
        )
    return response


def fail_safe(ser: serial.Serial | None, percent: int = 100) -> None:
    if ser is None:
        return
    try:
        command = "MAX" if percent >= 100 else f"SET {percent}"
        send_command(ser, command, expect_reply=False)
    except Exception:
        pass


def signal_handler(signum, frame):  # noqa: ANN001, ARG001
    global STOP
    STOP = True


def run(settings: Settings) -> int:
    global STOP
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    ser: serial.Serial | None = None
    last_logged_target: int | None = None
    selected_identity: str | None = None
    last_stall_count = 0
    stall_events_for_live_gpu = 0
    stall_locked = False
    critical_active = False
    commanded_percent = float(settings.failure_percent)
    last_control_time = time.monotonic()
    fall_hold_started: float | None = None
    filtered_temperature: float | None = None
    last_temperature_time = time.monotonic()
    previous_raw_temperature: float | None = None

    while not STOP:
        if ser is None or not ser.is_open:
            try:
                ser = connect_controller(settings)
                cfg_reply = configure_controller(ser, settings)
                LOG.info("Controller runtime config: %s", cfg_reply)
                _, fields = set_fan(ser, settings.failure_percent, settings)
                last_stall_count = int(fields.get("STALLS", "0"))
                commanded_percent = float(settings.failure_percent)
                last_control_time = time.monotonic()
                fall_hold_started = None
                filtered_temperature = None
                last_temperature_time = last_control_time
                previous_raw_temperature = None
            except Exception as exc:
                LOG.error("Controller connection failed: %s", exc)
                if ser:
                    try:
                        ser.close()
                    except Exception:
                        pass
                ser = None
                time.sleep(settings.reconnect_seconds)
                continue

        try:
            gpu_ok = False
            force_immediate = False
            try:
                gpu = select_gpu(
                    query_gpus(settings.nvidia_smi_timeout_seconds), settings.gpu_selector
                )
                gpu_ok = True
                identity = f"{gpu.name} [{gpu.uuid}]"
                if identity != selected_identity:
                    LOG.info("Controlling GPU %s (index %s)", identity, gpu.index)
                    selected_identity = identity

                if (
                    settings.critical_temperature_c > 0
                    and gpu.temperature >= settings.critical_temperature_c
                ):
                    raw_target = settings.failure_percent
                    force_immediate = True
                    reason = (
                        f"CRITICAL GPU temperature {gpu.temperature} C >= "
                        f"{settings.critical_temperature_c:g} C"
                    )
                    if not critical_active:
                        LOG.critical("%s; forcing %d%%", reason, settings.failure_percent)
                    critical_active = True
                    filtered_temperature = float(gpu.temperature)
                    last_temperature_time = time.monotonic()
                else:
                    if critical_active:
                        LOG.warning(
                            "GPU temperature back below critical threshold: %d C < %.1f C",
                            gpu.temperature,
                            settings.critical_temperature_c,
                        )
                    critical_active = False
                    now_temp = time.monotonic()
                    temp_dt = max(0.0, now_temp - last_temperature_time)
                    last_temperature_time = now_temp
                    filtered_temperature = smooth_temperature(
                        gpu.temperature,
                        filtered_temperature,
                        temp_dt,
                        settings.temperature_smoothing_seconds,
                        settings.temperature_rise_bypass,
                    )
                    if stall_locked:
                        raw_target = settings.failure_percent
                        force_immediate = True
                        reason = "fan stall lock; restart service after inspection"
                    else:
                        raw_target = fan_percent_for_temp(
                            filtered_temperature, settings.curve, settings.minimum_percent
                        )
                        if settings.temperature_smoothing_seconds > 0:
                            reason = (
                                f"GPU raw={gpu.temperature} C filtered={filtered_temperature:.1f} C, "
                                f"curve={raw_target}%"
                            )
                        else:
                            reason = f"GPU {gpu.temperature} C, curve={raw_target}%"
            except Exception as exc:
                raw_target = settings.failure_percent
                force_immediate = True
                reason = f"nvidia-smi error: {exc}"
                LOG.error("GPU temperature unavailable; forcing %d%%: %s", raw_target, exc)
                filtered_temperature = None
                last_temperature_time = time.monotonic()
                critical_active = False

            requested_target, deadband_note = apply_target_deadband(
                raw_target,
                commanded_percent,
                float(gpu.temperature) if gpu_ok else None,
                previous_raw_temperature,
                settings,
                force_immediate=force_immediate,
            )
            if deadband_note:
                reason = f"{reason}; {deadband_note}"
            previous_raw_temperature = float(gpu.temperature) if gpu_ok else None

            now = time.monotonic()
            dt = max(0.0, now - last_control_time)
            last_control_time = now
            commanded_percent, fall_hold_started = shape_fan_target(
                requested_target,
                commanded_percent,
                dt,
                now,
                fall_hold_started,
                settings,
                force_immediate=force_immediate,
            )
            target = int(round(commanded_percent))

            reply, fields = set_fan(ser, target, settings)
            stall_count = int(fields.get("STALLS", str(last_stall_count)))
            stall_state = fields.get("STALL", "UNKNOWN")
            rpm = fields.get("RPM", "?")
            applied = fields.get("FAN", str(target))

            if stall_count > last_stall_count:
                new_events = stall_count - last_stall_count
                last_stall_count = stall_count
                LOG.warning(
                    "Controller detected %d new no-TACH stall event(s); target=%d%% applied=%s%% rpm=%s",
                    new_events,
                    target,
                    applied,
                    rpm,
                )
                # Only count stalls toward the persistent host-side lock when the
                # selected GPU is actually present and we were intentionally asking
                # for less than fail-safe speed.  This avoids turning an unpowered
                # eGPU / missing SFX supply into a persistent stall lock.
                if gpu_ok and target < settings.failure_percent:
                    stall_events_for_live_gpu += new_events
                    if (
                        settings.stall_lock_events > 0
                        and stall_events_for_live_gpu >= settings.stall_lock_events
                    ):
                        stall_locked = True
                        LOG.error(
                            "Repeated fan stalls with live GPU; locking target to %d%% until service restart",
                            settings.failure_percent,
                        )

            if stall_state == "RECOVERY":
                LOG.warning(
                    "ESP stall recovery active: target=%d%% actual=%s%% rpm=%s",
                    target,
                    applied,
                    rpm,
                )

            effective_target = settings.failure_percent if stall_locked else target
            if effective_target != last_logged_target:
                LOG.info(
                    "Fan target %d%% (%s); controller: %s",
                    effective_target,
                    reason,
                    reply,
                )
                last_logged_target = effective_target
            else:
                LOG.debug("Fan %d%% (%s); %s", effective_target, reason, reply)

            time.sleep(settings.poll_seconds)

        except Exception as exc:
            LOG.error("Serial/controller error after retries: %s", exc)
            fail_safe(ser, settings.failure_percent)
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(settings.reconnect_seconds)

    LOG.info("Stopping; requesting fail-safe fan speed")
    fail_safe(ser, settings.failure_percent)
    if ser:
        try:
            ser.close()
        except Exception:
            pass
    return 0


def print_check(settings: Settings) -> int:
    gpu = select_gpu(query_gpus(settings.nvidia_smi_timeout_seconds), settings.gpu_selector)
    target = fan_percent_for_temp(gpu.temperature, settings.curve, settings.minimum_percent)
    if settings.critical_temperature_c > 0 and gpu.temperature >= settings.critical_temperature_c:
        target = settings.failure_percent
    print(f"GPU index={gpu.index} name={gpu.name} uuid={gpu.uuid}")
    print(f"temperature={gpu.temperature}C curve_target={target}%")
    print(
        "control="
        f"poll {settings.poll_seconds:g}s, nvidia-smi timeout {settings.nvidia_smi_timeout_seconds:g}s, "
        f"temp smoothing {settings.temperature_smoothing_seconds:g}s "
        f"(rise_bypass={settings.temperature_rise_bypass}), "
        f"rise {settings.rise_rate_percent_per_second:g}%/s, "
        f"fall hold {settings.fall_hold_seconds:g}s, "
        f"fall {settings.fall_rate_percent_per_second:g}%/s, "
        f"deadband {settings.target_deadband_percent:g}%, "
        f"rapid-rise bypass {settings.deadband_rapid_rise_c:g}C/sample, "
        f"high-temp bypass {settings.deadband_bypass_temperature_c:g}C"
    )
    print(
        "serial="
        f"reply timeout {settings.command_reply_timeout_seconds:g}s, "
        f"retries {settings.command_retries}, reconnect {settings.reconnect_seconds:g}s"
    )
    print(
        "controller="
        f"watchdog {settings.watchdog_timeout_seconds:g}s, "
        f"stall {settings.stall_timeout_seconds:g}s, "
        f"recovery {settings.stall_recovery_seconds:g}s, "
        f"rpm sample {settings.rpm_sample_seconds:g}s, "
        f"tach {settings.tach_pulses_per_rev} pulse/rev, "
        f"stall lock events {settings.stall_lock_events}, "
        f"critical {settings.critical_temperature_c:g}C"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="/etc/v100-fan-controller/config.ini",
        help="INI configuration file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read config and print selected GPU/current target without opening serial",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(Path(args.config))
        errors = validate_settings(settings)
        if errors:
            raise ValueError("; ".join(errors))
    except (OSError, ValueError, configparser.Error) as exc:
        print(f"ERROR: invalid configuration: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Conservative warning budget.  SET retries normally re-arm the ESP watchdog
    # as soon as the command reaches the MCU, but include their reply-wait budget
    # here so custom retry/timeout values cannot silently erase the safety margin.
    retry_budget = settings.command_retries * settings.command_reply_timeout_seconds
    estimated_host_gap = (
        settings.poll_seconds
        + settings.nvidia_smi_timeout_seconds
        + retry_budget
    )
    warning_margin = 1.0
    if settings.watchdog_timeout_seconds <= estimated_host_gap + warning_margin:
        LOG.warning(
            "watchdog_timeout_seconds %.2fs leaves little margin over a conservative "
            "host-delay estimate %.2fs + %.1fs margin "
            "(poll %.2fs + nvidia-smi %.2fs + %d retries x %.2fs)",
            settings.watchdog_timeout_seconds,
            estimated_host_gap,
            warning_margin,
            settings.poll_seconds,
            settings.nvidia_smi_timeout_seconds,
            settings.command_retries,
            settings.command_reply_timeout_seconds,
        )

    curve_floor = min(p for _, p in settings.curve)
    if settings.minimum_percent < curve_floor:
        LOG.info(
            "minimum_percent=%d is below the curve's lowest point=%d; effective automatic "
            "minimum remains %d%% until the curve is lowered",
            settings.minimum_percent,
            curve_floor,
            curve_floor,
        )

    if args.check:
        try:
            return print_check(settings)
        except Exception as exc:
            print(f"ERROR: check failed: {exc}", file=sys.stderr)
            return 1

    return run(settings)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
