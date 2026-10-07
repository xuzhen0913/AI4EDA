# Generic fixed-topology sizing agent (with SKY130 amplifier example)

**One command: select an idle GPU → start local Qwen → DC-gated sizing → performance simulation → generate English/Chinese PDFs → stop the service started by this invocation.**

```bash
SIZING_BACKEND=qwen bash /home/xu/Multi-agent/scripts/run_all.sh   # or SIZING_BACKEND=claude
```

## Choosing the model backend (required)

`SIZING_BACKEND` must be set on the command line; without it the run refuses to start (`--baseline-only` needs no model).

```bash
# Local Qwen (needs an idle GPU; starts and stops the service automatically)
SIZING_BACKEND=qwen bash /home/xu/Multi-agent/scripts/run_all.sh

# Claude Sonnet via the Claude Code CLI (no GPU needed; use when GPUs are busy)
SIZING_BACKEND=claude bash /home/xu/Multi-agent/scripts/run_all.sh
```

[中文 README](README.md)

**33 automated tests passed; the updated agent was exercised with Astra and real ngspice.** See the current validation result below.

## Generic sizing agent and circuit adapters

The sizing agent receives an already selected topology. The intended architecture is:
top-level topology → module-spec allocation agent → topology-selection agent → sizing agent.
Only the last layer is generalized here; the upstream agents are not implemented yet.

- `agents/sizing_agent/prompt.md` contains topology-independent rules: read and obey the reference constraints without assuming an amplifier, process, device count, polarity or metric formula.
- `agents/sizing_agent/agent.py` proposes and validates scalar changes. All netlist text except permitted parameter values remains immutable. Bounds, integer ratios, optional matching and effective dimensions are input data.
- `reference.spice` describes connections, shared expressions, fixed conditions, bounds, operating regions and measurements. Its new `SIZING CONTRACT` documents the example circuit completely.
- `target.json` contains requested performance and machine-readable constraints. `condition_parameters` explicitly binds conditions to parameters; optional MOS policies declare `model` and `diagnostic_prefix`, instead of assembling SKY130 names inside the agent.

Natural-language reference comments are read by the model, not compiled automatically into Python validators. A new circuit must supply matching structured constraints; changing comments alone is insufficient. Python still enforces immutable topology and shared expressions.

The upstream caller can use `SizingAgent.run(target, reference, candidate, full_log, measurements, history)` and validate its `analysis` / up-to-three `changes` response through `apply_changes` before simulation. Adjustable inputs currently use one scalar `.param NAME=value` per line; fixed expressions may reference those scalars. Signed or zero values are permitted when declared bounds allow them.

**A generic sizing agent is not an automatic simulator/report adapter for every circuit.** The current CLI still selects `circuits/two_stage_opamp`; the ngspice adapter retains the SKY130 tool configuration, DC→AC protocol and MOS saturation policy, and report drawing supports the existing amplifier topologies. Other circuit families need appropriate operating-point checks, measurements, simulation scripts and report drawings. Do not reuse amplifier saturation or PM assumptions for comparators, oscillators or passive networks. Those circuit-specific rules do not belong in the generic sizing agent.

The standard one-command launcher still uses Qwen and exits when no GPU is idle; it does not evict other jobs or automatically connect to Astra. This test uses an Astra replacement supplied by the Codex session, with separate outputs and unchanged long-term Qwen configuration.

## Actual topology

Active reference: `circuits/two_stage_opamp/reference/reference.spice`.

- M1/M2: NMOS differential pair.
- M3/M4: identical PMOS mirror load, fixed 1:1.
- M5: NMOS tail current source.
- **M7: PMOS common-source gain device**, gate=N2, source/body=VDD, drain=OUT.
- **M6: NMOS bias current sink**, gate=VBIAS_N, source/body=ground, drain=OUT.
- MBIAS_N: diode-connected NMOS reference biasing both M5 and M6.

There are **eight MOS devices**. MBIAS_P, IBIAS_P and VBIAS_P have been removed.
W_STAGE2/L_STAGE2 now size M7, not M6. N_STAGE2_BIAS controls M6's width relative to the NMOS bias reference.

## Structural matching and parameters

