import json
from types import SimpleNamespace as NS
import pytest
from analog_agents.client import LocalClient
from analog_agents.config import load_config
from analog_agents.reporting import summarize, ReportingAgent
from analog_agents.simulation import MockSimulation

P=dict(input_w_um=20,input_l_um=1,load_w_um=40,stage2_w_um=80,bias_ua=40,compensation_pf=2)

def test_rates_counts_and_partial_usage(tmp_path):
    cfg=load_config()
    result=MockSimulation().run(P,cfg['specification'],['op'],tmp_path)
    history=[{'iteration':0,'parameters':P,'simulation':result}]
    calls=[{'agent':'sizing','status':'passed','usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},'seconds':1.2},
           {'agent':'optimization','status':'failed','usage':None,'seconds':0.5}]
    s=summarize(cfg,{},history,calls,'failed','network',0,1,0.01,2)
    assert s['success_rate']['design_success_percent']==0
    assert s['number_of_simulations']=={'real_spice':0,'mock_attempted':1,'mock_completed':1}
    assert s['token_cost']['total_tokens']==15 and not s['token_cost']['usage_complete']
    assert s['token_cost']['currency_cost'] is None
    assert ReportingAgent().run(s,tmp_path).read_bytes().startswith(b'%PDF')

def test_success_and_empty_failure(tmp_path):
    cfg=load_config()
    h=[{'iteration':0,'parameters':P,'simulation':{'all_targets_met_synthetically':True}}]
    assert summarize(cfg,{},h,[],'completed',None,0,1,0.1,1)['success_rate']['design_success_percent']==100
    s=summarize(cfg,{},[],[],'failed','no response',0,0,0,1)
    assert s['final'] is None and s['success_rate']['design_success_percent']==0
    assert ReportingAgent().run(s,tmp_path).exists()

def test_client_records_usage_even_when_schema_fails():
    client=LocalClient(load_config())
    reply=NS(usage=NS(prompt_tokens=4,completion_tokens=3,total_tokens=7),choices=[NS(finish_reason='stop',message=NS(content='{"answer": "wrong type"}'))])
    client.api=NS(chat=NS(completions=NS(create=lambda **kw:reply)))
    with pytest.raises(Exception):
        client.ask('test',{}, {'type':'object','properties':{'answer':{'type':'integer'}}},agent_name='sizing')
    assert client.calls[0]['usage']['total_tokens']==7
    assert client.calls[0]['status']=='failed'
    assert client.calls[0]['seconds']>=0
