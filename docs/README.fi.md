# Suomenkielinen pikaopas

Tämä repo sisältää koko toimivan SXM2-to-PCIe-adapterin 12 V 4-wire blower-ohjaimen. Referenssikokoonpanossa jäähdytettävä GPU on Tesla V100-SXM2-32GB:

- ESP8266-firmware
- Linux/Python-daemon
- systemd-palvelu
- konfiguraatio
- kalibrointi- ja käsiohjaustyökalut
- regressiotestit
- täydellinen kytkentädokumentaatio
- tämän V100-SXM2-32GB + SXM2-to-PCIe/OCuLink -referenssikokoonpanon viritysmuistiinpanot

## Kytkentä lyhyesti

```text
D1/GPIO5 -> 2.2k -> BC337 base
BC337 base -> 100k -> GND
BC337 emitter -> GND
BC337 collector -> blower PWM

blower TACH -> 10k -> ESP 3V3
blower TACH -> 2.2k -> D2/GPIO4

blower +12V/GND tulee adapterilta/SFX:ltä
ESP saa virran hostin USB:stä
kaikki maat yhteiset
```

TACH pitää mitata ennen GPIO4:n kytkemistä. Referenssiblowerin raw TACH oli noin 0.105 V ilman omaa 3.3 V pull-upia, joten se käyttäytyi open-collector/open-drain -tyyppisesti.

## Nykyinen referenssiviritys

```ini
poll_seconds = 8.0
temperature_smoothing_seconds = 5.0
temperature_rise_bypass = true

curve = 30:10,55:10,60:15,65:25,70:40,75:60,80:100
minimum_percent = 10
failure_percent = 100
rise_rate_percent_per_second = 100
fall_hold_seconds = 16
fall_rate_percent_per_second = 0.5
target_deadband_percent = 3
deadband_rapid_rise_c = 2
deadband_bypass_temperature_c = 70

watchdog_timeout_seconds = 30
stall_timeout_seconds = 3
stall_recovery_seconds = 5
critical_temperature_c = 80
```

## Referenssikortin omat lämpörajat

`nvidia-smi -q -d TEMPERATURE` ilmoitti:

```text
GPU Max Operating Temp     83 C
Memory Max Operating Temp  85 C
GPU Slowdown Temp          87 C
GPU Shutdown Temp          90 C
```

170-200 W kuormassa core on käytännössä ollut useimmiten noin 65-68 C ja fan noin 25-34 %. HBM on ollut core-lämmön tasalla tai sitä alempana.

## Miksi deadband?

`target_deadband_percent = 3` vähentää pieniä PWM/RPM-muutoksia ja siten puhaltimen äänen sävelkorkeuden jatkuvaa vaeltelua.

Nousupuolen turvallisuus säilyy, koska pieni nousukin pääsee heti läpi jos:

- raw-lämpö nousee vähintään 2 C yhden pollin aikana, tai
- raw-lämpö on vähintään 70 C.

80 C critical-raja ohittaa koko normaalin säätöketjun ja pyytää heti 100 %.

## Aloita näistä

- `README.md`
- `docs/WIRING.md`
- `docs/INSTALL.md`
- `docs/CONFIGURATION.md`
- `docs/TUNING.md`
- `docs/SAFETY.md`
- `docs/GITHUB.md`

`docs/GITHUB.md` sisältää valmiit komennot, joilla tästä hakemistosta tehdään Git-repo ja työnnetään se GitHubiin.
