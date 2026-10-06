"""Fixed-topology SKY130/Qwen optimization. Run using scripts/run_demo.sh."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import time
from analog_agents.config import load_config, ROOT
from agents.sizing_agent.agent import SizingAgent, apply_changes, parameters, validate_candidate
from simulator.ngspice_runner import NgspiceRunner, save
from simulator.report_generator import generate

BASE=ROOT/'circuits/two_stage_opamp'

def run(baseline_only=False):
    target=json.loads((BASE/'specs/target.json').read_text())
    reference=(BASE/'reference/reference.spice').read_text()
    validate_candidate(reference,reference,target)
    results=BASE/'results';results.mkdir(exist_ok=True)
    # Preserve previous complete/partial experiments before updating current evidence.
    if (results/'summary.json').exists():
        archive=results/'runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        archive.mkdir(parents=True)
        for p in results.iterdir():
            if p.is_file() and p.name!='run.lock':shutil.copy2(p,archive/p.name)
    save(results/'target.json',target)
    (results/'reference.spice').write_text(reference)
    candidate=BASE/'working/candidate.spice';candidate.parent.mkdir(exist_ok=True)
    candidate.write_text(reference)
    runner=NgspiceRunner(results,target)
    agent=SizingAgent(load_config())
    history=[];save(results/'history.json',history)
    started=time.perf_counter();start_time=datetime.now(timezone.utc).isoformat()
    status='running';error=None;measurement=None
    try:
        measurement=runner.run(candidate)
        print('Baseline:',json.dumps(measurement['metrics']),flush=True)
        if not measurement['simulation_valid']:
            raise ValueError('Baseline testbench is invalid; inspect full log before optimization')
        if baseline_only:
            status='baseline_only'
        else:
            for iteration in range(1,target['optimization']['max_iterations']+1):
                tick=time.perf_counter();before=candidate.read_text()
                reply=agent.run(target,reference,before,(results/'current.log').read_text(),measurement,history)
                row=dict(iteration=iteration,simulation_number=measurement['simulation_number'],
                    parameters_before=parameters(before),measurements=measurement['metrics'],
                    simulation_status={k:measurement[k] for k in ['simulation_valid','return_code','warnings','errors']},qwen_analysis=reply['analysis'],
                    parameter_changes=reply['changes'],parameters_after=parameters(before),
                    qwen_token_usage=agent.client.calls[-1]['usage'])
                history.append(row)
                try:
                    proposed=apply_changes(reference,before,target,reply['changes'])
                    row['parameters_after']=parameters(proposed)
                except ValueError as exc:
                    row['validation_error']=str(exc)
                    raise
                finally:
                    row['iteration_time']=time.perf_counter()-tick
                    save(results/'history.json',history)
                print(f"Iteration {iteration}: {reply['analysis']['main_problem']}; changes={reply['changes']}",flush=True)
                # Even a numerically passing simulation is reviewed by Qwen before success.
                if measurement['all_targets_passed'] and reply['analysis']['simulation_valid'] and reply['analysis']['dc_op_valid']:
                    status='targets_passed';break
                if reply['changes']:
                    candidate.write_text(proposed)
                    measurement=runner.run(candidate)
                    row['result_simulation_number']=measurement['simulation_number']
                    row['result_measurements']=measurement['metrics']
                    row['iteration_time']=time.perf_counter()-tick
                    save(results/'history.json',history)
                # No-change decisions still count, with latest full log retained.
            else:status='max_iterations_reached'
    except Exception as exc:
        status='interrupted';error=f'{type(exc).__name__}: {exc}'
        print(error,flush=True)
    finally:
        elapsed=time.perf_counter()-started
        calls=agent.client.calls
        save(results/'calls.json',calls)
        (results/'candidate.spice').write_text(candidate.read_text())
        summary=dict(status=status,error=error,iteration_count=len(history),simulation_count=runner.count,
            design_backend='local_qwen', model=load_config()['served_model'],
            workflow_completed=status in ('targets_passed','max_iterations_reached'),
            max_iterations=target['optimization']['max_iterations'],
            optimization_start_time=start_time,optimization_end_time=datetime.now(timezone.utc).isoformat(),
            total_optimization_time_seconds=elapsed,
            final_simulation_number=measurement['simulation_number'] if measurement else None,
            tokens={k:sum((c.get('usage') or {}).get(k,0) for c in calls) for k in ['prompt_tokens','completion_tokens','total_tokens']},
            token_usage_complete=all(c.get('usage') is not None for c in calls),
            qwen_call_count=len(calls))
        save(results/'summary.json',summary)
        if measurement:print('PDF:',generate(results),flush=True)
    return 1 if status=='interrupted' else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-only',action='store_true',help='Real ngspice baseline and PDF; no Qwen call')
    args=parser.parse_args()
    with (BASE/'results/run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        raise SystemExit(run(args.baseline_only))
