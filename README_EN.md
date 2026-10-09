# Three-Agent Op-Amp Design Flow (SKY130): Topology Selection -> Sizing -> Performance Review

[中文 README](README.md)

Given specifications (`circuits/opamp/specs/target.json`) and a library of reference circuits
(`circuits/opamp/reference/`, six op-amp structures), three independent, circuit-agnostic agents
cooperate in a closed loop with real ngspice simulation and finally produce English and Chinese PDF reports.

## The three agents and the flow

| Agent | Directory | Job | Inputs (each item appears once) |
|---|---|---|---|
| Topology selection | `agents/topology_agent/` | Pick one structure for the specs | Targets, testbench description, each reference's **profile** (pros/cons text); on a retry also earlier rounds and the reviewer's advice |
| Sizing | `agents/sizing_agent/` | Edit only the tunable `.param` values of the selected circuit: DC first, then performance | Targets and budgets, the current netlist (with the circuit's own notes), the latest measurement (one merged device table, node voltages), pre-computed numbers, this run's history, the global formula handbook; on a retry also the reviewer's advice |
| Performance review | `agents/review_agent/` | Decide pass/fail; on failure decide whether the TOPOLOGY or the SIZING is at fault and write revision advice | Python's per-metric comparison, the selected profile, final device table / node voltages / parameters (bound usage flagged), every sizing step with its result, the parts of the log that the structured data cannot express |

There are **exactly three agents**; there is no per-reference sizing agent. The prompts, code and formula handbook
contain **no circuit-specific information** (no device names, parameter names or topology names). The only place that
holds topology information is `circuits/opamp/reference/*.spice` (`tests/test_references.py` enforces this with a regex scan).

```
specs + profiles of all references
        |
        v
 +----------------+   selected reference
 | topology agent | ---------------+
 +----------------+                v
        ^                  +----------------+  DC <= 5 decisions, total <= 10 (per sizing run)
        | fail_topology    |  sizing agent  |  DC repair first, then performance, all checked by real ngspice
        | + advice         +----------------+
        |                          | final netlist + log + history + measurements
        |                          v
        |                  +----------------+
        +----------------- |  review agent  | -- pass --> done, write PDFs
              fail_sizing  +----------------+
              + advice --> back to the sizing agent (topology is kept)
```

- **At most 3 rounds** overall (`target.json -> budgets.max_rounds`, must be 1..3). One round = (if needed) select a topology -> one complete sizing run -> review.
- **Each sizing run** keeps the original budgets: DC repair at most 5 decisions in total (`max_dc_iterations`); after DC passes, performance
  optimisation up to 10 decisions in total for that run (`max_iterations`). The two budgets are independent: 3 rounds, each sizing run may use all 10
  decisions, so the whole flow may contain more than 3 sizing decisions (up to 30).
- Round 1 always selects a topology. Afterwards: `fail_topology` -> the topology agent chooses again (rejected topologies are no longer offered) and sizing starts from the new
  reference's initial values; `fail_sizing` -> same topology, sizing resumes with the reviewer's advice (by default from the previous final netlist; the reviewer may set
  `restart_sizing_from_reference` when that netlist is worse than the start).
- The numbers are authoritative: if the reviewer says `pass` while a metric fails Python's comparison, the verdict is changed to `fail_sizing` and recorded in `review.json`;
  a `fail_*` verdict must come with non-empty advice.
- If round 3 still fails, the status is `max_rounds_reached` and the report records every round as it happened.

## One command: choose the model

Select a model with `SIZING_MODEL` (or `--model`); it is **required**. All three agents use the same model, each with its own client so calls and tokens are recorded separately.

| Model | Backend | Model ID | Note |
|---|---|---|---|
| `qwen` | local GPU | Qwen3-8B | idle GPU chosen, service started and stopped automatically; only 32k context |
| `fable` | Claude Code | claude-fable-5-1 | |
| `sonnet` | Claude Code | claude-sonnet-5-5 | |
| `opus` | Claude Code | claude-opus-5-5 | |
| `astra` | Codex | gpt-6-astra | |
| `sol` | Codex | gpt-6-sol | |
| `luna` | Codex | gpt-6-luna | |

```bash
cd /home/xu/Multi-agent

SIZING_MODEL=sonnet bash scripts/run_all.sh        # full three-agent flow
bash scripts/run_all.sh --model sol                # equivalent

# No model: simulate one untouched reference and write the reports (checks that a reference is understood by the toolchain)
bash scripts/run_all.sh --baseline-only --reference two_stage_nmos_input_pmos_stage2
```

- Full IDs work too (`SIZING_MODEL=gpt-6-sol`, `claude-opus-5-5`); legacy `SIZING_BACKEND=qwen|claude|codex` still selects that backend's default model.
- Claude models use the Claude Code CLI (logged-in account); Codex models use `codex exec` (`~/.codex/auth.json`), without reading `config.toml` or saving sessions. Use `CLAUDE_BIN` / `CODEX_BIN` if the CLI is not found.
- If an account runs out of credits the run fails with that error; rerun with another model.
- A Qwen service already started with `scripts/start.sh` can be reused via `SIZING_MODEL=qwen bash scripts/run_demo.sh`; stop it with `stop.sh`.

## The reference library (the only home of topology information)

Every file in `circuits/opamp/reference/` is one candidate structure. The file name is the id, `<structure>_<input polarity>[_<second stage>]`:

| File (id) | Structure |
|---|---|
| `two_stage_nmos_input_pmos_stage2` | Two-stage Miller, NMOS input, PMOS common-source second stage (**verified** to reach the specs) |
| `two_stage_pmos_input_nmos_stage2` | Two-stage Miller, PMOS input, NMOS common-source second stage (not verified) |
| `folded_cascode_nmos_input` | Folded cascode, NMOS input (not verified) |
| `folded_cascode_pmos_input` | Folded cascode, PMOS input (not verified) |
| `telescopic_cascode_nmos_input` | Telescopic cascode, NMOS input (not verified) |
| `telescopic_cascode_pmos_input` | Telescopic cascode, PMOS input (not verified) |

A reference holds **only the circuit under test**, top to bottom:

1. **`@profile-begin ... @profile-end`**: structure, advantages, disadvantages, best/avoid conditions, verification status (including observed baseline simulation).
   The topology agent decides from this text only; the review agent reads it too.
2. **`@analyses-begin ... @analyses-end`** (optional): a JSON list declaring which pre-computed estimates suit this structure (current-balance ratio, compensation zero/poles, cascode-stack output resistance and gain); device names appear only here.
3. **NOTES comments**: this circuit's DC-balance relations, bias relations and calibration data (read by the sizing agent).
4. **`.param` lines and the circuit.** Tunable parameters are the `.param` lines annotated `; tune MIN..MAX [UNIT] [int]` (e.g. `.param W_IN=10 ; tune 1..100 um`; `int` = integer-valued); all other `.param` are fixed constants.
   Device terminals, models, W/L expressions and the diagnostic names needed by the DC check are **parsed from the netlist**, never declared a second time.

**What is not in a reference** (duplicated input removed): supply, input sources, load capacitor, `.lib`/`.temp`, DC diagnostic `print`s, AC analysis and measurements are all generated by the shared
testbench (`simulator/testbench.py`) from `target.json` and the circuit's own devices and nodes, so every topology is measured in exactly the same way and a changed condition is edited in one place only.
A reference must therefore use the port nodes `vdd`, `vinp`, `vinn`, `out`, and must not contain `.lib/.temp/.control/.end`, `VSUPPLY/VINP/VINN/CLOAD_OUT` or the parameters `VDD/VCM/CLOAD` (checked at load; a violation stops the flow).
Load-time checks also require: one `.param` per line; initial values inside the tune range; integer parameters with integer initial values; every tunable used by the circuit; every device named in `@analyses` exists.
The effective W/L limits (including products such as `N_TAIL*WBN0`) are process rules and live in `target.json -> device_limits`, applied to every MOS.

**Adding a topology**: copy a reference, edit the circuit, profile, annotations and notes, and name the file by the rule above; nothing else changes and `pytest` checks it.
`target.json` holds specifications only: process/conditions, targets, device-size limits, DC thresholds, AC sweep, budgets.

## What each agent sees per call

Only the sizing agent receives `ANALOG_DESIGN_RULES.md` (circuit-independent formulas, criteria and a generic diagnostic checklist; its hash is stored in the call record). Every fact appears once:

- **Device table**: one row per MOS, merging the operating point (polarity-normalised |Vgs|, |Vds|, |Vth|, |Vdsat|), overdrive/saturation margin, gm, gm/Id, gm/gds, W/L and the failed DC criteria; there is no longer a raw-diagnostics + DC-acceptance + derived triple.
- **Parameters**: value, range and integer flag are on the annotated `.param` line; there is no separate parameter / current-value / bounds table.
- **Log**: numeric lines, banners and errors/warnings already in structured fields are not repeated; only the remaining lines are given (usually none).
- **History**: each decision's changes and measured result; no model prose from earlier iterations; the last result is the current measurement and is not repeated.
- **Testbench**: one generated paragraph (conditions and metric definitions), from the same source as the simulated deck.
- The topology and review agents do not receive the formula handbook.

Outputs: the topology agent returns the selected id, a suitability and reason per candidate, and expected risks;
the sizing agent returns only `analysis` and at most 3 `changes` (proposals pass `apply_changes`: tunable parameter, range, integer, effective W/L range, rest of the netlist unchanged, old_value agreement; a rejected proposal is recorded, fed back and still consumes an iteration);
the review agent returns `verdict`, `diagnosis`, advice for whichever agent is at fault, and whether to restart from the reference.

## Output

`circuits/opamp/results/` (the previous run is **moved** into `results/runs/<timestamp>/` before each run):

```
summary.json              workflow status, rounds, per-agent calls and tokens, simulations, time, model, per-round summary, final netlist path
specs.json                the specifications used in this run
round_01/ round_02/ ...   one directory per round
    topology_selection.json  this round's topology choice (ranking, reasons, risks); absent when the topology was kept
    topology_calls.json      topology agent call records
    candidate.spice          this round's circuit (edited in place while sizing; the final netlist when the round ends)
    history.json             every decision: analysis, changes, accepted?, measured result (first row also holds the starting point `before`)
    sizing_calls.json        sizing agent call records (tokens, rules hash, raw replies)
    summary.json             this round's sizing summary (including the reference's initial values)
    review.json / review_calls.json   verdict, diagnosis, revision advice
    logs/simulation_NNN.{spice,log,json}   the complete deck, log and parsed record of every simulation
final_report.pdf          English report
final_report_zh.pdf       Chinese report
```

The PDFs contain: outcome versus specs, a per-round table, the topology-selection reasoning and ranking, the final circuit's profile and a connectivity table parsed from the netlist, DC acceptance,
parameter range/initial/final values, every sizing iteration of every round, review verdicts and advice, token/simulation/time statistics, full DC diagnostics and the final netlist. Model-written text is kept in its original English.
(The report is topology-agnostic and uses the netlist-derived connectivity table instead of the hand-drawn schematic of the earlier single-circuit version.)

## Files

| Path | Role |
|---|---|
| `main.py` | Three-agent orchestration: rounds, retry routing, result files, reports |
| `agents/topology_agent/` | Topology agent (prompt, candidate enumeration, choice validation) |
| `agents/sizing_agent/` | Sizing agent (prompt, proposal validation/application, input construction; `loop.py` is one sizing run) |
| `agents/review_agent/` | Review agent (prompt, metric comparison, input construction, verdict consistency) |
| `analog_agents/reference.py` | Library loader and checks; builds the sizing target from the netlist |
| `analog_agents/spice.py` | SPICE-text tools: scalars, `.param`, MOS instances, nodes, restricted expressions |
| `analog_agents/evidence.py` | Measurement views for the agents (device table, node voltages, log de-duplication) |
| `analog_agents/analog_calc.py` | Formula library and `derive()` (pre-computed numbers, enabled by a reference's `@analyses`) |
| `analog_agents/models.py`, `factory.py`, `client.py`, `rules.py`, `schema.py`, `config.py` | Model registry; one client per agent; Qwen/Claude/Codex adapters; handbook injection; JSON-schema helpers; local-service config |
| `simulator/testbench.py` | The shared testbench: complete simulation deck and its description |
| `simulator/ngspice_runner.py` | ngspice runner/parser and the DC check |
| `simulator/report_generator.py` | English/Chinese PDF reports (topology-agnostic) |
| `circuits/opamp/` | `reference/` (topology library), `specs/target.json` (specs), `results/` (run output, gitignored) |
| `ANALOG_DESIGN_RULES.md` | Generic analog formulas and diagnostics (topology-independent) |
| `tools_path.md` | ngspice and SKY130 library paths |
| `scripts/` | One-command `run_all.sh`, `run_demo.sh` (reuse a running Qwen service), local Qwen service install/start/stop |

## Changing rules or circuit notes

- Circuit-independent formulas, criteria, generic advice -> `ANALOG_DESIGN_RULES.md`.
- A topology's pros/cons and suitability -> its `@profile` block; topology-specific numbers, directions, calibration -> its NOTES; tunable parameters and ranges -> its `.param` annotations; pre-computed analyses -> its `@analyses`.
- Operating conditions, targets, budgets, device-size limits, AC sweep -> `target.json`; measurement definitions -> `simulator/testbench.py`.

## Tests

```bash
/home/xu/.venv/bin/python -m pytest -q     # no model calls, no GPU
```

They cover: self-consistency and naming of every reference, a regex check that circuit-specific information appears only in references, a check that exactly three agents exist,
testbench generation (one measurement for all references, conditions only from the specs), evidence-view de-duplication,
and the whole routing with scripted agents and a scripted simulator (first-round pass, sizing retry, topology retry with exclusion of the failed topology, the 3-round cap, budget validation,
verdict overridden by the numbers, restart vs. continue, archiving of the previous run).

## Known limitations

- Apart from `two_stage_nmos_input_pmos_stage2`, the other five references have illustrative initial sizes/biases and none passes the DC check at baseline (stated in their profiles).
  Folded/telescopic references use ideal bias voltage sources with many coupled parameters; whether 5 DC decisions suffice depends on the model, and that is what the review agent's
  `fail_topology` / `fail_sizing` verdict is for.
- A reference is no longer a complete deck that can be given to ngspice as-is (the testbench is generated). To see the complete deck of an actual simulation, open `round_NN/logs/simulation_NNN.spice`.
