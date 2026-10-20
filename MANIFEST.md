# Repository Manifest

## Executable/source files

| Path | Purpose |
|---|---|
| `firmware/v100_fan_controller.ino` | Complete ESP8266 protocol-v3 firmware |
| `daemon/v100_fan_daemon.py` | Complete Linux temperature-to-fan daemon, including v0.11.0 deadband logic |
| `systemd/v100-fan-controller.service` | systemd unit |
| `install.sh` | root installer; preserves an existing installed config |
| `package.sh` | release ZIP builder |
| `tools/calibrate_fan.py` | low-duty running/start calibration tool |
| `tools/v100fanctl.py` | simple manual one-command serial CLI |
| `tools/list_gpus.sh` | GPU selector helper |
| `tests/test_regressions.py` | 13 host-side regression tests |
| `requirements.txt` | Python runtime dependency declaration |

## Configuration

| Path | Purpose |
|---|---|
| `config/config.ini` | Portable reference config reflecting the current tuned profile |

The public config intentionally uses generic serial/GPU selectors rather than the reference host's exact identifiers.

## Documentation

| Path | Purpose |
|---|---|
| `README.md` | Main GitHub overview and quick start |
| `LICENSE` | MIT software/documentation license |
| `docs/README.fi.md` | Finnish quick overview |
| `docs/ARCHITECTURE.md` | System/control architecture |
| `docs/WIRING.md` | Exact electrical wiring and TACH validation procedure |
| `docs/wiring-simple.svg` | Editable wiring diagram |
| `docs/wiring-simple.png` | Rendered wiring diagram |
| `docs/FIRMWARE.md` | ESP8266 behavior and firmware design |
| `docs/HOST_DAEMON.md` | Linux daemon internals and control path |
| `docs/CONFIGURATION.md` | All config keys and current reference values |
| `docs/PROTOCOL.md` | Serial protocol v3 contract |
| `docs/CALIBRATION.md` | Calibration workflow and measured blower data |
| `docs/TUNING.md` | Thermal/acoustic tuning rationale |
| `docs/SAFETY.md` | Layered fail-safe model and residual risks |
| `docs/REFERENCE_DEPLOYMENT.md` | AOOSTAR/V100/OCuLink reference build and measured values |
| `docs/INSTALL.md` | Installation/upgrade procedure |
| `docs/VALIDATION.md` | Regression and physical validation status |
| `docs/TOOLS.md` | Utility command reference |
| `docs/TROUBLESHOOTING.md` | Common failure modes |
| `docs/POWER.md` | Separate OCuLink/SFX power-on notes |
| `docs/GITHUB.md` | Git/GitHub publication and release checklist |
| `CHANGELOG.md` | Version history |

## Intentionally not included

The following are not part of the public/reusable package:

- exact GPU UUID from the reference host
- exact CP2102 serial identifier from the reference host
- system journal captures
- local workload/model identifiers
- local ad-hoc test scripts whose exact current source was not part of the packaged v0.10/v0.11.0 source tree

## Version relationship

- repository/public snapshot: **v0.11.0**
- ESP serial protocol: **v3**
- firmware control behavior: protocol-v3 firmware carried forward; host-side deadband is a daemon feature

## Compatibility identifiers

The public repository name is `sxm2-pcie-fan-controller`. The v0.11.0 snapshot deliberately retains `v100-fan-controller` systemd/install paths, source filenames and the `V100FAN 3` protocol greeting because those identifiers are part of the already-tested reference deployment. A future rename should be handled as an explicit migration with backward compatibility rather than as a documentation-only change.
