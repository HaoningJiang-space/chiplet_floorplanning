# Local transistor temperature: admission gate

Before extending paired timing comparisons to nonuniform chiplet temperature,
the simulator must actually apply the assigned temperature to each device.
Changing the ambient temperature of the whole circuit cannot represent
different source and receiver temperatures. Changing nominal model temperature
is also not a substitute for changing operating temperature.

The local ngspice 42 executable was tested on five manufactured BSIM4 level-54
DC decks (version 4.8.1). This isolates parameter support, not SKY130 accuracy.

| Control | Result |
|---|---|
| Global 25 C | Supply current -0.442245058 mA |
| Global 100 C | Supply current -0.365579683 mA |
| Instance TEMP=100 | Rejected; exit 1, unknown parameter |
| Instance DTEMP=75 | Rejected; exit 1, unknown parameter |
| Model T_ABS=100 at global 25 C | Exit 0, warning: ignored parameter; same current as global 25 C |

Exit zero alone would therefore falsely admit one unsupported temperature
method. All three tested local-temperature methods are rejected. The distinct
global controls show that the model does respond to temperature, without
proving local temperature support. Raw decks and failed logs are retained
locally; [compact evidence](evidence/local-bsim-temperature-probe.json)
records executable, source, deck and log hashes.

```powershell
. ./tools/windows_env.ps1
python tools/probe_bsim_temperature.py --output results/bsim-temperature-probe
```

The [ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)
documents exceptions to MOS instance temperature support for BSIM models.
The tested executable is the authority for the narrow finding above. This
does not establish that every simulator or every BSIM implementation lacks
local temperature support.

Next admission sequence for a replacement implementation: verify global-hot
versus local-hot equivalence on one device, verify independent temperatures
on two devices, then rebaseline identical PDK circuits at uniform 25 C before
comparing nonuniform-temperature layouts. Preserve compact-model parameters,
stimuli and boundary definitions. Do not fit away simulator differences or
claim the already completed reference-temperature experiments validate hot
timing. Receiver setup/hold constraints and real Pad/package calibration
remain separate open requirements.
