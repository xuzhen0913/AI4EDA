"""Explicitly synthetic backend. No subprocess executes model-generated code."""
import math
from typing import Protocol
from jsonschema import validate
from .agents import PARAMETERS

MOCK_FORMULA = "gain_db=45+12*log10(input_w_um/input_l_um); ugb_mhz=0.8*bias_ua/compensation_pf; phase_margin_deg=min(89,45+12*compensation_pf-0.2*load_pf); power_mw=vdd_v*3*bias_ua/1000. Synthetic only; not physical predictions."

class Simulator(Protocol):
    def run(self, parameters, spec, analyses, output_dir) -> dict: ...

def netlist(p, spec, analyses):
    validate(p, PARAMETERS)
    # Fixed connectivity, numeric parameters only; illustrative LEVEL=1 models are not a PDK.
    w, l, load, stage, bias, cc = [p[k] for k in PARAMETERS["properties"]]
    commands = {"op": ".op", "ac": ".ac dec 50 1 1G", "tran": ".tran 1n 10u"}
    return f"""* CONCEPTUAL TEMPLATE ONLY - NOT EXECUTED; no foundry PDK
* NMOS pair + PMOS mirror + PMOS common source second stage
VDD vdd 0 {spec['vdd_v']}
VINP inp 0 DC {spec['vdd_v']/2} AC 0.5
VINN inn 0 DC {spec['vdd_v']/2} AC 0.5 180
ITAIL tail 0 {bias}u
M1 n1 inp tail 0 NM W={w}u L={l}u
M2 n2 inn tail 0 NM W={w}u L={l}u
M3 n1 n1 vdd vdd PM W={load}u L={l}u
M4 n2 n1 vdd vdd PM W={load}u L={l}u
M5 out n2 vdd vdd PM W={stage}u L={l}u
IBIAS out 0 {2*bias}u
CC n2 out {cc}p
CL out 0 {spec['load_pf']}p
.model NM NMOS LEVEL=1 VTO=0.45 KP=120u LAMBDA=0.04
.model PM PMOS LEVEL=1 VTO=-0.45 KP=50u LAMBDA=0.04
""" + "\n".join(commands[a] for a in analyses) + "\n.end\n"

class MockSimulation:
    def run(self, parameters, spec, analyses, output_dir):
        validate(parameters, PARAMETERS)
        (output_dir / "conceptual_not_executed.cir").write_text(netlist(parameters, spec, analyses))
        p = parameters
        metrics = {"gain_db": round(45+12*math.log10(p["input_w_um"]/p["input_l_um"]), 3),
                   "ugb_mhz": round(0.8*p["bias_ua"]/p["compensation_pf"], 3),
                   "phase_margin_deg": round(min(89, 45+12*p["compensation_pf"]-0.2*spec["load_pf"]), 3),
                   "power_mw": round(spec["vdd_v"]*3*p["bias_ua"]/1000, 4)}
        checks = {k: metrics[k] >= spec[k+"_min"] for k in ("gain_db", "ugb_mhz", "phase_margin_deg")}
        checks["power_mw"] = metrics["power_mw"] <= spec["power_mw_max"]
        return {"backend": "mock", "synthetic": True, "real_spice_executed": False,
                "warning": "仅用于软件流程测试；不得作为真实电路性能或流片依据。",
                "metrics": metrics, "checks": checks, "all_targets_met_synthetically": all(checks.values()),
                "mock_formula": MOCK_FORMULA}
