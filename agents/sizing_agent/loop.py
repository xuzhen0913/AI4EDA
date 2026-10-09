"""One sizing run: DC repair first (<= max_dc_iterations), then performance (<= max_iterations decisions in total)."""
import time
from agents.sizing_agent.agent import apply_changes
from simulator.ngspice_runner import save


def evaluate(runner, candidate):
    dc = runner.run(candidate, mode='dc')
    if not dc['dc_passed']:
        return dc
    full = runner.run(candidate, mode='full')
    full['preceding_dc_simulation_number'] = dc['simulation_number']
    return full


def brief(measurement):
    return dict(simulation_number=measurement['simulation_number'], dc_passed=measurement['dc_passed'],
                failed_dc_devices=measurement['dc_acceptance']['failed_devices'], metrics=measurement['metrics'])


def optimize(runner, agent, candidate, reference, target, results, history, state, baseline_only=False, feedback=None):
    """`candidate` is a file edited in place; `history` and `state` are filled for the caller."""
    state['measurement'] = evaluate(runner, candidate)
    if baseline_only:
        return 'baseline_only'
    limits = target['optimization']
    while True:
        measurement = state['measurement']
        if measurement['all_targets_passed']:
            return 'targets_passed'
        if not measurement['dc_passed'] and state['dc_iterations'] >= limits['max_dc_iterations']:
            return 'dc_iteration_limit'
        if len(history) >= limits['max_iterations']:
            return 'max_iterations_reached'
        phase = 'dc_repair' if not measurement['dc_passed'] else 'performance'
        tick, before = time.perf_counter(), candidate.read_text()
        reply = agent.run(target, before, measurement, history, feedback=feedback)
        if phase == 'dc_repair':
            state['dc_iterations'] += 1
        row = dict(iteration=len(history)+1, phase=phase, analysis=reply['analysis'], changes=reply['changes'],
                   token_usage=agent.client.calls[-1]['usage'])
        if not history:
            row['before'] = brief(measurement)  # the starting point; later rows start from the previous result
        history.append(row)
        try:
            try:
                proposed = apply_changes(reference, before, target, reply['changes'])
            except ValueError as exc:
                row['validation_error'] = str(exc)
                proposed = before
            row['accepted'] = 'validation_error' not in row
            candidate.write_text(proposed)
            # Every decision, including an unchanged proposal, receives a fresh DC check.
            state['measurement'] = evaluate(runner, candidate)
            row['result'] = brief(state['measurement'])
        finally:
            row['seconds'] = time.perf_counter()-tick
            save(results/'history.json', history)
        print(f"  Iteration {row['iteration']} ({phase}); DC={row['result']['dc_passed']}; "
              f"failed={row['result']['failed_dc_devices']}; metrics={row['result']['metrics']}", flush=True)
