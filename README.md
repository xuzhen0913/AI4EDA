# SKY130 fixed-topology Qwen sizing

The project is `/home/xu/Multi-agent` (Linux paths are case-sensitive).
This version implements the current `prompt.md`: ONE local Qwen sizing agent,
real SKY130/ngspice, constrained `.param` updates and an English PDF.
The previous mock multi-agent workflow has been removed. Obsolete manuals and their build scripts have been removed.

## Run

```bash
cd /home/xu/Multi-agent
bash scripts/start.sh
bash scripts/run_demo.sh
bash scripts/stop.sh
```

`start.sh` uses the existing Qwen3-8B weights and vLLM installation. It does not
install or download anything. GPU 3 is configured; startup refuses a busy GPU
(>1024 MiB used or >5% utilization). It does not kill other users' processes or
select another GPU automatically. Set `gpu` in `config/settings.json` to an idle
GPU before startup. An idle check is not a cluster reservation; use the site's
scheduler on shared machines if available. Stop only this project's managed service.

The existing API is `http://127.0.0.1:8003/v1`, served model `qwen3-8b-local`.
The same proven OpenAI-compatible client is retained in `analog_agents/client.py`.
The context limit is now 32768: the required initial full input is already about
13619 tokens. Input is tokenized before calling Qwen; full logs/history are never
silently truncated. If later history exceeds the limit, the run records an interruption.
`max_tokens=1800`, temperature=0.2, structured JSON and thinking-disabled template
remain explicit local inference settings. All sizing reasoning must come from Qwen.

CPU-only real simulation and report check (no Qwen iteration):

```bash
bash scripts/run_demo.sh --baseline-only
```

## Files and workflow

1. `scripts/run_demo.sh` sources `scripts/env.sh` and starts `main.py` with
   `/home/xu/.venv/bin/python`.
2. `main.py` reads `circuits/two_stage_opamp/specs/target.json` and
   `circuits/two_stage_opamp/reference/reference.spice`. It checks allowed parameters
   and matching, copies the reference into `working/candidate.spice` and snapshots inputs.
3. `simulator/ngspice_runner.py` reads executable/model locations from `tools_path.md`
   and executes real ngspice. Each invocation saves the actual netlist, complete merged
   stdout/stderr, return code, measurements and device/node DC diagnostics in numbered files.
4. `agents/sizing_agent/agent.py` reads its `prompt.md`, and sends target, reference,
   candidate, FULL latest log, measurements and history through the retained local client.
5. Qwen diagnoses simulation validity, then DC bias, then AC/power. Python validates JSON,
   allowed names, old values, numeric bounds and unchanged topology/matching before applying
   at most three parameter changes. Invalid proposals interrupt safely; no random fallback.
6. The updated candidate is simulated, and the loop repeats up to the target's iteration
   budget (currently 5), or stops when measured targets pass and Qwen confirms validity/DC bias.
7. `simulator/report_generator.py` reads recorded evidence and builds an English PDF,
   including actual net-labeled transistor topology, all source/passive connections,
   full candidate, metrics, history, counts, timing and tokens. An interrupted run also
   receives a clearly labeled partial report if simulation evidence exists.

A Qwen decision counts as one iteration, even with no changes. Every ngspice invocation
counts separately. Final candidate results after the last allowed update are retained,
but no unbudgeted extra Qwen decision is made. A run ending at its iteration limit is
not reported as a Qwen-confirmed successful experiment.

## Configuration and tools

- `target.json`: performance limits, conditions, allowed sizes/bounds and iteration budget.
- `reference.spice`: fixed circuit and testbench; `reference.original.spice` preserves
  the exact user input before testbench corrections. Changing conditions requires matching
  edits to reference and target; startup validates this consistency.
- `agents/sizing_agent/prompt.md`: Qwen analysis instructions.
- `config/settings.json`: existing local model/API/GPU/context/inference settings.
- `tools_path.md`: existing read-only EDA tool locations; no PDK/tools reinstallation.
- Model: `models/Qwen3-8B`; caches: `.runtime`; service logs: `logs`.
- Shared Python: `/home/xu/.venv`; shared Python installation/tools remain under
  `/home/xu/.runtime`. No changes to `/home/xu/eda`.

## Results

`circuits/two_stage_opamp/results/final_report.pdf`

Adjacent files include `summary.json`, `history.json`, `measurements.json`, `calls.json`,
`current.log`, input snapshots, and `logs/simulation_NNN.{log,json,spice}`.
Earlier run-level files are copied into `results/runs/<timestamp>/`; numbered logs are
never overwritten. Use a single run at a time; a file lock enforces this.

The original testbench used unsupported `.meas op` and added radian phase to 180 degrees.
The corrected testbench computes DC power from supply current, reports device OP, and
uses continuous phase in degrees of `-V(out)` (the supplied input-to-output transfer is
inverting). See the official ngspice manual: https://ngspice.sourceforge.io/docs/ngspice-manual.pdf
Only testbench instrumentation was changed; circuit connectivity and initial sizing remain.

The supplied target defines two explicit matched pairs. Tail and bias NMOS lengths are
separate allowed parameters (`L_TAIL`, `L_BIAS_N`); this implementation preserves exactly
that supplied parameterization rather than inventing a new shared bias parameter.

## Validation

```bash
source scripts/env.sh
"$PROJECT_PYTHON" -m pytest -q
```

No mock circuit simulator is included. Unit tests exercise constraint/parser behavior;
they are not evidence of Qwen inference or circuit convergence.

Latest real validation: five local Qwen decisions, six SKY130/ngspice simulations,
normal termination at the five-iteration limit, and an English PDF. Circuit targets
were not all met. See `docs/SIZING_VALIDATION.md` for measured results and limitations.
