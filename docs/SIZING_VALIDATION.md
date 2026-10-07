> Historical validation of the previous NMOS-gain-stage topology. On 2026-10-07 the
> project was adapted to the user-provided PMOS M7 gain stage and NMOS M6 bias sink.
> That revision received static checks only; the results and test-pass counts below
> must not be attributed to the new circuit. See README.md and README_EN.md.

# DC-first validation — 2026-10-06

Implemented shared input W/L, shared mirror L and positive-integer output/reference width ratios.
Python validates both base parameters and effective N*W sizes. Removed independent mirror dimensions.

## Automated checks

26 tests pass, including integer rejection, product bounds, missing/cutoff/PMOS DC checks,
DC-before-AC transitions, DC re-entry, cumulative five-DC and ten-total decision budgets,
invalid proposal feedback, idle GPU selection and owned-service cleanup. Python and shell syntax pass.
Transition fixtures test policy only; they do not claim circuit performance or Qwen reasoning.

## Actual one-command run

Executed `bash /home/xu/Multi-agent/scripts/run_all.sh` against the existing local Qwen3-8B
on idle GPU 3, with real SKY130/ngspice. Startup and automatic shutdown succeeded.

{
  "status": "dc_iteration_limit",
  "error": null,
  "iteration_count": 5,
  "dc_iteration_count": 5,
  "performance_iteration_count": 0,
  "simulation_count": 6,
  "design_backend": "local_qwen",
  "model": "qwen3-8b-local",
  "workflow_completed": true,
  "max_iterations": 10,
  "max_dc_iterations": 5,
  "optimization_start_time": "2026-10-06T13:13:58.846024+00:00",
  "optimization_end_time": "2026-10-06T13:16:53.827476+00:00",
  "total_optimization_time_seconds": 174.98146464582533,
  "final_simulation_number": 18,
  "tokens": {
    "prompt_tokens": 95821,
    "completion_tokens": 1935,
    "total_tokens": 97756
  },
  "token_usage_complete": true,
  "qwen_call_count": 5
}

Six actual DC-only simulations ran: baseline plus five decisions. M6 remained outside the
configured saturation acceptance region, so AC was never executed. All AC values are null,
not zero and not copied from older experiments. The run terminated at the five-DC limit.
Both English and Chinese PDFs were generated, and the managed service state was removed.
The performance-stage path is covered by transition tests; it was not reached by this real run.

One earlier validation exposed a stale old_value proposal. Rejected proposals now preserve the
candidate, record validation_error, consume the decision budget and feed the rejection back.
The final real run also exercised that rejection path. The model did not achieve a valid DC design;
this does not imply the original Qwen's circuit reasoning is reliable. No replacement sizing was injected.

Results: circuits/two_stage_opamp/results/final_report.pdf and final_report_zh.pdf.
The last simulation's per-device saturation margins are in measurements.json.
