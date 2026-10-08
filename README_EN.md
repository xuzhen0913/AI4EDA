# Fixed-topology sizing agent (SKY130 two-stage op-amp example)

[中文 README](README.md)

For an already chosen topology, an LLM iteratively edits `.param` sizes and real ngspice verifies them: DC operating-point repair first, then performance optimization (gain, UGB, phase margin, power), then bilingual PDF reports.

## One-line run: choose the model

Select the model with `SIZING_MODEL` (or `--model`). It is **required**; the program refuses to start without it.

| Name | Backend | Model ID | Note |
|---|---|---|---|
| `qwen` | local GPU | Qwen3-8B | picks an idle GPU, starts and stops the service |
| `fable` | Claude Code | claude-fable-5-1 | |
| `sonnet` | Claude Code | claude-sonnet-5-5 | |
| `opus` | Claude Code | claude-opus-5-5 | |
| `astra` | Codex | gpt-6-astra | |
| `sol` | Codex | gpt-6-sol | |
| `luna` | Codex | gpt-6-luna | |

```bash
cd /home/xu/Multi-agent

SIZING_MODEL=sonnet bash scripts/run_all.sh      # environment variable
bash scripts/run_all.sh --model sol              # equivalent flag

# legacy form: backend only, uses its default (claude->sonnet, codex->astra, qwen->qwen)
SIZING_BACKEND=codex bash scripts/run_all.sh

bash scripts/run_all.sh --baseline-only          # no model; baseline netlist + reports
```

- Full IDs also work: `SIZING_MODEL=gpt-6-sol`, `SIZING_MODEL=claude-opus-5-5`.
- A model that conflicts with `SIZING_BACKEND` (e.g. `SIZING_MODEL=sol SIZING_BACKEND=claude`) is an error.
- Claude models run through the Claude Code CLI with the account already logged in there. Codex models run through `codex exec` with the account logged in by the VS Code ChatGPT/Codex extension (`~/.codex/auth.json`); your `config.toml` is ignored and no session is saved. Cloud models need no GPU.
- Override CLI locations with `CLAUDE_BIN=/path/to/claude` and `CODEX_BIN=/path/to/codex` (otherwise PATH and the VS Code extension folders are searched).
- If an account is out of credits the run stops with the CLI's message (e.g. `claude CLI error (claude-fable-5-1): You're out of usage credits`); rerun with another model name.
- `summary.json` (`design_backend`, `model`) and the PDF record which model was used.
- With a Qwen service already started by `scripts/start.sh`, use `SIZING_MODEL=qwen bash scripts/run_demo.sh` to reuse it; `stop.sh` shuts it down.

## What the model sees each iteration

All models use the same entry point and identical input:

1. `ANALOG_DESIGN_RULES.md`: general formulas, criteria and diagnostic self-checks (re-read every call; hash stored in `calls.json`).
2. `reference.spice`: connectivity, hard constraints and circuit-specific notes (DC balance relation, compensation resistor, ngspice-calibrated data).
3. `target.json`: specs, parameter bounds, DC acceptance criteria.
4. Current measurements (DC operating point, performance, exact failed checks) and this run's iteration history (without earlier model prose).
5. `derived_calculations`: numbers precomputed by Python (gm/Id and gm/gds per device, stage-mismatch ratio Rm and target W/L, compensation resistance and zero side, p2/UGB/A1/A2 estimates, power headroom) from `analog_agents/analog_calc.py`. Estimates; simulator results take precedence.

The model returns JSON only: `analysis` plus at most 3 `changes`. `apply_changes` validates them (bounds, integers, matching, unchanged topology text, old_value); rejected proposals are recorded and fed back but still use an iteration.

## Flow and stopping

1. Baseline DC check (Python criteria in `target.json -> dc_acceptance`).
2. DC failing: DC repair, at most `max_dc_iterations` (5), else `dc_iteration_limit`.
3. DC passing: AC analysis and performance optimization, at most `max_iterations` (10) in total.
4. All targets met: `targets_passed`; otherwise `max_iterations_reached`.

## Outputs

In `circuits/two_stage_opamp/results/`: `summary.json`, `history.json` (parameters, measurements, proposals, accepted/rejected per iteration), `calls.json` (tokens, rules hash, raw responses), `measurements.json`, `candidate.spice`, `logs/simulation_NNN.{spice,log,json}`, `final_report.pdf` and `final_report_zh.pdf`. Earlier runs are archived under `results/runs/`.

## Files

| Path | Role |
|---|---|
| `scripts/run_all.sh` / `run_all.py` | one-line entry; resolves the model; manages the GPU service for Qwen |
| `analog_agents/models.py` | model registry (alias -> backend + model ID) |
| `analog_agents/client.py` | `LocalClient` (Qwen), `ClaudeCliClient`, `CodexCliClient` |
| `analog_agents/rules.py`, `context.py` | inject global rules; compress input |
| `analog_agents/analog_calc.py` | formula library and `derive()` |
| `agents/sizing_agent/` | prompt, proposal validation and application |
| `simulator/` | ngspice runner/parser, PDF reports |
| `circuits/two_stage_opamp/` | reference netlist, `specs/target.json`, results |
| `ANALOG_DESIGN_RULES.md` | topology-independent analog formulas and diagnostics |
| `main.py` | optimization loop |

## Adding or changing models

Add one line to `MODELS` in `analog_agents/models.py`: `'alias': ('claude'|'codex', 'model-id')`. Available Codex model names are listed in `~/.codex/models_cache.json`.

## Editing rules or circuit notes

- Circuit-independent formulas, criteria and advice: `ANALOG_DESIGN_RULES.md`.
- Anything specific to this op-amp: the `TOPOLOGY-SPECIFIC NOTES` comment block at the top of `reference.spice`.
- A new circuit also needs the structured constraints in `target.json` (bounds, `device_dimensions`, `dc_acceptance`, device roles under `topology`); comments alone are not enforced by Python.

## Tests

```bash
/home/xu/.venv/bin/python -m pytest -q     # 55 tests, no model calls, no GPU
```