| Device | W expression | L expression |
|---|---|---|
| M1/M2 | W_IN | L_IN |
| M3/M4 | W_LOAD | L_LOAD |
| MBIAS_N | WBN0 | L_BIAS_N |
| M5 | N_TAIL*WBN0 | L_BIAS_N |
| M6 | N_STAGE2_BIAS*WBN0 | L_BIAS_N |
| M7 | W_STAGE2 | L_STAGE2 |

N_TAIL and N_STAGE2_BIAS are independent positive integers, initially both 1.
W/L are in micrometers. Base parameters and effective product dimensions are bounded:
all effective MOS widths are capped at 100 um; valid bounds do not guarantee a PDK model bin for every W/L combination.
Netlist expressions enforce sharing. Python rejects fractional ratios, out-of-range sizes,
stale old_value fields and changes to device connectivity. Removed parameters
N_STAGE2_LOAD, WBP0 and L_BIAS_P are no longer allowed. M3/M4 have no tunable ratio.

Rejected proposals preserve the candidate and feed an error into the next decision,
but still consume budget. A new run starts from the new reference, not an old-topology
working/candidate.spice left over from a previous experiment.

## DC polarity and acceptance

Start with DC OP only. Python checks all eight devices, including MBIAS_N; a model's
subjective claim of valid bias cannot override the gate. Current acceptance conditions:

- |Id| >= 1 nA;
- NMOS: VGS=Vg-Vs, VDS=Vd-Vs; PMOS: VSG=Vs-Vg, VSD=Vs-Vd;
- forward orientation: VDS/VSD > 0;
- VGS/VSG - |Vth| >= 0;
- VDS/VSD - |model VDSAT| >= 0.

These configurable thresholds are in target.json/dc_acceptance and constitute the project's
strong-inversion saturation policy. Missing/nonfinite diagnostics or DC simulation errors
cannot pass. Device terminals and NFET/PFET models are cross-checked against the netlist
before running, preventing stale topology mappings.

For the new second stage:

| Device | Conduction / overdrive | Saturation headroom |
|---|---|---|
| M6, NMOS sink | V(vbias_n)-|Vth6| >= 0 | V(out)-|VDSAT6| >= 0 |
| M7, PMOS gain | VDD-V(n2)-|Vth7| >= 0 | VDD-V(out)-|VDSAT7| >= 0 |

An output too close to ground can desaturate M6; an output too close to VDD can desaturate
M7. Increasing N2 reduces M7's VSG and weakens its conduction, unlike an NMOS gain device.
Changing WBN0 or L_BIAS_N affects the shared NMOS reference and both mirror branches.

## Performance formulas and phase convention

The current differential AC excitation is VINP=+0.5 and VINN=-0.5, giving 1 V differential.
The testbench explicitly computes:

```text
Vin_diff = V(vinp) - V(vinn)
A_diff   = V(out) / Vin_diff
Gain_dB  = 20*log10(|A_diff|)
L        = -A_diff
PM       = 180 degrees + continuous_phase(L)*180/pi at UGB
Power    = -I(VSUPPLY)*V(vdd)
```

- dc_gain_db is the **1 Hz low-frequency approximation**, not a separate DC-sweep gain.
- UGB is the first falling 0 dB crossing, in the existing 1 Hz–1 GHz AC sweep.
- A PMOS common-source stage still inverts. With this first-stage wiring, A_diff is still
  negative at low frequency, so L=-A_diff is retained rather than blindly flipping the sign.
- The run checks real(L)>0 at 1 Hz. Missing/wrong polarity, missing measurements or AC
  errors cannot count as a passing design. AC failures do not invalidate a separately
  valid DC operating point; the performance diagnostics remain available to Qwen.
- PM is an **open-loop small-signal estimate for unity negative feedback applied to VINP**.
  VINP/VINN labels do not themselves establish conventional noninverting/inverting inputs.
  This is not an arbitrary feedback-network return-ratio measurement, and a first-crossing
  result alone is not a proof of stability in a multiple-crossing response.
- ngspice cph returns radians, explicitly converted to degrees. Power still uses the actual
  supply current, so removing the PMOS bias branch is accounted for naturally, without an
  obsolete branch-count estimate.

Function definitions: [official ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf).
The new-topology polarity reasoning and implementation have not been verified by simulation.

