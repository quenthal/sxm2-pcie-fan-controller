# Changelog

## v0.11.0

GitHub/documentation and acoustic-control update based on the tuned reference deployment.

- Public repository name: `sxm2-pcie-fan-controller`.
- Project wording now treats the controlled 12 V blower as part of the SXM2-to-PCIe adapter/cooling assembly rather than an on-card V100 fan.
- Added MIT license.
- Existing `v100-*` runtime/service/install identifiers and the `V100FAN 3` wire-protocol greeting are retained for compatibility with the tested deployment.

### Host daemon

- Added configurable target deadband: `target_deadband_percent`.
- Added upward deadband bypass on rapid raw-temperature rise: `deadband_rapid_rise_c`.
- Added upward deadband bypass above a configured raw temperature: `deadband_bypass_temperature_c`.
- Safety/`force_immediate` requests bypass deadband and normal response shaping.
- Deadband releases requests to the configured minimum so the fan cannot be held permanently above the low floor.
- `--check` reports deadband and bypass values.

### Reference tuning

- Host polling: 8 s.
- GPU temperature smoothing: 5 s with rise bypass enabled.
- Fan curve: `30:10,55:10,60:15,65:25,70:40,75:60,80:100`.
- Minimum automatic fan: 10%.
- Fall hold: 16 s.
- Fall rate: 0.5 percentage points/s.
- Target deadband: 3 percentage points.
- Rapid-rise bypass: +2 C/sample.
- High-temperature deadband bypass: 70 C.
- ESP runtime watchdog: 30 s.
- Host critical temperature: 80 C.

### Tests and documentation

- Regression suite expanded to 13 tests with deadband coverage.
- Added complete GitHub-ready architecture, firmware, host-daemon, protocol, safety, tuning, calibration, deployment and publishing documentation.
- Updated wiring package and regenerated the PNG from the SVG.
- Public reference config intentionally omits machine-specific GPU UUID and CP2102 serial identifier.

ESP firmware serial protocol remains **v3**.


## v0.10

- Reworked `docs/wiring-simple.svg/png` into a clean net-label schematic with no misleading wire crossings or lines through component boxes.
- Daemon HELLO handshake now detects `V100FAN <n>` responses with unsupported protocol versions and reports the detected version plus an explicit protocol-v3 firmware upgrade instruction.
- Calibration handshake reports unsupported protocol versions the same way.
- Added regression tests for old-protocol detection in both daemon and calibration paths.
- Added `package.sh` and clean-package rules so `__pycache__` directories and `.pyc` files are excluded from release ZIPs.

## v0.9

- Corrected `docs/wiring-simple.svg/png`: the 10 kOhm TACH pull-up is on the **fan-side TACH node before** the 2.2 kOhm GPIO series resistor, matching `WIRING.md`; ESP GND is drawn separately from D1/D2/3V3.
- Daemon SET/CFG reply validators no longer accept generic `ERR` lines as current replies; stale ERRs are ignored until a matching acknowledgement arrives or the deadline expires.
- `calibrate_fan.py` now uses command-specific reply matching for SET/MAX/STATUS/CONFIG/CFG and ignores delayed `V100FAN`/generic `ERR` lines outside HELLO.
- Added regression coverage for stale ERR reply handling and delayed HELLO/banner traffic before calibration CFG replies.
- `INSTALL.md` now includes `python3 tests/test_regressions.py` as a routine pre-install check.
- Documentation explicitly states that the 10 kOhm pull-up must not be placed on the GPIO side of the 2.2 kOhm series resistor.

## v0.8

Serial synchronization, upgrade compatibility and TACH bring-up hardening.

### Daemon

