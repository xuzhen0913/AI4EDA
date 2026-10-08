import copy
from types import SimpleNamespace
import pytest
from analog_agents.context import compact_payload
from analog_agents.client import LocalClient, ClaudeCliClient
from analog_agents import rules


def payload():
    return dict(reference_spice='* Keep R matched; equation a=b\n.param R=1k\nRA in 0 {R}\n',
        candidate_spice='* Keep R matched; equation a=b\n.param R=2k\nRA in 0 {R}\n',
        current_parameters={'R':'2k'},target={'targets':{'x':{'min':1}}},
        measurements={'dc_operating_point':{'v(in)':1.0,'@device[gm]':0.1},'metrics':{'x':2.0}},
        full_ngspice_log='v(in) = 1\nx = 2\nx = 3\n@device[gm] = .1\nwarning: floating node\nError: model missing\nunknown_scalar = 4\n',
        history=[],global_analog_design_rules={'content':'ALL RULES'})


def test_packing_preserves_evidence_and_source():
    p=payload();original=copy.deepcopy(p);record={};c=compact_payload(p,record)
    assert p==original
    assert c['current_parameters']=={'R':'2k'} and 'candidate_spice' not in c
    assert 'Keep R matched; equation a=b' in c['reference_spice']
    assert c['measurements']['device_operating_point']['@device']['gm']==.1
    assert 'x = 2\n' not in c['log_additional_evidence']
    for text in ('x = 3','warning: floating node','Error: model missing','unknown_scalar = 4'):
        assert text in c['log_additional_evidence']
    assert c['global_analog_design_rules']==p['global_analog_design_rules']
    assert c['target']==p['target']


def test_changed_topology_is_not_hidden_by_overrides():
    p=payload();p['candidate_spice']=p['candidate_spice'].replace('RA in 0','RA other 0')
    c=compact_payload(p,{})
    assert 'candidate_parameter_overrides' not in c and 'RA other 0' in c['candidate_spice']


def test_history_reconstruction_and_rejected_proposal():
    p=payload();p['history']=[dict(iteration=i,parameters_before={'R':str(i)},
        parameters_after={'R':str(i+1) if i!=2 else str(i)},
        parameter_changes=[{'parameter':'R','old_value':str(i),'new_value':'99','reason':'proposal'}],
        validation_error='rejected' if i==2 else None,result_measurements={'gain':i},
        qwen_analysis={'main_problem':'bias','reasoning':'wrong old theory'}) for i in range(1,5)]
    rows=compact_payload(p,{})['history'];state={}
    for src,row in zip(p['history'],rows):
        state=copy.deepcopy(row.get('parameters_before',state))
        state.update(row.get('parameters_before_delta',{}))
        assert state==src['parameters_before']
        state.update(row.get('actual_parameter_delta',{}))
        assert state==src['parameters_after']
        assert row['result_measurements']==src['result_measurements']
        assert row['validation_error']==src['validation_error']
        assert 'qwen_analysis' not in row and all('reason' not in c for c in row['parameter_changes'])
    assert rows[1]['actual_parameter_delta']=={}


@pytest.mark.parametrize('client_type',[LocalClient,ClaudeCliClient])
def test_both_backends_use_shared_rules_and_compression(client_type,tmp_path,monkeypatch):
    path=tmp_path/'rules.md';path.write_text('shared rules')
    monkeypatch.setattr(rules,'RULES_PATH',path)
    client=object.__new__(client_type);client.calls=[]
    client._ask=lambda prompt,payload,schema,record:payload
    result=client.ask('generic',payload(),{})
    assert result['global_analog_design_rules']['content']=='shared rules'
    assert 'candidate_spice' not in result and 'current_parameters' in result
    assert client.calls[-1]['context_compression']['version']==2
    path.unlink()
    with pytest.raises(FileNotFoundError):client.ask('generic',payload(),{})


def test_exact_failure_flags_survive_table_encoding():
    p=payload()
    device={'passed':False,'checks':{'overdrive':False,'saturation':True},
            'overdrive_v':-.01,'saturation_margin_v':.47}
    p['measurements']['dc_acceptance']={'devices':{'M':device}}
    c=compact_payload(p,{})
    table=c['measurements']['dc_acceptance']['device_table']
    restored=dict(zip(table['columns'],table['rows'][0]));restored.pop('device')
    assert restored==device
    assert c['decision_focus']['failed_dc_checks']['M']['failed_checks']==['overdrive']


def test_repeated_measurement_reference_is_exact():
    p=payload();p['history']=[{'iteration':1,'result_measurements':{'gain':2}},
                            {'iteration':2,'measurements':{'gain':2},'result_measurements':{'gain':3}},
                            {'iteration':3,'measurements':{'gain':4}}]
    rows=compact_payload(p,{})['history']
    assert rows[1]['measurements_from_iteration']==1 and 'measurements' not in rows[1]
    assert rows[2]['measurements']=={'gain':4}


def test_model_input_omits_log_location_and_launcher_command():
    p=payload();p['measurements']['log']='/archive/old_runs/logs/current.log'
    p['full_ngspice_log']='COMMAND: ["ngspice", "/archive/old_runs/logs/current.spice"]\nError: model missing\n'
    result=compact_payload(p,{})
    assert 'log' not in result['measurements']
    assert 'COMMAND:' not in result['log_additional_evidence']
    assert 'Error: model missing' in result['log_additional_evidence']
    assert result['history']==[] and 'this optimization invocation' in result['input_scope']
