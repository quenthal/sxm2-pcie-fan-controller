# Background References

These are background materials that informed the project or were retained from earlier project notes. The physical reference system and source code in this repository remain the primary basis for the documented final wiring/tuning.

## NVIDIA

- `nvidia-smi` documentation: https://docs.nvidia.com/deploy/nvidia-smi/

GPU thermal limits used in the reference deployment were read directly from the installed V100 with `nvidia-smi -q -d TEMPERATURE`, rather than copied from a different V100 form-factor datasheet.

## ESP8266

- ESP8266 Arduino Core documentation: https://arduino-esp8266.readthedocs.io/

## V100 external-cooling background

- Tymscar V100 local-LLM build: https://blog.tymscar.com/posts/v100localllm/

## 4-wire fan electrical model

The design follows the conventional 4-wire PC-fan model in which PWM is driven by an open-collector/open-drain style pull-down and TACH is an open-collector/open-drain output when the physical blower actually conforms to that behavior.

The project does not assume TACH compliance blindly: `docs/WIRING.md` requires physical voltage measurement before connecting ESP GPIO4.

## OCuLink/eGPU power behavior

Community discussion retained from earlier project notes:

- https://egpu.io/forums/custom-egpu-chassis/oculink-what-it-is-why-you-need-it-and-where-to-get-it/paged/13/

Those reports are treated as community observations, not as a manufacturer electrical specification for the exact reference adapter revision.
