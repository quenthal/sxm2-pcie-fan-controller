# OCuLink Adapter Power-On Notes

Power control is intentionally separate from the fan controller.

## Why power-on is out of scope

The ESP8266 can be USB-powered while the SFX/GPU side is off. In that condition:

- blower +12 V is absent
- TACH can legitimately be zero
- the GPU may not exist on PCIe

The current project therefore does **not** control ATX `PS_ON#` and does not assume that the ESP should decide when the SFX PSU starts.

## Reference adapter context

The development build used a CY-SF-014+SF-061 style OCuLink/PCIe adapter package. Earlier project notes also compared behavior reported by users of NFHK N-P114-A style adapters.

Community reports indicate that OCuLink sideband wiring can affect automatic eGPU power-on/power-off behavior. Some cables may not carry all sideband pins, so a build that requires a manual adapter switch is not necessarily a fan-controller fault.

This is community/hardware-specific behavior, not part of the fan-control protocol.

## First power test

Before designing any ESP-controlled PSU circuitry:

1. keep the fan controller electrically independent of `PS_ON#`
2. connect the OCuLink adapter and SFX normally
3. set the adapter's power switch according to its documented/known behavior
4. fully shut down the host
5. observe whether the SFX/GPU is also off
6. start the host
7. observe whether the SFX/GPU starts automatically
8. confirm the V100 enumerates in Linux
9. perform a normal host shutdown
10. observe whether the SFX/GPU powers off automatically

Possible outcomes:

```text
A) GPU/SFX follows host automatically
   -> no PSU-control work needed

B) manual adapter switch is required
   -> fan controller still works; power can remain manual
   -> sideband/cable behavior is a likely separate investigation

C) GPU does not enumerate even with the adapter powered
   -> investigate OCuLink/PCIe/PSU rather than fan-control logic
```

## Cable continuity investigation

If auto-power matters and the adapter/cable behavior is unclear, perform only passive continuity/ohm measurements on a fully unpowered, disconnected cable.

Do not inject voltage into unknown OCuLink pins.

## Adapter switch reverse engineering

If manual power remains necessary and you later want automation, first characterize the adapter switch with all power removed:

- which contacts connect in each switch position
- whether any contact is tied to ground
- whether a contact maps to ATX `PS_ON#`

Only after the actual board revision is understood should an open-collector/NPN parallel control stage be designed.

That circuit is intentionally not part of v0.11.0.
