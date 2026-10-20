# Wiring

## Reference hardware

The controlled blower is part of the external SXM2-to-PCIe adapter/cooling assembly; it is not an on-card fan integrated into the V100 SXM2 module.

- ESP8266 NodeMCU / ESP-12E development board
- CP2102 USB-UART on the controller board
- 12 V 4-wire blower
- Q1: BC337 NPN (BC547-family parts can also work if pinout/current are suitable)
- 2 x 2.2 kOhm resistors
- 1 x 100 kOhm resistor
- 1 x 10 kOhm resistor
- common ground between adapter/SFX, blower and ESP8266

## Topology

Blower power remains on the adapter/SFX path:

```text
adapter +12 V ----------------------------> blower +12 V
adapter GND ----+-------------------------> blower GND
                +-------------------------> ESP GND
                +-------------------------> Q1 emitter
```

The adapter's original PWM and TACH signal paths are not continued to the blower/controller logic.

### PWM

```text
ESP D1 / GPIO5 ---- 2.2k ----> Q1 base
ESP GND ----------- 100k ----> Q1 base
Q1 emitter ------------------> common GND
Q1 collector ----------------> blower PWM
```

The NPN is used as an open-collector style pull-down. The firmware intentionally inverts the ESP PWM duty so that the percentage reported by the host/controller corresponds to the blower's requested fan duty.

### TACH

```text
blower TACH --------+---- 2.2k ----> ESP D2 / GPIO4
                    |
                   10k
                    |
                  ESP 3V3
```

**The 10 kOhm pull-up belongs on the fan-side TACH node before the 2.2 kOhm GPIO series resistor.** The 2.2 kOhm resistor is fault-current limiting; it is not a voltage divider or level shifter.

## Reference pin map

| Function | ESP8266 pin | GPIO | Notes |
|---|---|---:|---|
| PWM drive | D1 | 5 | through 2.2 kOhm to Q1 base |
| TACH input | D2 | 4 | through 2.2 kOhm series resistor |
| TACH pull-up | 3V3 | - | 10 kOhm to fan-side TACH node |
| Ground | GND | - | common with adapter/blower/Q1 emitter |

GPIO16/D0 was not used for final TACH input because GPIO4 supports the normal external interrupt path required by the firmware.

## Electrical fail-safe

The PWM stage is intentionally arranged so that:

```text
ESP GPIO5 LOW / ESP off / reset
      -> Q1 off
      -> blower PWM input released
      -> standard 4-wire fan behavior: full speed
```

This is the first safety layer and does not depend on the Linux daemon.

## Mandatory TACH bring-up procedure

Do not connect an unknown blower TACH directly to ESP8266 GPIO4 without measuring it.

### Step A - raw fan TACH

Keep GPIO4 disconnected and do not add the project's 10 kOhm pull-up yet.

1. Power the blower normally from the adapter/SFX.
2. Confirm fan GND and +12 V.
3. Measure fan TACH relative to GND while the blower spins.
4. If the fan actively presents a clear high level above 3.3 V, do not use the direct GPIO topology.

On the reference blower, raw TACH measured about **0.105 V** with the added pull-up disconnected, consistent with an open-collector/open-drain style output.

### Step B - add the 3.3 V pull-up

Keep GPIO4 physically disconnected.

1. Add 10 kOhm from the fan-side TACH node to ESP 3.3 V.
2. Measure the TACH node again.
3. Verify that the high level stays safely around 3.3 V.
4. Only after that measurement, connect the TACH node through 2.2 kOhm to D2/GPIO4.

A multimeter does not show pulse waveform quality as well as an oscilloscope or logic analyzer. If the result is ambiguous, use a level-shifting stage instead of guessing.

## Optional Q2 TACH level shifter

For a non-standard TACH output, a second NPN can isolate the ESP input:

```text
fan TACH ---- 47k ----> Q2 base
Q2 base ----- 100k ---> GND
Q2 emitter -----------> GND
Q2 collector --+------> ESP D2 / GPIO4
               |
              10k
               |
             ESP 3V3
```

This inverts the TACH polarity but does not change the pulse count per revolution.

## Do not connect

- Do not feed SFX/adapter +12 V into ESP `VIN`, `5V` or `3V3` in this design.
- Do not connect the adapter's original PWM output to the ESP PWM GPIO.
- Do not connect the adapter's original TACH input to ESP TACH.
- Do not assume blower wire colors indicate function.
- Do not assume TO-92 transistor lead order; identify base/collector/emitter from the exact part/datasheet or a component tester.

## Suggested resistor ranges

| Function | Reference | Practical range |
|---|---:|---:|
| GPIO5 -> Q1 base | 2.2 kOhm | about 1-4.7 kOhm |
| Q1 base pulldown | 100 kOhm | about 47-220 kOhm |
| TACH pull-up to 3.3 V | 10 kOhm | about 4.7-22 kOhm |
| TACH series to GPIO4 | 2.2 kOhm | about 1-4.7 kOhm |
| optional Q2 base resistor | 47 kOhm | about 33-68 kOhm |
| optional Q2 base pulldown | 100 kOhm | about 47-220 kOhm |

## Diagram

- [wiring-simple.svg](wiring-simple.svg)
- [wiring-simple.png](wiring-simple.png)
