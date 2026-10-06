import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from .config import load_config, project_path
from .client import LocalClient
from .agents import Agent
from .simulation import MockSimulation
from .reporting import ReportingAgent, summarize

def main():
    started = time.perf_counter()
    cfg = load_config()
    stamp = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d-%H%M%S-%f")
    out = project_path(f"outputs/{stamp}")
    out.mkdir(parents=True)
    def save(name, value):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    save("config.json", cfg)
    client = LocalClient(cfg)
    context = {"specification": cfg["specification"]}
    history = []
    updates = 0
    simulations_attempted = 0
    simulation_seconds = 0.0
    status, error = "completed", None
    try:
        agents = {name: Agent(name, client) for name in ("architecture", "sizing", "simulation", "optimization")}
        for name in ("architecture", "sizing"):
            context[name] = agents[name].run(context)
            save(name+".json", context[name])
            print(f"{name}: OK", flush=True)
        params = context["sizing"]["parameters"]
        # Initial evaluation plus up to max_iterations actual parameter updates.
        for step in range(cfg["max_iterations"]+1):
            step_dir = out / f"iteration-{step}"
            step_dir.mkdir()
            plan = agents["simulation"].run({**context, "parameters": params})
            simulations_attempted += 1
            sim_started = time.perf_counter()
            try:
                result = MockSimulation().run(params, cfg["specification"], plan["analyses"], step_dir)
            finally:
                simulation_seconds += time.perf_counter() - sim_started
            record = {"iteration": step, "parameters": params, "simulation_plan": plan, "simulation": result}
            history.append(record)
            save("history.json", history)
            print(f"simulation {step}: MOCK {result['metrics']}", flush=True)
            if step == cfg["max_iterations"]:
                break
            advice = agents["optimization"].run({**context, **record})
            record["optimization"] = advice
            save("history.json", history)
            if advice["stop"] and result["all_targets_met_synthetically"]:
                break
            params = advice["parameters"]
            updates += 1
    except Exception as exc:
        status, error = "failed", str(exc)
        save("failure.json", {"status": "failed", "error": str(exc)})
        raise
    finally:
        summary = summarize(cfg, context, history, client.calls, status, error,
                            updates, simulations_attempted, simulation_seconds,
                            time.perf_counter() - started)
        save("calls.json", client.calls)
        save("summary.json", summary)
        ReportingAgent().run(summary, out)
    print(f"Results: {out}")
    print(f"PDF: {out / 'REPORT.pdf'}")

if __name__ == "__main__":
    main()
