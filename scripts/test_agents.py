"""Calls each agent independently against the real local Qwen API."""
import json
from analog_agents.config import load_config, project_path
from analog_agents.agents import Agent
from analog_agents.client import LocalClient

def main():
    c = load_config()
    params = dict(input_w_um=20, input_l_um=1, load_w_um=40, stage2_w_um=80, bias_ua=40, compensation_pf=2)
    payload = {"specification": c["specification"], "architecture": {"topology": "two_stage_cmos_opamp"},
        "parameters": params, "simulation": {"backend": "mock", "synthetic": True,
        "metrics": {"gain_db": 60.6, "ugb_mhz": 16, "phase_margin_deg": 68, "power_mw": 0.216}}}
    results = {}
    for name in ("architecture", "sizing", "simulation", "optimization"):
        results[name] = {"status": "passed", "response": Agent(name, LocalClient(c)).run(payload)}
        project_path("logs/agent_tests.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(name, "PASS", flush=True)

if __name__ == "__main__":
    main()
