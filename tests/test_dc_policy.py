"""Unit fixtures test policy transitions, not circuit accuracy or model quality."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from agents.sizing_agent.agent import apply_changes, validate_candidate
from simulator.ngspice_runner import parse_log, dc_check, simulation_source, NgspiceRunner
from main import optimize
from scripts import service
ROOT=Path(__file__).resolve().parents[1]
REF=(ROOT/'circuits/two_stage_opamp/reference/reference.spice').read_text()
TARGET=json.loads((ROOT/'circuits/two_stage_opamp/specs/target.json').read_text())


def diagnostics():
    values={'v(vdd)':1.8,'v(vinp)':.9,'v(vinn)':.9,'v(vbias_n)':.7,'v(ntail)':.2,'v(n1)':.9,'v(n2)':.9,'v(out)':.9}
    for name,spec in TARGET['dc_acceptance']['devices'].items():
        prefix='@m.'+name.lower()+'.msky130_fd_pr__'+spec['kind']+'_01v8'
        values.update({prefix+'['+key+']':v for key,v in {'id':1e-5,'vgs':.7,'vds':.7,'vth':.3,'vdsat':.1}.items()})
    return values


def test_sat_checks_include_pmos_polarity_cutoff_and_missing():
    op=diagnostics();assert dc_check(op,TARGET)['passed']
    op['v(out)']=1.79
    assert 'XM7' in dc_check(op,TARGET)['failed_devices']
    op=diagnostics();op['v(out)']=.01
    assert 'XM6' in dc_check(op,TARGET)['failed_devices']
    op=diagnostics();key='@m.xm5.msky130_fd_pr__nfet_01v8[id]';op[key]=0
    assert not dc_check(op,TARGET)['devices']['XM5']['passed']
    op.pop(key);assert not dc_check(op,TARGET)['passed']
    op=diagnostics();op['v(vbias_n)']=.1
    assert not dc_check(op,TARGET)['devices']['XM5']['passed']


def test_dc_missing_ac_is_expected_but_full_missing_ac_fails():
    text='\n'.join(f'{k} = {v}' for k,v in diagnostics().items())+'\npower_w = 0.0001\n'
    dc=parse_log(text,0,TARGET,'dc');assert dc['dc_passed'] and dc['simulation_valid']
    assert dc['metrics']['ugb_hz'] is None and not dc['all_targets_passed']
    assert not parse_log(text,0,TARGET,'full')['simulation_valid']
    full=text+'dc_gain_db = 70\nugb_hz = 2e7\nphase_margin_deg = 70\nloop_real_lf = 1000\n'
    assert parse_log(full,0,TARGET,'full')['all_targets_passed']
    assert not parse_log(full+'Error: convergence failed\n',0,TARGET,'full')['all_targets_passed']


@pytest.mark.parametrize('ratio', ['0','1.5','-1','nan','21'])
def test_integer_mirror_ratios(ratio):
    with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[dict(parameter='N_TAIL',old_value='1',new_value=ratio)])


def test_product_width_is_bounded_and_shared_lengths_are_locked():
    with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[dict(parameter='N_TAIL',old_value='1',new_value='20')])
    good=apply_changes(REF,REF,TARGET,[dict(parameter='N_TAIL',old_value='1',new_value='3')])
    assert validate_candidate(REF,good,TARGET)['N_TAIL']=='3'
    damaged=REF.replace('W={N_TAIL*WBN0} L={L_BIAS_N}','W={N_TAIL*WBN0} L={L_IN}')
    with pytest.raises(ValueError):validate_candidate(damaged,damaged,TARGET)
    with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[dict(parameter='L_TAIL',old_value='1',new_value='2')])


def test_dc_source_removes_ac_and_full_requires_certificate(tmp_path):
    dc=simulation_source(REF,'dc')
    assert '\nac ' not in dc and 'meas ac' not in dc and '\nop\n' in dc
    p=tmp_path/'candidate.spice';p.write_text(REF)
    runner=NgspiceRunner(tmp_path,TARGET)
    with pytest.raises(ValueError,match='passing DC'):runner.run(p,mode='full')
    assert runner.count==0


class AgentFixture:
    def __init__(self):self.client=SimpleNamespace(calls=[])
    def run(self,*args):
        self.client.calls.append({'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        return {'analysis':{'simulation_valid':True,'dc_op_valid':True,'main_problem':'fixture','reasoning':'Unit fixture, not inference'},'changes':[]}


class RunnerFixture:
    def __init__(self,path,passes):self.path=path;self.passes=iter(passes);self.modes=[];self.n=0
    def run(self,candidate,mode):
        self.modes.append(mode);self.n+=1
        passed=next(self.passes) if mode=='dc' else True
        (self.path/'current.log').write_text('Unit fixture')
        return dict(dc_passed=passed,all_targets_passed=False,simulation_number=self.n,
            metrics={'power_w':.0001},dc_acceptance={'failed_devices':[] if passed else ['XM6']},
            analysis_mode=mode,simulation_valid=True,return_code=0,warnings=[],errors=[])


def exercise(tmp_path,passes):
    candidate=tmp_path/'candidate.spice';candidate.write_text(REF)
    runner=RunnerFixture(tmp_path,passes);state={'dc_iterations':0};history=[]
    status=optimize(runner,AgentFixture(),candidate,REF,TARGET,tmp_path,history,state)
    return status,runner,state,history


def test_dc_limit_even_when_model_claims_valid(tmp_path):
    status,r,s,h=exercise(tmp_path,[False]*6)
    assert status=='dc_iteration_limit' and len(h)==5 and s['dc_iterations']==5
    assert r.modes==['dc']*6


def test_total_limit_ten_and_dc_precedes_every_full(tmp_path):
    status,r,s,h=exercise(tmp_path,[True]*11)
    assert status=='max_iterations_reached' and len(h)==10 and s['dc_iterations']==0
    assert r.modes==['dc','full']*11


def test_return_to_dc_repair_uses_shared_budget(tmp_path):
    status,r,s,h=exercise(tmp_path,[False,True,False,False,False,False,False])
    assert status=='dc_iteration_limit' and len(h)==6 and s['dc_iterations']==5
    assert [v['phase'] for v in h]==['dc_repair','performance']+['dc_repair']*4
    assert r.modes==['dc','dc','full']+['dc']*5


def test_gpu_selection_never_chooses_busy_device(monkeypatch):
    monkeypatch.setattr(service.subprocess,'check_output',lambda *a,**kw:'0, 20000, 99\n1, 0, 0\n3, 5, 0')
    assert service.choose_idle_gpu(3)==3
    assert service.choose_idle_gpu(0)==1
    monkeypatch.setattr(service.subprocess,'check_output',lambda *a,**kw:'0, 20000, 99')
    with pytest.raises(RuntimeError,match='No idle'):service.choose_idle_gpu(0)


def test_fifth_dc_repair_can_continue_to_total_limit(tmp_path):
    status,r,s,h=exercise(tmp_path,[False]*5+[True]*6)
    assert status=='max_iterations_reached' and len(h)==10 and s['dc_iterations']==5
    assert [x['phase'] for x in h]==['dc_repair']*5+['performance']*5


def test_one_command_cleans_partial_owned_startup(tmp_path,monkeypatch):
    from scripts import run_all
    state=tmp_path/'service.json';actions=[]
    monkeypatch.setattr(run_all.sys,'argv',['run_all.py']);monkeypatch.setenv('SIZING_BACKEND','qwen')
    monkeypatch.setattr(run_all,'project_path',lambda p:tmp_path/p)
    monkeypatch.setattr(service,'STATE',state)
    def start(**kwargs):
        state.write_text('{"pid":123}');raise RuntimeError('startup fixture failure')
    def stop():actions.append('stopped');state.unlink()
    monkeypatch.setattr(service,'start',start);monkeypatch.setattr(service,'stop',stop)
    with pytest.raises(RuntimeError,match='fixture failure'):run_all.main()
    assert actions==['stopped'] and not state.exists()


def test_one_command_does_not_stop_preexisting_service(tmp_path,monkeypatch):
    from scripts import run_all
    state=tmp_path/'service.json';state.write_text('{"pid":123}');actions=[]
    monkeypatch.setattr(run_all.sys,'argv',['run_all.py']);monkeypatch.setenv('SIZING_BACKEND','qwen')
    monkeypatch.setattr(run_all,'project_path',lambda p:tmp_path/p)
    monkeypatch.setattr(service,'STATE',state)
    monkeypatch.setattr(service,'owned',lambda s:True)
    monkeypatch.setattr(service,'stop',lambda:actions.append('stopped'))
    with pytest.raises(RuntimeError,match='already running'):run_all.main()
    assert actions==[] and state.exists()


def test_rejected_stale_proposal_preserves_candidate_and_consumes_budget(tmp_path):
    class StaleAgent(AgentFixture):
        def run(self,*args):
            reply=super().run(*args)
            reply['changes']=[dict(parameter='W_IN',old_value='99',new_value='12',reason='invalid unit fixture')]
            return reply
    candidate=tmp_path/'candidate.spice';candidate.write_text(REF)
    history=[];state={'dc_iterations':0};runner=RunnerFixture(tmp_path,[False]*6)
    status=optimize(runner,StaleAgent(),candidate,REF,TARGET,tmp_path,history,state)
    assert status=='dc_iteration_limit' and len(history)==5
    assert candidate.read_text()==REF and all(not x['proposal_accepted'] for x in history)
    assert all('old_value' in x['validation_error'] for x in history)


def test_pmos_stage_terminal_policy_and_removed_parameters():
    policy=TARGET['dc_acceptance']['devices']
    assert len(policy)==8 and 'XMBIAS_P' not in policy
    assert policy['XM6']['gate']=='vbias_n' and policy['XM6']['kind']=='nfet'
    assert policy['XM7']['gate']=='n2' and policy['XM7']['kind']=='pfet'
    allowed=TARGET['optimization']['allowed_parameters']
    assert 'N_STAGE2_BIAS' in allowed
    assert not {'N_STAGE2_LOAD','WBP0','L_BIAS_P'}.intersection(allowed)
    assert TARGET['optimization']['device_dimensions']['XM6']=={'W':'N_STAGE2_BIAS*WBN0','L':'L_BIAS_N'}
    assert TARGET['optimization']['device_dimensions']['XM7']=={'W':'W_STAGE2','L':'L_STAGE2'}
    validate_candidate(REF,REF,TARGET)


def test_m6_bias_and_m7_signal_gate_have_correct_dc_polarity():
    op=diagnostics();op['v(n2)']=1.6
    result=dc_check(op,TARGET)
    assert result['devices']['XM6']['passed']
    assert not result['devices']['XM7']['checks']['overdrive']
    op=diagnostics();op['v(vbias_n)']=.1
    result=dc_check(op,TARGET)
    assert not result['devices']['XM6']['checks']['overdrive']
    assert result['devices']['XM7']['passed']


def test_dc_mapping_cannot_silently_use_old_nmos_stage():
    old=REF.replace('XM6 out vbias_n 0 0','XM6 out n2 0 0')
    with pytest.raises(ValueError,match='terminal mapping'):validate_candidate(old,old,TARGET)


def test_ac_polarity_failure_does_not_invalidate_passing_dc():
    text='\n'.join(f'{k} = {v}' for k,v in diagnostics().items())
    text+='\npower_w = 0.0001\nEND_DC_OPERATING_POINT\n'
    text+='dc_gain_db = 70\nugb_hz = 2e7\nphase_margin_deg = 70\n'
    for value in ['-1000','0','nan']:
        result=parse_log(text+'loop_real_lf = '+value+'\n',0,TARGET,'full')
        assert result['dc_passed'] and not result['all_targets_passed']
        assert not result['ac_polarity']['passed']
    result=parse_log(text+'loop_real_lf = 1000\n',0,TARGET,'full')
    assert result['dc_passed'] and result['all_targets_passed']


def test_reference_differential_gain_and_power_conventions():
    assert 'let differential_gain = v(out)/differential_input' in REF
    assert 'let differential_input = v(vinp)-v(vinn)' in REF
    assert 'let loop_gain = -differential_gain' in REF
    assert 'let gain = db(differential_gain)' in REF
    assert 'let loop_phase_deg = 180/PI*cph(loop_gain)' in REF
    assert 'let power_w = -i(VSUPPLY)*v(vdd)' in REF
    assert 'IBIAS_P ' not in REF
