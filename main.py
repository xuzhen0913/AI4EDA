"""DC-gated fixed-topology sizing, with independent DC and total decision budgets."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import time
from analog_agents.config import load_config, ROOT
from agents.sizing_agent.agent import SizingAgent, apply_changes, parameters, validate_candidate
from simulator.ngspice_runner import NgspiceRunner, save
from simulator.report_generator import generate

BASE=ROOT/'circuits/two_stage_opamp'


def evaluate(runner, candidate):
    dc=runner.run(candidate,mode='dc')
    if not dc['dc_passed']:return dc
    full=runner.run(candidate,mode='full')
    full['preceding_dc_simulation_number']=dc['simulation_number']
    return full


def optimize(runner, agent, candidate, reference, target, results, history, state, baseline_only=False):
    state['measurement']=evaluate(runner,candidate)
    if baseline_only:return 'baseline_only'
    limits=target['optimization']
    while True:
        measurement=state['measurement']
        if measurement['all_targets_passed']:return 'targets_passed'
        if not measurement['dc_passed'] and state['dc_iterations']>=limits['max_dc_iterations']:
            return 'dc_iteration_limit'
        if len(history)>=limits['max_iterations']:return 'max_iterations_reached'
        phase='dc_repair' if not measurement['dc_passed'] else 'performance'
        tick=time.perf_counter();before=candidate.read_text()
        reply=agent.run(target,reference,before,(results/'current.log').read_text(),measurement,history)
        if phase=='dc_repair':state['dc_iterations']+=1
        row=dict(iteration=len(history)+1,phase=phase,simulation_number=measurement['simulation_number'],
            parameters_before=parameters(before),measurements=measurement['metrics'],
            simulation_status={k:measurement[k] for k in ['analysis_mode','dc_passed','simulation_valid','return_code','warnings','errors']},
            failed_dc_devices=measurement['dc_acceptance']['failed_devices'],
            qwen_analysis=reply['analysis'],parameter_changes=reply['changes'],
            parameters_after=parameters(before),qwen_token_usage=agent.client.calls[-1]['usage'])
        history.append(row)
        try:
            try:
                proposed=apply_changes(reference,before,target,reply['changes'])
            except ValueError as exc:
                row['validation_error']=str(exc)
                proposed=before
            row['parameters_after']=parameters(proposed)
            row['proposal_accepted']='validation_error' not in row
            candidate.write_text(proposed)
            # Every decision, including an unchanged proposal, receives a fresh DC check.
            state['measurement']=evaluate(runner,candidate)
            after=state['measurement']
            row.update(result_simulation_number=after['simulation_number'],result_measurements=after['metrics'],
                       result_dc_passed=after['dc_passed'],result_failed_dc_devices=after['dc_acceptance']['failed_devices'])
        finally:
            row['iteration_time']=time.perf_counter()-tick
            save(results/'history.json',history)
        print(f"Iteration {row['iteration']} ({phase}); DC={after['dc_passed']}; failed={after['dc_acceptance']['failed_devices']}; metrics={after['metrics']}",flush=True)


def run(baseline_only=False):
    target=json.loads((BASE/'specs/target.json').read_text())
    reference=(BASE/'reference/reference.spice').read_text()
    validate_candidate(reference,reference,target)
    limits=target['optimization']
    if not (type(limits['max_dc_iterations']) is int and type(limits['max_iterations']) is int
            and 1<=limits['max_dc_iterations']<=5 and limits['max_dc_iterations']<=limits['max_iterations']<=10):
        raise ValueError('Budgets require 1 <= DC <= 5 and DC <= total <= 10')
    results=BASE/'results';results.mkdir(exist_ok=True)
    if (results/'summary.json').exists():
        archive=results/'runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        archive.mkdir(parents=True)
        for p in results.iterdir():
            if p.is_file() and p.name!='run.lock':shutil.copy2(p,archive/p.name)
    save(results/'target.json',target)
    (results/'reference.spice').write_text(reference)
    candidate=BASE/'working/candidate.spice';candidate.parent.mkdir(exist_ok=True)
    candidate.write_text(reference)
    runner=NgspiceRunner(results,target);agent=SizingAgent(load_config())
    history=[];save(results/'history.json',history)
    state={'dc_iterations':0,'measurement':None}
    started=time.perf_counter();start_time=datetime.now(timezone.utc).isoformat()
    status='interrupted';error=None
    try:
        status=optimize(runner,agent,candidate,reference,target,results,history,state,baseline_only)
    except (Exception,KeyboardInterrupt) as exc:
        error=f'{type(exc).__name__}: {exc}';print(error,flush=True)
    finally:
        measurement=state['measurement'];calls=agent.client.calls
        save(results/'calls.json',calls)
        (results/'candidate.spice').write_text(candidate.read_text())
        summary=dict(status=status,error=error,iteration_count=len(history),dc_iteration_count=state['dc_iterations'],
            performance_iteration_count=len(history)-state['dc_iterations'],simulation_count=runner.count,
            design_backend='claude_cli' if os.environ.get('SIZING_BACKEND')=='claude' else 'local_qwen',model='sonnet' if os.environ.get('SIZING_BACKEND')=='claude' else load_config()['served_model'],
            workflow_completed=status in ('targets_passed','max_iterations_reached','dc_iteration_limit'),
            max_iterations=limits['max_iterations'],max_dc_iterations=limits['max_dc_iterations'],
            optimization_start_time=start_time,optimization_end_time=datetime.now(timezone.utc).isoformat(),
            total_optimization_time_seconds=time.perf_counter()-started,
            final_simulation_number=measurement['simulation_number'] if measurement else None,
            tokens={k:sum((c.get('usage') or {}).get(k,0) for c in calls) for k in ['prompt_tokens','completion_tokens','total_tokens']},
            token_usage_complete=all(c.get('usage') is not None for c in calls),qwen_call_count=len(calls))
        save(results/'summary.json',summary)
        if measurement:
            print('PDF:',generate(results),flush=True)
            print('中文 PDF:',generate(results,language='zh'),flush=True)
    return 1 if status=='interrupted' else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-only',action='store_true',help='DC baseline; AC only if DC passes; no Qwen')
    args=parser.parse_args()
    (BASE/'results').mkdir(exist_ok=True)
    with (BASE/'results/run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        raise SystemExit(run(args.baseline_only))
