import pytest
from agents.sizing_agent.agent import apply_changes, validate_candidate
from analog_agents.spice import number
from helpers import REF, TARGET

def test_valid_change_preserves_matching_and_topology():
    after=apply_changes(REF,REF,TARGET,[dict(parameter='W_IN',old_value='10',new_value='12')])
    assert validate_candidate(REF,after,TARGET)['W_IN']=='12'
    assert 'W={W_IN} L={L_IN}' in after and '; tune 1..100 um' in after   # the tune annotation survives edits

@pytest.mark.parametrize('change',[
    dict(parameter='VDD',old_value='1.8',new_value='2'),            # testbench condition, not a parameter of the circuit
    dict(parameter='RSH_RZ',old_value='100',new_value='200'),       # fixed constant
    dict(parameter='W_IN',old_value='10',new_value='101'),
    dict(parameter='W_IN',old_value='11',new_value='12'),
    dict(parameter='W_IN',old_value='10',new_value='10\n.end'),
    dict(parameter='CC',old_value='1p',new_value='0'),
])
def test_reject_unsafe_changes(change):
    with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[change])

def test_reject_topology_edit():
    with pytest.raises(ValueError):validate_candidate(REF,REF.replace('XM1 n1','XM1 out'),TARGET)

def test_bounds_annotation_cannot_be_edited_through_a_value_change():
    widened=REF.replace('.param W_IN=10          ; tune 1..100 um','.param W_IN=500         ; tune 1..1000 um')
    assert widened!=REF
    with pytest.raises(ValueError):validate_candidate(REF,widened,TARGET)

def test_suffix_units():
    assert number('1m')==1e-3
    assert number('1meg')==1e6
    assert number('20u')==pytest.approx(20e-6)
    with pytest.raises(ValueError):number('nan')