- Fixed delayed-reply serial de-synchronization: `SET n` now accepts only an `OK` reply whose `TARGET=n`; stale replies are skipped until the deadline.
- `CFG` replies are likewise validated against the requested runtime values.
- Restored fallback for legacy `[fan] stall_lock_events` when `[safety] stall_lock_events` is absent.
- Watchdog margin warning now includes configured serial retry/reply-timeout budget.
- Restored explanatory comment for why persistent stall-lock counting requires a live GPU and a sub-failsafe target.

### Calibration

- HELLO handshake now retries three times and ignores ESP boot banners, matching daemon behavior.
- Fixed summary formatting so a measured numeric zero is not rendered as an empty value.

### Electrical / docs

- TACH verification is explicitly two-stage with GPIO4 disconnected during both measurements.
- Added a 2.2 kOhm (1-4.7 kOhm acceptable) series resistor between the verified TACH node and GPIO4 as fault-current limiting.
- The series resistor is documented as supplemental protection, not a level shifter.

### Validation

- Added simulated delayed duplicate response coverage for the retry/desync case.
- Added legacy config fallback and calibration boot-banner handshake tests.

## v0.7

Electrical simplification after re-evaluating the TACH protection requirement.

### Electrical / docs

- Default wiring returns to a **single NPN transistor (Q1)** for PWM.
- Fan TACH is connected directly to ESP GPIO4 with a 10 kOhm pull-up to ESP 3.3 V **only after measuring the fan-side TACH voltage with ESP disconnected**.
- Q2 is now an optional level-shifter for non-standard or ambiguous TACH outputs instead of a mandatory stage.
- Removed the default +12 V TACH pull-up from the design.
- Updated wiring diagram, installation guide, firmware comments and validation notes.
- Firmware protocol and daemon behavior remain unchanged from v0.6.

## v0.6

Safety/robustness update based on external code review and re-audit of v0.5.

### Electrical

- TACH is no longer wired directly to ESP8266 GPIO4.
- Added Q2 NPN TACH level-shifter stage to isolate fan-side TACH voltage.
- Updated wiring guide and diagram for two-transistor design.
- Added explicit pre-connection TACH voltage measurement step.

### Daemon

- Added same-open-session serial command retries (`command_retries`, default 2).
- Added configurable command reply timeout.
- Added configurable `nvidia_smi_timeout_seconds` (default 2 s).
- Increased default ESP serial watchdog to 8 s.
- Added watchdog-vs-host-delay warning.
- Deduplicated auto-probed serial paths by realpath.
- Added `critical_temperature_c` (default 85 C): immediate failure_percent + CRITICAL log.
- Config validation now exits with a clear error instead of raw traceback.
- Logs when `minimum_percent` is lower than the configured curve floor.

### Calibration

- Calibration now pushes its own controller `CFG` from config.ini and reads back `CONFIG`.
- Stop detection waits longer than one configured RPM sample window between zero-RPM samples.
- Reports current curve floor and effective automatic minimum.
- Added `--apply-curve-floor` to intentionally lower only the curve points that define the existing low plateau.
- `--write-config` creates timestamped backups instead of one repeatedly overwritten `.bak`.
- Explicit warning that <5% ESP8266 commanded PWM is exploratory until waveform validation.

### Service / docs

- Added `StartLimitIntervalSec=0` to systemd unit.
- Calibration instructions explicitly require stopping the daemon service first.
- Documented that STATUS/CONFIG/CFG do not feed the ESP watchdog; only SET/MAX do.
- Documented long fail-safe recovery behavior as intentional.
- Updated validation/residual-risk notes.

## v0.5

- Runtime-configurable controller watchdog/stall/RPM values via protocol v3 CFG.
- Temperature smoothing with rise bypass.
- Configurable normal fan rise/fall dynamics.

## v0.4

- Configurable fan curve and asymmetric fan-speed ramping.

## v0.3

- Multi-trial fan calibration tool with optional config writing.

## v0.2

- Full-range 0..100% firmware, TACH stall recovery and OCuLink power documentation.

## v0.1

- Initial ESP8266 firmware, Linux daemon, wiring and install package.
