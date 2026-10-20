#!/usr/bin/env python3
"""Calibrate a 4-wire adapter blower controlled by the ESP8266 fan controller.

Measures:
* minimum stable running PWM
* minimum reliable starting PWM

The tool always prints measurements and recommendations. With --write-config it
stores calibration metadata and updates [fan] minimum_percent. If the calibrated
minimum is below the configured fan curve floor, --apply-curve-floor can also
lower only the curve points that currently define that floor.

Stop v100-fan-controller.service before running this tool. The finally block
requests MAX so Ctrl-C/error exits fail safe where possible.
"""

from __future__ import annotations

import argparse
import configparser
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import serial

STATUS_RE = re.compile(r"([A-Z_]+)=([^ ]+)")
DEFAULT_RUNNING_VALUES = [20, 15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
DEFAULT_STARTUP_VALUES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20]


@dataclass
class ControllerConfig:
    watchdog_seconds: float
    stall_seconds: float
    recovery_seconds: float
    rpm_sample_seconds: float
    tach_pulses_per_rev: int


@dataclass
class PointResult:
    percent: int
    rpms: list[int] = field(default_factory=list)
    passes: int = 0
    attempts: int = 0

    @property
    def min_rpm(self) -> int:
        return min(self.rpms) if self.rpms else 0

    @property
    def avg_rpm(self) -> int:
        return round(sum(self.rpms) / len(self.rpms)) if self.rpms else 0

    @property
    def reliable(self) -> bool:
        return self.attempts > 0 and self.passes == self.attempts


@dataclass
class CalibrationResult:
    running_min: int | None = None
    starting_min: int | None = None
    recommended_min: int | None = None
    recommended_start: int | None = None
    running_points: dict[int, PointResult] = field(default_factory=dict)
    startup_points: dict[int, PointResult] = field(default_factory=dict)
    startup_measurable: bool = True


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "config.ini"


def parse_values(text: str) -> list[int]:
    values: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        value = int(token)
        if not 0 <= value <= 100:
            raise argparse.ArgumentTypeError("PWM values must be 0..100")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("At least one PWM value is required")
    return values


def parse_curve_text(value: str) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for item in value.split(","):
        t, p = item.strip().split(":", 1)
        points.append((int(t), int(p)))
    if len(points) < 2:
        raise ValueError("fan curve needs at least two points")
    return points