## Workflow and decision limits

1. Validate reference, targets, matching expressions and DC terminal mapping.
2. Run DC only. Failed devices trigger Qwen bias/headroom repair using the full log.
3. A passing candidate may run full OP+AC/power measurements of that exact netlist.
4. Every decision is followed by fresh DC checking. A later DC failure returns to repair.
5. Stop when all DC/performance requirements pass, or when a decision budget is exhausted.

**At most 5 cumulative DC-repair decisions within at most 10 total decisions.** Re-entering
DC repair does not reset its allowance. A failing fifth repair stops; a passing fifth repair
may use remaining total decisions for performance. Baseline does not count as a decision.
No-change and rejected decisions still count. Each DC-only or full OP+AC ngspice invocation
counts separately. Unmeasured AC values are null/unavailable, never zero or stale prior results.

## Automatic GPU/service lifecycle

The configured GPU (currently 3) is preferred; if busy, another idle GPU is selected.
Idle means <=1024 MiB used and <=5% utilization. No idle GPU means refusal, never eviction
of existing processes. This check is not a cluster reservation.

The script attempts to stop only its own service on normal exit, error or Ctrl+C. A preexisting
managed service causes refusal; use `bash scripts/stop.sh` first or reuse it with
`bash scripts/run_demo.sh`. SIGKILL cannot guarantee cleanup.

## File map and outputs

| Purpose | File |
|---|---|
| One-command entry point | scripts/run_all.sh |
| GPU/service lifecycle | scripts/run_all.py; scripts/service.py |
| DC/performance transitions | main.py |
| Reference circuit | circuits/two_stage_opamp/reference/reference.spice |
| Targets, dimensions, DC mapping, AC conventions | circuits/two_stage_opamp/specs/target.json |
| Model rules and constraint validation | agents/sizing_agent/prompt.md; agent.py |
| Real simulator and result parser | simulator/ngspice_runner.py |
| Bilingual PDFs and connected circuit diagram | simulator/report_generator.py |
| Local model service configuration | config/settings.json |

Outputs: circuits/two_stage_opamp/results/final_report.pdf and final_report_zh.pdf.
The results directory also holds snapshots, history, tokens, timing and full logs.
Existing evidence belongs to the old circuit; subsequent runs archive earlier reports into
results/runs and preserve numbered logs. The schematic renderer distinguishes the new
PMOS stage from historical NMOS-stage netlists rather than relabeling old evidence.

Endpoint: http://127.0.0.1:8003/v1; served model: qwen3-8b-local.
Weights: models/Qwen3-8B; shared Python: /home/xu/.venv; EDA paths: tools_path.md.
Each model call includes full latest logs, reference/candidate, targets, metrics and history.
Context overflow causes an explicit stop, not silent truncation.

## Optional later checks (not executed for this revision)

CPU-only baseline plus both reports, still subject to the DC gate:

```bash
bash /home/xu/Multi-agent/scripts/run_all.sh --baseline-only
```

Regression tests:

```bash
cd /home/xu/Multi-agent
source scripts/env.sh
"$PROJECT_PYTHON" -m pytest -q -p no:cacheprovider
```

Tests were adapted but not executed. Static checking does not establish convergence or performance.

## Validation run (2026-10-07)

All 33 tests passed, including passive-network sizing and a non-SKY130 model. All four GPUs were busy, so Astra read the generic prompt and current reference and supplied decisions to real ngspice simulations. All targets passed after 3 iterations (1 DC repair, 2 performance decisions), 7 simulation calls and 154.37 seconds: gain 69.7099 dB, UGB 11.6066 MHz, PM 72.0794 degrees, power 234.639 uW. All eight MOS devices passed DC. Success 1/1 describes only this run, not arbitrary circuit families.

Final candidate: W_STAGE2=100, N_STAGE2_BIAS=4, CC=2.5p. Reference initial values are retained. Astra token usage is unavailable and recorded as unknown.

[English report](circuits/two_stage_opamp/results/astra_20261007_113433/final_report.pdf) · [Chinese report](circuits/two_stage_opamp/results/astra_20261007_113433/final_report_zh.pdf) · [Run summary](circuits/two_stage_opamp/results/astra_20261007_113433/summary.json)
