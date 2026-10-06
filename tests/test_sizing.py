import json
from pathlib import Path
import pytest
from agents.sizing_agent.agent import apply_changes, validate_candidate, number
from simulator.ngspice_runner import parse_log
ROOT=Path(__file__).resolve().parents[1]
REF=(ROOT/'circuits/two_stage_opamp/reference/reference.spice').read_text()
TARGET=json.loads((ROOT/'circuits/two_stage_opamp/specs/target.json').read_text())

def test_valid_change_preserves_matching_and_topology():
    after=apply_changes(REF,REF,TARGET,[dict(parameter='W_IN',old_value='10',new_value='12')])
    assert validate_candidate(REF,after,TARGET)['W_IN']=='12'
    assert 'W={W_IN} L={L_IN}' in after

@pytest.mark.parametrize('change',[
    dict(parameter='VDD',old_value='1.8',new_value='2'),
    dict(parameter='W_IN',old_value='10',new_value='101'),
    dict(parameter='W_IN',old_value='11',new_value='12'),
    dict(parameter='W_IN',old_value='10',new_value='10\n.end'),
    dict(parameter='CC',old_value='1p',new_value='0'),
])
def test_reject_unsafe_changes(change):
    with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[change])

def test_reject_topology_edit():
    with pytest.raises(ValueError):validate_candidate(REF,REF.replace('XM1 n1','XM1 out'),TARGET)


def test_suffix_units():
    assert number('1m')==1e-3
    assert number('1meg')==1e6
    assert number('20u')==pytest.approx(20e-6)
    with pytest.raises(ValueError):number('nan')

def test_target_conditions_must_match_reference():
    altered=json.loads(json.dumps(TARGET));altered['conditions']['vdd_v']=1.7
    with pytest.raises(ValueError):validate_candidate(REF,REF,altered)

