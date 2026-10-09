"""Three-agent op-amp workflow: topology selection -> sizing -> performance review (<= 3 rounds).

Round n: (topology agent, when the reviewer blamed the topology or n == 1) -> sizing agent
(DC repair <= max_dc_iterations, total <= max_iterations decisions, per sizing run) -> review agent.
The review agent passes the design, or returns advice to the agent at fault and the next round starts.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import shutil
import time
from agents.review_agent.agent import ReviewAgent, build_evidence, spec_check
from agents.sizing_agent.agent import SizingAgent, check_library, validate_candidate
from agents.sizing_agent.loop import optimize
from agents.topology_agent.agent import TopologyAgent
from analog_agents.config import ROOT
from analog_agents.factory import backend, new_client
from analog_agents.reference import design_target, load_references
from simulator.ngspice_runner import NgspiceRunner, save
from simulator.report_generator import generate

BASE = ROOT/'circuits/opamp'
KEEP = ('run.lock', 'runs')
BACKENDS = {'claude': 'claude_cli', 'codex': 'codex_cli', 'qwen': 'local_qwen'}


def tokens(calls):
    return {k: sum((c.get('usage') or {}).get(k, 0) for c in calls)
            for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}


def check_budgets(specs):
    b = specs['budgets']
    if not (all(type(b[k]) is int for k in ('max_dc_iterations', 'max_iterations', 'max_rounds'))
            and 1 <= b['max_dc_iterations'] <= 5 and b['max_dc_iterations'] <= b['max_iterations'] <= 10):
        raise ValueError('Sizing budgets require 1 <= DC <= 5 and DC <= total <= 10')
    if not 1 <= b['max_rounds'] <= 3:
        raise ValueError('Workflow budget requires 1 <= max_rounds <= 3')


def archive_previous(results):
    """The previous run is moved (not copied) into results/runs/<timestamp>/."""
    if not (results/'summary.json').exists():
        return
    destination = results/'runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    destination.mkdir(parents=True)
    for path in results.iterdir():
        if path.name not in KEEP:
            shutil.move(str(path), destination/path.name)


def round_digest(entry):
    """Compact record of an earlier round, shown to later agents."""
    return {k: entry.get(k) for k in ('round', 'reference', 'sizing_status', 'metrics', 'dc_passed',
                                      'failed_dc_devices', 'failed_specs', 'verdict', 'diagnosis', 'revision_advice')}


def sizing_run(n, rdir, specs, reference, target, agent, start_text, feedback, baseline_only):
    """One complete sizing run (or just the baseline simulation) on the selected reference."""
    candidate = rdir/'candidate.spice'
    candidate.write_text(start_text)
    validate_candidate(reference.text, start_text, target)
    runner = NgspiceRunner(rdir, target)
    history, state = [], {'dc_iterations': 0, 'measurement': None}
    save(rdir/'history.json', history)
    started = time.perf_counter()
    status, error = 'interrupted', None
    try:
        status = optimize(runner, agent, candidate, reference.text, target, rdir, history, state,
                          baseline_only=baseline_only, feedback=feedback)
    except (Exception, KeyboardInterrupt) as exc:
        error = f'{type(exc).__name__}: {exc}'
        print(error, flush=True)
    finally:
        calls = agent.client.calls if agent else []
        save(rdir/'sizing_calls.json', calls)
        measurement = state['measurement']
        limits = target['optimization']
        summary = dict(status=status, error=error, round=n, reference=reference.id,
            initial_parameters={k: reference.initial[k] for k in reference.bounds},
            iteration_count=len(history), dc_iteration_count=state['dc_iterations'],
            performance_iteration_count=len(history)-state['dc_iterations'], simulation_count=runner.count,
            max_iterations=limits['max_iterations'], max_dc_iterations=limits['max_dc_iterations'],
            total_optimization_time_seconds=time.perf_counter()-started,
            final_simulation_number=measurement['simulation_number'] if measurement else None,
            tokens=tokens(calls), token_usage_complete=all(c.get('usage') is not None for c in calls),
            call_count=len(calls))
        save(rdir/'summary.json', summary)
    return summary, history, measurement


def run(baseline_only=False, only_reference=None):
    specs = json.loads((BASE/'specs/target.json').read_text())
    check_budgets(specs)
    references = load_references(BASE/'reference')
    check_library(specs, references)
    if baseline_only and only_reference not in references:
        raise ValueError('--baseline-only needs --reference <id>; ids: '+', '.join(references))
    selection = None if baseline_only else backend()
    max_rounds = 1 if baseline_only else specs['budgets']['max_rounds']
    results = BASE/'results'
    results.mkdir(exist_ok=True)
    archive_previous(results)
    save(results/'specs.json', specs)

    clients = {} if baseline_only else {name: new_client(selection) for name in ('topology', 'sizing', 'review')}
    topology_agent, sizing_agent, review_agent = (None,)*3 if baseline_only else (
        TopologyAgent(clients['topology']), SizingAgent(clients['sizing']), ReviewAgent(clients['review']))

    rounds, excluded = [], []
    reference, last_review, last_candidate = None, None, None
    status, error = 'interrupted', None
    started = time.perf_counter()
    start_time = datetime.now(timezone.utc).isoformat()
    try:
        for n in range(1, max_rounds+1):
            rdir = results/f'round_{n:02d}'
            rdir.mkdir()
            print(f'=== Round {n}/{max_rounds} ===', flush=True)
            entry = dict(round=n, topology_agent_ran=False, sizing_feedback_used=False)
            if baseline_only:
                reference = references[only_reference]
            elif n == 1 or last_review['verdict'] == 'fail_topology':
                offered = [i for i in references if i not in excluded]
                if offered:
                    choice = topology_agent.select(specs, references, excluded, [round_digest(r) for r in rounds] or None,
                                                   last_review if n > 1 else None)
                    reference = references[choice['selected_reference']]
                    entry['topology_agent_ran'] = True
                    save(rdir/'topology_selection.json', dict(offered=offered, excluded=excluded, **choice))
                    save(rdir/'topology_calls.json', clients['topology'].calls)
                    print('  topology:', reference.id, flush=True)
                else:  # nothing left to offer: keep sizing the last structure
                    last_review = dict(last_review, verdict='fail_sizing')
            target = design_target(specs, reference)
            feedback = None
            start_text = reference.text
            if n > 1 and last_review['verdict'] == 'fail_sizing':
                feedback = {k: last_review[k] for k in ('diagnosis', 'revision_advice')}
                entry['sizing_feedback_used'] = True
                if not last_review['restart_sizing_from_reference']:
                    start_text = last_candidate
            summary, history, measurement = sizing_run(n, rdir, specs, reference, target, sizing_agent, start_text,
                                                       feedback, baseline_only)
            candidate_text = (rdir/'candidate.spice').read_text()
            last_candidate = candidate_text
            entry.update(reference=reference.id, sizing_status=summary['status'], decisions=summary['iteration_count'],
                         dc_decisions=summary['dc_iteration_count'], simulations=summary['simulation_count'])
            if summary['error'] or measurement is None:
                error = summary['error'] or 'sizing produced no measurement'
                rounds.append(entry)
                break
            checks = spec_check(specs['targets'], measurement['metrics'])
            entry.update(metrics=measurement['metrics'], dc_passed=measurement['dc_passed'],
                         failed_dc_devices=measurement['dc_acceptance']['failed_devices'],
                         failed_specs=[k for k, v in checks.items() if v['passed'] is not True],
                         final_simulation_number=summary['final_simulation_number'])
            rounds.append(entry)
            if baseline_only:
                status = 'baseline_only'
                break
            review = review_agent.review(build_evidence(n, max_rounds, specs, reference, target, summary, history,
                                                        measurement, candidate_text, [round_digest(r) for r in rounds[:-1]]))
            save(rdir/'review.json', review)
            save(rdir/'review_calls.json', clients['review'].calls)
            entry.update(verdict=review['verdict'], diagnosis=review['diagnosis'],
                         revision_advice=review['revision_advice'])
            last_review = review
            print(f"  review: {review['verdict']}", flush=True)
            if review['verdict'] == 'pass':
                status = 'targets_passed'
                break
            if review['verdict'] == 'fail_topology':
                excluded.append(reference.id)
            status = 'max_rounds_reached'
    except (Exception, KeyboardInterrupt) as exc:
        error = f'{type(exc).__name__}: {exc}'
        print(error, flush=True)
        status = 'interrupted'
    finally:
        calls = {name: c.calls for name, c in clients.items()}
        every_call = [c for group in calls.values() for c in group]
        keep = ('round', 'reference', 'topology_agent_ran', 'sizing_feedback_used', 'sizing_status', 'decisions',
                'dc_decisions', 'simulations', 'metrics', 'dc_passed', 'failed_dc_devices', 'failed_specs',
                'final_simulation_number', 'verdict')
        summary = dict(status=status, error=error, rounds_run=len(rounds), max_rounds=max_rounds,
            workflow_completed=status in ('targets_passed', 'max_rounds_reached', 'baseline_only'),
            final_reference=rounds[-1].get('reference') if rounds else None,
            final_verdict=rounds[-1].get('verdict') if rounds else None,
            final_candidate=f'round_{len(rounds):02d}/candidate.spice' if rounds else None,
            rounds=[{k: r[k] for k in keep if k in r} for r in rounds],
            design_backend=BACKENDS[selection.kind] if selection else None,
            model=(selection.model_id or 'qwen3-8b-local') if selection else None,
            tokens_by_agent={name: tokens(c) for name, c in calls.items()}, tokens=tokens(every_call),
            token_usage_complete=all(c.get('usage') is not None for c in every_call),
            calls_by_agent={name: len(c) for name, c in calls.items()},
            simulation_count=sum(r.get('simulations', 0) for r in rounds), start_time=start_time,
            end_time=datetime.now(timezone.utc).isoformat(), total_time_seconds=time.perf_counter()-started)
        save(results/'summary.json', summary)
        if rounds and rounds[-1].get('metrics') is not None:
            try:
                print('PDF:', generate(results), flush=True)
                print('中文 PDF:', generate(results, language='zh'), flush=True)
            except Exception as exc:  # the evidence on disk stays valid even if rendering fails
                print('Report generation failed:', f'{type(exc).__name__}: {exc}', flush=True)
    return 1 if status == 'interrupted' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-only', action='store_true', help='simulate one untouched reference; no model')
    parser.add_argument('--reference', help='reference id for --baseline-only')
    args = parser.parse_args()
    (BASE/'results').mkdir(exist_ok=True)
    with (BASE/'results/run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run(args.baseline_only, args.reference))
