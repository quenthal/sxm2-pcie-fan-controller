# GitHub publication guide

The public repository name is **`sxm2-pcie-fan-controller`**. The project is MIT licensed.

The first public release is **v0.11.0**; ESP serial protocol remains **v3**.

## 1. Work from a development machine

There is no reason to install Git on the Proxmox/GPU host just to publish this project. A Windows laptop with Git for Windows or GitHub Desktop is a cleaner place to maintain the repository.

Clone the already-created empty repository, for example in PowerShell:

```powershell
cd $HOME\source
git clone https://github.com/YOUR-USER/sxm2-pcie-fan-controller.git
cd sxm2-pcie-fan-controller
```

Copy the contents of the cleaned release tree into that clone. Do not copy the enclosing ZIP directory as an extra nested folder.

## 2. Check for machine-specific identifiers

The reusable repository must not contain the reference host's exact GPU UUID or CP2102 serial identifier. In PowerShell:

```powershell
Get-ChildItem -Recurse -File |
  Select-String -Pattern 'GPU-[0-9a-fA-F-]{36}|CP2102_USB_to_UART_Bridge_Controller_[^\\/ ]+-if'
```

No match is expected. The hostname may appear in private notes, but it is not required by the public repository.

## 3. Validate before the first commit

On Windows with Python available:

```powershell
python tests/test_regressions.py
python -m py_compile daemon/v100_fan_daemon.py tools/calibrate_fan.py tools/v100fanctl.py
```

The regression suite should report 13 passing tests.

Shell syntax checks can be run on Linux/WSL later; the source tree has also been validated before packaging.

## 4. Review exactly what will be committed

```powershell
git status
git diff -- .
```

For an empty repository, `git diff` does not show untracked files until they are staged. A useful first-pass review is:

```powershell
git add -N .
git diff -- .
```

Then stage the actual snapshot:

```powershell
git add .
git status
```

## 5. First commit and push

```powershell
git commit -m "Initial public release: v0.11.0"
git push -u origin main
```

If the empty GitHub repository was created with a README/license/gitignore already present, pull/reconcile that commit before pushing rather than force-pushing over it.

## 6. Tag the first release

```powershell
git tag -a v0.11.0 -m "v0.11.0: documented SXM2 PCIe adapter blower controller"
git push origin v0.11.0
```

## 7. Optional release ZIP

On Linux/WSL:

```bash
./package.sh ../sxm2-pcie-fan-controller-v0.11.0.zip
sha256sum ../sxm2-pcie-fan-controller-v0.11.0.zip
```

A GitHub Release can attach the generated ZIP and checksum, although GitHub already provides source archives automatically for each tag.

## 8. Suggested repository description

```text
ESP8266 + Linux temperature-controlled 4-wire blower controller for SXM2-to-PCIe adapter/cooling assemblies, with TACH feedback and layered fail-safes. V100-SXM2 reference deployment.
```

Suggested topics:

```text
sxm2
pcie
nvidia
v100
esp8266
oculink
fan-control
linux
hardware
```

## 9. Suggested v0.11.0 release notes

```text
v0.11.0 documents the complete reference SXM2-to-PCIe adapter blower controller:
ESP8266 firmware, Linux daemon, wiring, protocol, calibration, safety model and
tested V100-SXM2 reference tuning. The host control adds a configurable PWM-target
deadband while preserving rapid upward thermal response. Reference settings use
8 s polling, a 30 s MCU watchdog, 10% automatic fan minimum, 80 C host critical
fail-safe, 3-point target deadband and fast-rise/slow-fall shaping.

The public project is named sxm2-pcie-fan-controller. Existing v100-* deployment
identifiers and the V100FAN 3 serial greeting are retained for compatibility.
```

## 10. Future workflow

For tuning-only changes:

```bash
# edit config/config.ini and docs as appropriate
python3 tests/test_regressions.py
git diff
git add .
git commit -m "Tune fan response"
git push
```

For daemon/firmware changes, run the full validation set in `docs/VALIDATION.md` before tagging a release.

## 11. Keep machine-specific config out of Git

The repository `config/config.ini` is a portable reference profile. Keep the real host values only in:

```text
/etc/v100-fan-controller/config.ini
```

The `v100-fan-controller` install path is a compatibility identifier retained from the tested reference deployment; it does not mean the blower is physically part of the V100 module.
