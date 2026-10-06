import pytest
from jsonschema import ValidationError
from analog_agents.config import project_path, load_config
from analog_agents.simulation import MockSimulation

PARAMS = dict(input_w_um=20, input_l_um=1, load_w_um=40, stage2_w_um=80, bias_ua=40, compensation_pf=2)

def test_path_escape():
    with pytest.raises(ValueError):
        project_path("../../tmp/escape")

def test_synthetic_provenance(tmp_path):
    result = MockSimulation().run(PARAMS, load_config()["specification"], ["op", "ac"], tmp_path)
    assert result["synthetic"] and not result["real_spice_executed"]
    assert result["metrics"]["power_mw"] == pytest.approx(0.216)
    assert "NOT EXECUTED" in (tmp_path / "conceptual_not_executed.cir").read_text()

def test_reject_bad_sizing(tmp_path):
    with pytest.raises(ValidationError):
        MockSimulation().run({**PARAMS, "compensation_pf": 0}, load_config()["specification"], ["op"], tmp_path)

def test_parameter_update_changes_evaluation(tmp_path):
    tool = MockSimulation()
    first = tool.run(PARAMS, load_config()["specification"], ["ac"], tmp_path)
    second = tool.run({**PARAMS, "bias_ua": 80}, load_config()["specification"], ["ac"], tmp_path)
    assert second["metrics"]["ugb_mhz"] == 2 * first["metrics"]["ugb_mhz"]
