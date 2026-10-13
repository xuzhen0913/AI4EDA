"""Unit fixtures test policy transitions, not circuit accuracy or model quality."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from agents.sizing_agent.agent import apply_changes, validate_candidate
from simulator.ngspice_runner import parse_log, dc_check, NgspiceRunner
from simulator.testbench import deck
from agents.sizing_agent.loop import optimize
from scripts import service
ROOT=Path(__file__).resolve().parents[1]
from analog_agents.reference import design_target, parse_reference
from helpers import REF, SPECS, TARGET


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
    # Constraints are read from the netlist itself: a circuit wired differently is simply a different reference.
    rewired=REF.replace('W={N_TAIL*WBN0} L={L_BIAS_N}','W={N_TAIL*WBN0} L={L_IN}')
    target=design_target(SPECS,parse_reference(rewired,'rewired'))
    assert target['optimization']['device_dimensions']['XM5']=={'W':'N_TAIL*WBN0','L':'L_IN'}
    assert validate_candidate(rewired,rewired,target)
    with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[dict(parameter='L_TAIL',old_value='1',new_value='2')])


def test_dc_deck_has_no_ac_and_full_requires_certificate(tmp_path):
    library='/lib/sky130.lib.spice'
    dc=deck(REF,TARGET,library,'dc',TARGET['feedback_input'])
    assert '\nac ' not in dc and 'meas ac' not in dc and '\nop\n' in dc and 'print v(out)' in dc
    assert 'ac dec 100 1 1000000000' in deck(REF,TARGET,library,'full',TARGET['feedback_input'])
    p=tmp_path/'candidate.spice';p.write_text(REF)
    runner=NgspiceRunner(tmp_path,TARGET)
    with pytest.raises(ValueError,match='passing DC'):runner.run(p,mode='full')
    assert runner.count==0


class AgentFixture:
    def __init__(self):self.client=SimpleNamespace(calls=[])
    def run(self,*args,**kwargs):
        self.client.calls.append({'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        return {'analysis':{'simulation_valid':True,'dc_op_valid':True,'main_problem':'fixture','reasoning':'Unit fixture, not inference'},'changes':[]}


class RunnerFixture:
    def __init__(self,path,passes):self.path=path;self.passes=iter(passes);self.modes=[];self.n=0
    def run(self,candidate,mode):
        self.modes.append(mode);self.n+=1
        passed=next(self.passes) if mode=='dc' else True
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


def test_rejected_proposal_preserves_candidate_is_re_asked_and_only_costs_budget_after_the_free_allowance(tmp_path):
    class StaleAgent(AgentFixture):
        asked=0
        def run(self,*args,**kwargs):
            StaleAgent.asked+=1
            reply=super().run(*args,**kwargs)
            reply['changes']=[dict(parameter='N_TAIL',new_value='20',reason='product width out of range fixture')]
            return reply
    candidate=tmp_path/'candidate.spice';candidate.write_text(REF)
    history=[];state={'dc_iterations':0};runner=RunnerFixture(tmp_path,[False]*6)
    status=optimize(runner,StaleAgent(),candidate,REF,TARGET,tmp_path,history,state)
    free=[x for x in history if x.get('free')]
    assert status=='dc_iteration_limit' and len(history)==8 and len(free)==3 and history[:3]==free   # 3 refusals cost nothing
    assert state['dc_iterations']==5 and runner.n==1                                                # nothing was re-simulated
    assert candidate.read_text()==REF and all(not x['accepted'] for x in history)
    assert all('outside its limit' in x['validation_error'] for x in history)
    assert all(len(x['rejected_attempts'])==1 for x in history) and StaleAgent.asked==16   # the repeat ends the asking: 2 asks per decision
    assert all(x['changes'][0]['old_value']=='1' for x in history)                         # the old value is filled in by the loop


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


def test_testbench_conventions_are_generated_not_copied():
    text=deck(REF,TARGET,'/lib/sky130.lib.spice','full',TARGET['feedback_input'])
    for line in ('let loop_gain = -v(out)/v(acin)','let gain = db(loop_gain)','let loop_phase_deg = 180/PI*cph(loop_gain)',
                 'let power_w = -i(VSUPPLY)*v(vdd)','VINN vinn 0 DC {VCM}','CLOAD_OUT out 0 {CLOAD}',
                 '.lib "/lib/sky130.lib.spice" tt','.temp 27','.param VDD=1.8','.param VCM=0.9','.param CLOAD=2e-12'):
        assert line in text.splitlines(),line
    assert 'IBIAS_P ' not in text and 'differential_gain' not in text   # no assumption about which way the circuit inverts


def test_closed_loop_must_hold_the_output_at_vcm():
    """With the loop closed a healthy amplifier sits at VCM; anything else means no regulation (wrong feedback input,
    a saturated stage, or no current), which is a DC failure even when every device row passes."""
    op=diagnostics()
    ok=dc_check(op,TARGET);assert ok['passed'] and ok['loop']['passed'] and ok['loop']['output_error_v']==pytest.approx(0)
    for out in (1.79,0.01,0.9501,0.8499):
        op=diagnostics();op['v(out)']=out
        bad=dc_check(op,TARGET)['loop']
        assert not bad['passed'] and bad['output_error_v']==pytest.approx(out-0.9) and bad['maximum_output_error_v']==0.05
    op=diagnostics();op['v(out)']=0.94;assert dc_check(op,TARGET)['loop']['passed']
    op=diagnostics();del op['v(out)'];assert not dc_check(op,TARGET)['loop']['passed']
    # a dc_acceptance without the window (a generic target) is not subject to the check
    generic=json_copy(TARGET);del generic['dc_acceptance']['maximum_output_error_v']
    op=diagnostics();op['v(out)']=1.7;assert dc_check(op,generic)['loop']['passed']


def json_copy(value):
    import json
    return json.loads(json.dumps(value))


def test_a_loop_that_does_not_regulate_fails_dc_in_the_parsed_record():
    text='\n'.join(f'{k} = {v}' for k,v in {**diagnostics(),'v(out)':1.7}.items())+'\npower_w = 0.0001\nEND_DC_OPERATING_POINT\n'
    result=parse_log(text,0,TARGET,'dc')
    assert not result['dc_passed'] and result['dc_acceptance']['failed_devices']==[] and not result['dc_acceptance']['loop']['passed']


def test_record_carries_the_declared_feedback_input_and_the_bias_mode():
    base='\n'.join(f'{k} = {v}' for k,v in diagnostics().items())+'\npower_w = 0.0001\nEND_DC_OPERATING_POINT\n'
    base+='dc_gain_db = 70\nugb_hz = 2e7\nphase_margin_deg = 70\nloop_real_lf = 1000\n'
    result=parse_log(base,0,TARGET,'full')
    assert result['bias']=='closed_loop' and result['ac_polarity']['feedback_input']==TARGET['feedback_input']=='vinp'
    assert result['all_targets_passed']
    negative=parse_log(base.replace('loop_real_lf = 1000','loop_real_lf = -1000'),0,TARGET,'full')
    assert not negative['simulation_valid'] and any('wrong feedback input' in e for e in negative['errors'])


def test_loop_failure_with_every_device_fine_is_visible_in_the_history(tmp_path):
    from analog_agents.search import history_table
    class LoopRunner(RunnerFixture):
        def run(self,candidate,mode):
            m=super().run(candidate,mode)
            if not m['dc_passed']:m['dc_acceptance']={'failed_devices':[],'loop':{'passed':False,'output_error_v':0.6,'maximum_output_error_v':0.05}}
            return m
    candidate=tmp_path/'candidate.spice';candidate.write_text(REF)
    runner=LoopRunner(tmp_path,[False]+[True]*11);state={'dc_iterations':0};history=[]
    optimize(runner,AgentFixture(),candidate,REF,TARGET,tmp_path,history,state)
    assert history[0]['before']['loop_regulated'] is False and history[0]['before']['failed_dc_devices']==[]
    assert history[0]['result']['dc_passed'] and 'loop_regulated' not in history[0]['result']
    table=history_table(history)
    assert table['rows'][0][0]=='start' and 'loop does not hold out' in table['rows'][0][table['columns'].index('dc')]
