"""The sizing layer must not require an amplifier, SKY130, or MOS devices."""
import copy
import pytest
from agents.sizing_agent.agent import apply_changes, validate_candidate

REF='''* Passive module, chosen by an upstream topology selector.
* Keep RA and RB matched via the same RVAL; fixed source and connections.
.param RVAL=1k
.param OFFSET=0
VTEST in 0 1
RA in out {RVAL}
RB out 0 {RVAL}
.end
'''
TARGET={'targets':{'ratio':{'min':0.49,'max':0.51}},'optimization':{
    'allowed_parameters':['RVAL','OFFSET'],
    'parameter_bounds':{'RVAL':{'min':100,'max':10000},'OFFSET':{'min':-1,'max':1}}}}

def test_passive_topology_and_signed_parameter():
    changed=apply_changes(REF,REF,TARGET,[dict(parameter='RVAL',old_value='1k',new_value='2k'),
        dict(parameter='OFFSET',old_value='0',new_value='-0.5')])
    assert validate_candidate(REF,changed,TARGET)['OFFSET']=='-0.5'
    assert 'RA in out {RVAL}' in changed and 'RB out 0 {RVAL}' in changed
    with pytest.raises(ValueError):validate_candidate(REF,changed.replace('RB out 0','RB in 0'),TARGET)
    with pytest.raises(ValueError):validate_candidate(REF,changed.replace('Keep RA','Ignore RA'),TARGET)

def test_other_process_arbitrary_instance_name():
    ref='* Example selected topology\n.param SIZE=2\nMGAIN output input 0 0 custom_n W={SIZE} L=1u\n.end\n'
    target={'optimization':{'allowed_parameters':['SIZE'],'parameter_bounds':{'SIZE':{'min':1,'max':10}}},
        'dc_acceptance':{'devices':{'MGAIN':{'drain':'output','gate':'input','source':'0','body':'0','model':'custom_n'}}}}
    assert apply_changes(ref,ref,target,[dict(parameter='SIZE',old_value='2',new_value='3')])
    wrong=copy.deepcopy(target);wrong['dc_acceptance']['devices']['MGAIN']['model']='another_model'
    with pytest.raises(ValueError):validate_candidate(ref,ref,wrong)
