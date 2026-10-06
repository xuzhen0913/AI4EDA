# SKY130 two-stage op-amp: DC-first sizing

**One command: select an idle GPU → start local Qwen → optimize → generate English and Chinese PDFs → release the service started by this command.**

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh
```

[中文 README](README.md)

## Startup and outputs

Uses the existing Qwen3-8B/vLLM installation and SKY130/ngspice tools. No reinstallation
or modifications to `/home/xu/eda` are performed. The configured GPU (currently 3) is
preferred. If busy, another idle GPU is selected. Idle means memory usage <=1024 MiB
and utilization <=5%; no idle GPU causes a clean refusal, never process eviction.
This check is not a cluster reservation; follow your site's scheduler policy.

Only the service started by this invocation is cleaned up on completion, Python error,
or Ctrl+C. SIGKILL cannot run cleanup. An already managed service causes refusal;
use `bash scripts/run_demo.sh` to reuse it or `bash scripts/stop.sh` before the one-command run.

Reports:

- `circuits/two_stage_opamp/results/final_report.pdf`
- `circuits/two_stage_opamp/results/final_report_zh.pdf`

Reports are also produced at iteration limits. Workflow completion does not imply circuit
success. AC metrics are marked unavailable if DC failed; previous AC results are not reused.

## Structural matching

Reference: `circuits/two_stage_opamp/reference/reference.spice`.

| Device | W expression | L expression |
|---|---|---|
| M1 and M2 | W_IN | L_IN |
| M3 (diode reference) | W_LOAD | L_LOAD |
| M4 | N_LOAD*W_LOAD | L_LOAD |
| MBIAS_N (diode reference) | WBN0 | L_BIAS_N |
| M5 | N_TAIL*WBN0 | L_BIAS_N |
| MBIAS_P (diode reference) | WBP0 | L_BIAS_P |
| M7 | N_STAGE2_LOAD*WBP0 | L_BIAS_P |
| M6 | W_STAGE2 | L_STAGE2 |

All N parameters must be positive integers; initial values are 1, 1 and 2. Unity is valid.
Netlist expressions enforce sharing, while Python enforces integer values and bounds.
Invalid proposals, including stale old_value fields, are recorded and rejected; dimensions
remain unchanged and the rejection is supplied to the next decision. They still consume budget.
Effective product widths are checked too: current maxima are 100 um for M4/M5 and 200 um
for M7. See target.json for all limits. Qwen cannot modify individual device dimensions.

M7's initial length changed from 0.5 um to the shared PMOS bias length of 1.0 um. Historical
results are not the new baseline. `reference.original.spice` preserves the original input;
it is not the active reference.

## DC gate and budgets

1. Validate reference parameters, fixed conditions and matching expressions.
2. Execute DC OP only; remove the marked AC block from the execution copy.
3. Check all nine MOS devices, including both bias references:
   - forward drain orientation;
   - |Id| >= 1 nA;
   - VGS (NMOS) or VSG (PMOS) minus |Vth| >= 0;
   - VDS (NMOS) or VSD (PMOS) minus model |VDSAT| >= 0.
4. Failed or missing DC data blocks AC. Qwen reasons about bias/headroom and repairs sizing.
5. Only a passing DC candidate may run full OP+AC measurements: gain, UGB, phase margin, power.
6. Every decision is followed by a fresh DC check; later DC failures return to repair immediately.
7. Stop on all performance targets passing, or on a decision budget being exhausted.

**At most 5 cumulative DC-repair decisions, within at most 10 total decisions.** Re-entering
DC repair does not reset its budget. If the fifth repair passes DC, remaining total decisions
may optimize performance. If it fails, stop. Baseline is not a decision; a no-change model
response still counts. Each DC-only or full OP+AC ngspice invocation counts separately.

The configurable `dc_acceptance` policy requires strong-inversion saturation. It uses model
VDSAT rather than substituting the long-channel approximation VGS-Vth. See the
[official ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf).
Passing this gate does not validate every analog design requirement.

## Configuration and implementation

| Purpose | File |
|---|---|
| Targets, ranges, integer ratios, DC thresholds, budgets | circuits/two_stage_opamp/specs/target.json |
| Fixed topology, shared dimensions, measurement commands | circuits/two_stage_opamp/reference/reference.spice |
| Model design instructions | agents/sizing_agent/prompt.md |
| Parameter and structural validation | agents/sizing_agent/agent.py |
| DC policy and real ngspice runner | simulator/ngspice_runner.py |
| Stage transitions and counts | main.py |
| Model, port, preferred GPU, context | config/settings.json |
| GPU selection and owned-service lifecycle | scripts/service.py; scripts/run_all.py |
| Bilingual PDF and connected schematic | simulator/report_generator.py |

The existing endpoint is `http://127.0.0.1:8003/v1`, served model `qwen3-8b-local`.
Each request supplies target, reference, candidate, FULL latest log, measurements and history.
Context overflow stops explicitly; logs are never silently truncated.

Weights: `models/Qwen3-8B`; caches: `.runtime`; shared Python: `/home/xu/.venv`.
EDA paths are read from `tools_path.md`. `analog_agents` retains the proven client and config;
there is one design agent. Current candidate is in `circuits/two_stage_opamp/working`.
Results contain JSON, PDFs and full numbered logs/execution netlists. Prior run summaries
and reports are archived in `results/runs`; numbered logs are not overwritten.

## CPU-only validation

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh --baseline-only
```

This validates the baseline and both PDFs, honoring the DC gate, without Qwen/GPU inference.

```bash
cd /home/xu/Multi-agent
source scripts/env.sh
"$PROJECT_PYTHON" -m pytest -q -p no:cacheprovider
```

Unit fixtures test validators, transition policies and counters; they are not model or circuit results.
