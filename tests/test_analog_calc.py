import json
import math
from pathlib import Path
from agents.sizing_agent.agent import number, parameters
from analog_agents import analog_calc as ac

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'circuits/two_stage_opamp/results/logs'


def test_formulas():
    assert math.isclose(ac.sheet_resistor(100, 10, 1), 1000)
    assert ac.zero_hz(1 / 3000, 1e-12, 1000) > 0          # R < 1/gm -> RHP
    assert ac.zero_hz(1 / 3000, 1e-12, 5000) < 0          # R > 1/gm -> LHP
    assert ac.zero_hz(1 / 3000, 1e-12, 3000) is None
    assert math.isclose(ac.mirror_ratio_mismatch(60, 20, 9.4, 21.3), 1.32, abs_tol=0.01)
    assert math.isclose(ac.target_wl_for_balance(20, 9.4, 21.3), 45.3, abs_tol=0.1)


def test_derive_on_recorded_run():
    target = json.loads((ROOT / 'circuits/two_stage_opamp/specs/target.json').read_text())
    path = RESULTS / 'simulation_112.json'
    if not path.exists():
        return
    measurements = json.loads(path.read_text())
    params = parameters((ROOT / 'circuits/two_stage_opamp/reference/reference.spice').read_text())
    d = ac.derive(target, params, measurements, number)
    assert d['stage_balance']['Rm'] > 1.2                 # default failing design
    assert d['series_resistor_ohm'] == 1000
    assert d['compensation']['zero_side'].startswith('RHP')