def load_ini(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if not cfg.read(path):
        raise FileNotFoundError(f"Config not found: {path}")
    return cfg


def load_controller_config(cfg: configparser.ConfigParser) -> ControllerConfig:
    return ControllerConfig(
        watchdog_seconds=cfg.getfloat("controller", "watchdog_timeout_seconds", fallback=8.0),
        stall_seconds=cfg.getfloat("controller", "stall_timeout_seconds", fallback=3.0),
        recovery_seconds=cfg.getfloat("controller", "stall_recovery_seconds", fallback=5.0),
        rpm_sample_seconds=cfg.getfloat("controller", "rpm_sample_seconds", fallback=1.0),
        tach_pulses_per_rev=cfg.getint("controller", "tach_pulses_per_rev", fallback=2),
    )


def _command_reply_matches(text: str, line: str) -> bool:
    """Match a reply to the command that caused it.

    Protocol v3 has no request IDs, so generic ERR or V100FAN banner/HELLO lines
    cannot safely be attributed to an arbitrary command. Valid calibration
    commands are host-validated, so stale generic ERR lines are ignored rather
    than allowed to desynchronise the reply stream.
    """
    parts = text.strip().split()
    if not parts:
        return False
    op = parts[0].upper()
    fields = dict(STATUS_RE.findall(line))
    if op == "SET" and len(parts) == 2:
        return line.startswith("OK ") and fields.get("TARGET") == parts[1]
    if op == "MAX":
        return line.startswith("OK ") and fields.get("TARGET") == "100"
    if op == "STATUS":
        return line.startswith("STATUS ")
    if op == "CONFIG":
        return line.startswith("CONFIG ")
    if op == "CFG" and len(parts) == 6:
        expected = {
            "WATCHDOG_MS": parts[1],
            "STALL_MS": parts[2],
            "RECOVERY_MS": parts[3],
            "RPM_MS": parts[4],
            "PPR": parts[5],
        }
        return line.startswith("OK CFG ") and all(
            fields.get(key) == value for key, value in expected.items()
        )
    return False


def command(
    ser: serial.Serial,
    text: str,
    timeout: float = 1.5,
) -> tuple[str, dict[str, str]]:
    ser.write((text + "\n").encode("ascii"))
    ser.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if not _command_reply_matches(text, line):
            continue
        return line, dict(STATUS_RE.findall(line))
    raise TimeoutError(f"No matching reply to {text}")



def handshake(ser: serial.Serial, attempts: int = 3) -> None:
    """Handshake robustly across USB-UART reset banners and slow ESP boots."""
    for attempt in range(1, attempts + 1):
        ser.write(b"HELLO\n")
        ser.flush()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            match = re.fullmatch(r"V100FAN\s+(\d+)", line)
            if match:
                version = match.group(1)
                if version == "3":
                    return
                raise RuntimeError(
                    f"Controller protocol v{version} detected; protocol v3 is required. "
                    "Flash firmware/v100_fan_controller.ino from this package."
                )
            # NodeMCU/Wemos port-open reset can emit V100FAN READY 3 or other
            # startup text before the HELLO response. Ignore it and keep reading.
        if attempt < attempts:
            time.sleep(0.2)
    raise RuntimeError(f"Expected protocol v3 firmware; HELLO failed after {attempts} attempts")

def configure_controller(ser: serial.Serial, cfg: ControllerConfig) -> dict[str, str]:
    wire = (
        f"CFG {round(cfg.watchdog_seconds * 1000)} "
        f"{round(cfg.stall_seconds * 1000)} "
        f"{round(cfg.recovery_seconds * 1000)} "
        f"{round(cfg.rpm_sample_seconds * 1000)} "
        f"{cfg.tach_pulses_per_rev}"
    )
    line, fields = command(ser, wire)
    if not line.startswith("OK CFG "):
        raise RuntimeError(f"Controller rejected calibration CFG: {line}")
    verify_line, verify_fields = command(ser, "CONFIG")
    if not verify_line.startswith("CONFIG "):
        raise RuntimeError(f"Unexpected CONFIG reply: {verify_line}")
    print(f"Controller config: {verify_line}")
    return verify_fields or fields


def status(ser: serial.Serial) -> dict[str, str]:
    return command(ser, "STATUS")[1]


def int_field(fields: dict[str, str], name: str, default: int = 0) -> int:
    try:
        return int(fields.get(name, str(default)))
    except ValueError:
        return default


def keepalive_status(ser: serial.Serial, target: int) -> dict[str, str]:
    # STATUS/CONFIG intentionally do not feed the firmware watchdog. Re-send SET
    # so calibration itself remains the active controller.
    return command(ser, f"SET {target}")[1]


def observe_target(
    ser: serial.Serial,
    target: int,
    seconds: float,
    poll: float,
) -> tuple[bool, int, int]:
    """Return (clean, last_rpm, new_stall_events) for a target interval."""
    before = status(ser)
    stalls_before = int_field(before, "STALLS")
    command(ser, f"SET {target}")

    deadline = time.monotonic() + seconds
    last_rpm = 0
    clean = True
    last_fields = before

    while time.monotonic() < deadline:
        last_fields = keepalive_status(ser, target)
        last_rpm = int_field(last_fields, "RPM")
        stall_state = last_fields.get("STALL", "UNKNOWN")
        stalls_now = int_field(last_fields, "STALLS", stalls_before)
        if stall_state == "RECOVERY" or stalls_now > stalls_before:
            clean = False
            break
        time.sleep(poll)

    stalls_after = int_field(last_fields, "STALLS", stalls_before)
    return clean and last_rpm > 0, last_rpm, max(0, stalls_after - stalls_before)


def wait_until_stopped(
    ser: serial.Serial,
    timeout: float,
    rpm_sample_seconds: float,
) -> bool:
    command(ser, "SET 0")
    deadline = time.monotonic() + timeout
    zero_samples = 0
    # Poll slower than one firmware RPM window so two zero samples cannot simply
    # be the same cached RPM window read twice.
    poll = max(0.25, rpm_sample_seconds * 1.10)

    while time.monotonic() < deadline:
        fields = keepalive_status(ser, 0)
        rpm = int_field(fields, "RPM")
        if rpm == 0:
            zero_samples += 1
            if zero_samples >= 2:
                return True
        else:
            zero_samples = 0
        time.sleep(poll)
    return False


def kick_to_max(ser: serial.Serial, seconds: float = 1.5) -> None:
    command(ser, "MAX")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        command(ser, "MAX")
        time.sleep(0.5)


def running_test(
    ser: serial.Serial,
    values: list[int],
    settle: float,
    trials: int,
    poll: float,
) -> tuple[int | None, dict[int, PointResult]]:
    print("\n=== RUNNING-DUTY CALIBRATION ===")
    print(
        "Each trial starts at 100%, then steps downward. A point passes only "
        "if TACH remains present without ESP stall recovery."
    )

    points = {v: PointResult(v) for v in values}
    trial_minima: list[int] = []

    for trial in range(1, trials + 1):
        print(f"\nRunning trial {trial}/{trials}")
        kick_to_max(ser, 1.5)
        lowest_this_trial: int | None = None

        for value in values:
            point = points[value]
            point.attempts += 1
            print(f"  {value:3d}% ... ", end="", flush=True)
            clean, rpm, stalls = observe_target(ser, value, settle, poll)
            point.rpms.append(rpm)
            if clean:
                point.passes += 1
                lowest_this_trial = value
                print(f"PASS  rpm={rpm}")
            else:
                print(f"FAIL  rpm={rpm} new_stalls={stalls}")
                break

        if lowest_this_trial is not None:
            trial_minima.append(lowest_this_trial)
            print(f"  -> trial minimum: {lowest_this_trial}%")
        else:
            print("  -> no tested running point passed")

    measured = max(trial_minima) if len(trial_minima) == trials else None
    return measured, points


def startup_test(
    ser: serial.Serial,
    values: list[int],
    stop_wait: float,
    start_wait: float,
    trials: int,
    rpm_sample_seconds: float,
    poll: float,
) -> tuple[int | None, dict[int, PointResult], bool]:
    print("\n=== STARTUP-DUTY CALIBRATION ===")
    print(
        "For each candidate the fan is stopped with SET 0, then started from "
        "rest. The first duty that succeeds in every trial is the measured "
        "reliable-start threshold."
    )

    points = {v: PointResult(v) for v in values}
    print("\nChecking whether SET 0 stops the blower ...")
    if not wait_until_stopped(ser, stop_wait, rpm_sample_seconds):
        fields = status(ser)
        rpm = int_field(fields, "RPM")
        print(
            f"  SET 0 did not produce stable 0 RPM (last RPM={rpm}).\n"
            "  Startup threshold cannot be measured with this fan/controller behavior; "
            "skipping startup calibration."
        )
        kick_to_max(ser)
        return None, points, False

    for value in values:
        point = points[value]
        print(f"\nCandidate {value}%")
        for trial in range(1, trials + 1):
            if not wait_until_stopped(ser, stop_wait, rpm_sample_seconds):
                fields = status(ser)
                rpm = int_field(fields, "RPM")
                print(f"  trial {trial}/{trials}: could not stop fan (rpm={rpm}); aborting")
                kick_to_max(ser)
                return None, points, False

            point.attempts += 1
            print(f"  trial {trial}/{trials}: ", end="", flush=True)
            clean, rpm, stalls = observe_target(ser, value, start_wait, poll)
            point.rpms.append(rpm)
            if clean:
                point.passes += 1
                print(f"PASS  rpm={rpm}")
            else:
                print(f"FAIL  rpm={rpm} new_stalls={stalls}")
            kick_to_max(ser, 1.0)

        if point.reliable:
            print(f"  -> {value}% passed all {trials} startup trials")
            return value, points, True

    print("  -> no tested startup duty passed every trial")
    return None, points, True


def recommendation(measured: int | None, margin: int) -> int | None:
    if measured is None:
        return None
    return min(100, measured + max(0, margin))


def print_point_table(title: str, points: dict[int, PointResult]) -> None:
    attempted = [p for p in points.values() if p.attempts]
    if not attempted:
        return
    print(f"\n{title}")
    print("PWM   PASS     AVG RPM   MIN RPM   RESULT")
    print("---   -------  -------   -------   ------")
    for p in sorted(attempted, key=lambda x: x.percent, reverse=True):
        result = "PASS" if p.reliable else "FAIL"
        print(
            f"{p.percent:>3}%  {p.passes:>2}/{p.attempts:<2}     "
            f"{p.avg_rpm:>7}   {p.min_rpm:>7}   {result}"
        )


def curve_floor_from_cfg(cfg: configparser.ConfigParser) -> tuple[int, list[tuple[int, int]]]:
    points = parse_curve_text(cfg.get("fan", "curve"))
    return min(p for _, p in points), points


def print_summary(
    result: CalibrationResult,
    margin: int,
    config_path: Path,
    curve_floor: int,
) -> None:
    print("\n" + "=" * 66)
    print("CALIBRATION SUMMARY")
    print("=" * 66)

    def show(value: int | None) -> str:
        return f"{value}%" if value is not None else "not measured"

    print(f"Minimum stable running PWM : {show(result.running_min)}")
    if result.startup_measurable:
        print(f"Minimum reliable start PWM : {show(result.starting_min)}")
    else:
        print("Minimum reliable start PWM : not measurable (fan did not stop at 0%)")
    print(f"Safety margin               : +{margin} percentage point(s)")
    print(f"Recommended minimum PWM     : {show(result.recommended_min)}")
    print(f"Recommended start PWM       : {show(result.recommended_start)}")
    print(f"Current fan-curve floor     : {curve_floor}%")

    if result.recommended_min is not None:
        effective = max(result.recommended_min, curve_floor)
        print(f"Effective auto minimum now  : {effective}%")
        if result.recommended_min < curve_floor:
            print(
                "NOTE: minimum_percent alone cannot lower automatic fan speed below the "
                f"current {curve_floor}% curve floor. Use --apply-curve-floor with "
                "--write-config if you intentionally want the low curve plateau lowered."
            )
        print("\nSuggested config metadata:")
        print(f"[fan]\nminimum_percent = {result.recommended_min}")
        print("\n[calibration]")
        print(f"measured_running_min_percent = {result.running_min if result.running_min is not None else ''}")
        print(f"recommended_minimum_percent = {result.recommended_min}")
        print(f"measured_starting_min_percent = {result.starting_min if result.starting_min is not None else ''}")
        print(f"recommended_start_percent = {result.recommended_start if result.recommended_start is not None else ''}")
        print(f"\nTo write results:\n  --write-config --config {config_path}")


def replace_fan_key(text: str, key: str, value: str) -> str:
    section = re.search(r"(?ms)^\[fan\]\s*\n(.*?)(?=^\[|\Z)", text)
    if not section:
        raise ValueError("Config has no [fan] section")
    body = section.group(1)
    pattern = rf"(?m)^(\s*{re.escape(key)}\s*=\s*)[^#;\r\n]+"
    if re.search(pattern, body):
        new_body = re.sub(pattern, rf"\g<1>{value}", body, count=1)
    else:
        new_body = body + f"{key} = {value}\n"
    return text[: section.start(1)] + new_body + text[section.end(1) :]


def patch_ini_preserving_comments(
    path: Path,
    result: CalibrationResult,
    args: argparse.Namespace,
) -> None:
    if result.recommended_min is None:
        raise ValueError("Cannot write config without a running-duty recommendation")
    if not path.exists():
        raise FileNotFoundError(path)

    original = path.read_text(encoding="utf-8")
    parsed = load_ini(path)
    curve_floor, curve_points = curve_floor_from_cfg(parsed)
    text = replace_fan_key(original, "minimum_percent", str(result.recommended_min))
    curve_floor_applied = False

    if result.recommended_min < curve_floor:
        if args.apply_curve_floor:
            changed = [
                (t, result.recommended_min if p == curve_floor else p)
                for t, p in curve_points
            ]
            curve_value = ",".join(f"{t}:{p}" for t, p in changed)
            text = replace_fan_key(text, "curve", curve_value)
            curve_floor_applied = True
            print(
                f"Lowered fan-curve floor {curve_floor}% -> {result.recommended_min}% "
                "for the points that defined the old floor."
            )
        else:
            print(
                f"WARNING: curve floor remains {curve_floor}%, so automatic control will "
                f"not actually use {result.recommended_min}% until the curve is lowered."
            )

    timestamp = datetime.now(timezone.utc)
    timestamp_iso = timestamp.isoformat()
    stamp = timestamp.strftime("%Y%m%d-%H%M%S-%f")
    cal_lines = [
        "[calibration]",
        "# Measured by tools/calibrate_fan.py. Hardware limits are distinct from",
        "# the desired normal fan curve; curve_floor_applied records whether this",
        "# calibration run intentionally changed the low curve plateau.",
        f"measured_running_min_percent = {result.running_min if result.running_min is not None else ''}",
        f"recommended_minimum_percent = {result.recommended_min}",
        f"measured_starting_min_percent = {result.starting_min if result.starting_min is not None else ''}",
        f"recommended_start_percent = {result.recommended_start if result.recommended_start is not None else ''}",
        f"margin_percent_points = {args.margin}",
        f"running_trials = {args.running_trials}",
        f"startup_trials = {args.startup_trials}",
        f"curve_floor_before_percent = {curve_floor}",
        f"curve_floor_applied = {'true' if curve_floor_applied else 'false'}",
        f"calibrated_utc = {timestamp_iso}",
    ]
    cal_block = "\n".join(cal_lines) + "\n"

    existing = re.search(r"(?ms)^\[calibration\]\s*\n.*?(?=^\[|\Z)", text)
    if existing:
        text = text[: existing.start()] + cal_block + text[existing.end() :]
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + cal_block

    backup = path.with_name(path.name + f".bak.{stamp}")
    backup.write_text(original, encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    print(f"\nUpdated config: {path}")
    print(f"Timestamped backup: {backup}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("port", help="ESP serial port, preferably /dev/serial/by-id/...")
    p.add_argument(
        "mode",
        nargs="?",
        choices=["all", "running", "startup"],
        default="all",
        help="calibration mode (default: all)",
    )
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--settle", type=float, default=5.0, help="seconds observed per running-duty point")
    p.add_argument("--stop-wait", type=float, default=5.0, help="seconds allowed for SET 0 to stop fan")
    p.add_argument("--start-wait", type=float, default=2.5, help="seconds observed for a startup attempt")
    p.add_argument("--running-trials", type=int, default=3)
    p.add_argument("--startup-trials", type=int, default=5)
    p.add_argument("--margin", type=int, default=2, help="safety margin in percentage points")
    p.add_argument(
        "--running-values",
        type=parse_values,
        default=DEFAULT_RUNNING_VALUES,
        help="comma-separated descending PWM values",
    )
    p.add_argument(
        "--startup-values",
        type=parse_values,
        default=DEFAULT_STARTUP_VALUES,
        help="comma-separated ascending PWM values",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="config.ini used for controller CFG and optional update",
    )
    p.add_argument(
        "--write-config",
        action="store_true",
        help="write recommendation/calibration metadata to config.ini",
    )
    p.add_argument(
        "--apply-curve-floor",
        action="store_true",
        help="with --write-config, lower current minimum fan-curve points to the recommended minimum",
    )
    args = p.parse_args()

    if args.running_trials < 1 or args.startup_trials < 1:
        p.error("trial counts must be >= 1")
    if args.margin < 0:
        p.error("--margin must be >= 0")
    if args.settle <= 0 or args.stop_wait <= 0 or args.start_wait <= 0:
        p.error("timings must be > 0")
    if args.apply_curve_floor and not args.write_config:
        p.error("--apply-curve-floor requires --write-config")

    try:
        ini = load_ini(args.config)
        controller_cfg = load_controller_config(ini)
        curve_floor, _ = curve_floor_from_cfg(ini)
    except (OSError, ValueError, configparser.Error) as exc:
        print(f"ERROR: invalid config: {exc}", file=sys.stderr)
        return 2

    tested_values = list(args.running_values) + list(args.startup_values)
    if tested_values and min(tested_values) < 5:
        print(
            "NOTE: PWM points below 5% are exploratory on ESP8266 software PWM. "
            "Treat them as commanded values until the actual 25 kHz waveform is "
            "verified with an oscilloscope/logic analyzer."
        )

    print("WARNING: stop v100-fan-controller.service before calibration.")
    print("Run with the V100 idle and monitor GPU temperature independently.")
    print("Ctrl-C/error exits request MAX in the finally block.")

    result = CalibrationResult()
    # Poll no faster than half an RPM window for normal observations. The stop
    # detector itself uses >1 complete RPM window between zero samples.
    observation_poll = max(0.25, controller_cfg.rpm_sample_seconds * 0.5)

    with serial.Serial(args.port, args.baud, timeout=0.3, write_timeout=1.0) as ser:
        time.sleep(2.0)
        ser.reset_input_buffer()
        try:
            handshake(ser)
            configure_controller(ser, controller_cfg)
            # CONFIG does not feed watchdog by design; arm it immediately with MAX.
            command(ser, "MAX")

            if args.mode in ("all", "running"):
                result.running_min, result.running_points = running_test(
                    ser,
                    list(args.running_values),
                    args.settle,
                    args.running_trials,
                    observation_poll,
                )
                result.recommended_min = recommendation(result.running_min, args.margin)

            if args.mode in ("all", "startup"):
                (
                    result.starting_min,
                    result.startup_points,
                    result.startup_measurable,
                ) = startup_test(
                    ser,
                    list(args.startup_values),
                    args.stop_wait,
                    args.start_wait,
                    args.startup_trials,
                    controller_cfg.rpm_sample_seconds,
                    observation_poll,
                )
                result.recommended_start = recommendation(result.starting_min, args.margin)
        finally:
            try:
                command(ser, "MAX")
            except Exception:
                pass

    print_point_table("Running-duty measurements", result.running_points)
    print_point_table("Startup-duty measurements", result.startup_points)
    print_summary(result, args.margin, args.config, curve_floor)

    if args.write_config:
        if result.recommended_min is None:
            print(
                "\nConfig was NOT modified: a reliable running minimum was not measured. "
                "Run mode 'all' or 'running' successfully first.",
                file=sys.stderr,
            )
            return 2
        patch_ini_preserving_comments(args.config, result, args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted; MAX requested before exit where possible.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: calibration failed: {exc}", file=sys.stderr)
        sys.exit(1)
