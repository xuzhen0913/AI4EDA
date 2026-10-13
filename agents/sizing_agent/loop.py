"""One sizing run: DC repair first (<= max_dc_iterations), then performance (<= max_iterations decisions in total).

The model proposes single steps; everything the toolchain can settle without it is done around it (see optimize)."""
import json
import random
import time
from types import SimpleNamespace
from agents.sizing_agent.agent import apply_changes
from analog_agents.evidence import outcome
from analog_agents.search import (DC_FALLBACK_PARAMS, JUMP_FRACTIONS, JUMP_TRIES, MAX_CHANGES, MAX_CHANGES_DC,
                                  MAX_CONSECUTIVE_REVERTS, MAX_FREE_REFUSALS, MAX_JUMPS, MAX_MEMORY_STEPS, MAX_RETRIES, charged,
                                  circuit_is_off, clamp, dc_moves, direction, effective, fill_old, jump_changes, key_of_params,
                                  move_text, open_moves, point_key, proposal, shortfall, step_change, step_effect, to_unit,
                                  tunable_point)
from analog_agents.spice import number, parameters
from simulator.ngspice_runner import save


def evaluate(runner, candidate):
    dc = runner.run(candidate, mode='dc')
    if not dc['dc_passed']:
        return dc
    full = runner.run(candidate, mode='full')
    full['preceding_dc_simulation_number'] = dc['simulation_number']
    return full


def brief(measurement):
    item = dict(simulation_number=measurement['simulation_number'], dc_passed=measurement['dc_passed'],
                failed_dc_devices=measurement['dc_acceptance']['failed_devices'], metrics=measurement['metrics'])
    if (measurement['dc_acceptance'].get('loop') or {}).get('passed') is False:
        item['loop_regulated'] = False  # DC failed although every device may be fine: the loop does not hold out at VCM
    return item


def new_run(target, names, memory_points, seed, start_text):
    """The state the helpers of one sizing run share. `memory_points`: [(status, metrics, full parameters)] remembered
    from earlier runs: they close revisits (known) and the ones that met the current targets are tried whole."""
    known = {key_of_params(p, names): dict(dc_passed=s != 'D', failed_dc_devices=[], metrics=m or {})
             for s, m, p in memory_points}
    start, bounds = parameters(start_text), target['optimization']['parameter_bounds']
    def distance(p):
        return sum(abs(to_unit(bounds[n], number(p[n])) - to_unit(bounds[n], number(start[n]))) for n in names)
    passing = sorted(((distance(p), p) for s, m, p in memory_points if s != 'D'), key=lambda t: t[0])
    good = [p for s, m, p in memory_points if s != 'D' and m and shortfall(target['targets'], m) == 0]
    return SimpleNamespace(target=target, names=names, visited={}, known=known, worse=set(), rng=random.Random(seed),
                           free_left=MAX_FREE_REFUSALS, jumps_left=MAX_JUMPS, memory_left=MAX_MEMORY_STEPS,
                           dc_memory_left=MAX_MEMORY_STEPS, stall=0,
                           memory_candidates=sorted(good, key=distance),     # met the current targets: tried once DC passes
                           dc_candidates=[p for _, p in passing])            # passed DC under the same bench: tried while DC fails


def seen_before(run, proposed):
    key = point_key(proposed, run.names)
    return run.visited.get(key) or run.known.get(key)


def prepare(run, reply, before, reference, measurement):
    """Turn a reply into (proposed text, changes as applied, notes) or raise ValueError saying what is wrong with it."""
    params = parameters(before)
    changes, notes = clamp(run.target['optimization']['parameter_bounds'], fill_old(params, reply['changes']))
    limit = MAX_CHANGES if measurement['dc_passed'] else MAX_CHANGES_DC
    if len(changes) > limit:
        raise ValueError(f'at most {limit} change{"s" if limit > 1 else ""} per decision, got {len(changes)}')
    if not changes:
        return before, [], notes
    real = effective(changes)
    if not real:
        raise ValueError('the new value equals the current value, so nothing would change')
    levers = dc_moves(run.target.get('levers'))
    if levers and circuit_is_off(measurement, run.target['dc_acceptance']['devices']) \
            and not {c['parameter'] for c in real} & {n for n, _, _ in levers}:
        raise ValueError('no device conducts, so sizes cannot change anything: move the bias levers first ('
                         + move_text(levers, 6) + ')')
    for c in real:
        if (c['parameter'], direction(c)) in run.worse:
            raise ValueError(f"{'raising' if direction(c) > 0 else 'lowering'} {c['parameter']} already made the result "
                             'worse in this search (see `history`, column vs_previous); do not continue in that direction')
    proposed = apply_changes(reference, before, run.target, real)
    seen = seen_before(run, proposed)
    if seen:
        raise ValueError('this exact point was already simulated: '+json.dumps(outcome(seen), separators=(',', ':')))
    return proposed, real, notes


def next_moves(run, measurement, history):
    return open_moves(run.target.get('levers'), run.target['targets'], measurement['metrics'], history, run.worse, run.names,
                      dc_failed=not measurement['dc_passed'])


def ask_until_usable(run, agent, before, measurement, history, reference, feedback):
    """Ask; a refused proposal comes back with the reason and the moves still open, and the model answers again. It stops
    asking as soon as the model repeats a refused proposal (it will not change its mind) or after MAX_RETRIES.
    Returns (reply, proposed, changes, notes, refusals, usage, error); `refusals` includes the last one when error is set."""
    refusals, usage = [], dict(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    for attempt in range(MAX_RETRIES+1):
        reply = agent.run(run.target, before, measurement, history, feedback=feedback, rejections=refusals or None)
        for k, v in (agent.client.calls[-1]['usage'] or {}).items():
            usage[k] = usage.get(k, 0)+v
        try:
            return reply, *prepare(run, reply, before, reference, measurement), refusals, usage, None
        except ValueError as exc:
            repeated = any(r['proposal'] == proposal(reply['changes']) for r in refusals)
            refusals.append(dict(proposal=proposal(reply['changes']), error=str(exc),
                                 note='not applied; the current values are unchanged',
                                 try_instead=move_text(next_moves(run, measurement, history), 6) or 'any parameter not moved yet'))
            error = str(exc)
            if repeated:
                break
    return reply, before, reply['changes'], [], refusals, usage, error


def fallback(run, before, measurement, history, reference):
    """When the model has no usable proposal: step the first open lever(s) of the missed metrics (levers are declared by
    the reference; without them, a parameter never moved). While DC fails only the reference's DC levers are used, the
    first DC_FALLBACK_PARAMS of them together (coupled biases). Returns (proposed text, changes) or None."""
    bounds, params = run.target['optimization']['parameter_bounds'], parameters(before)
    repair = not measurement['dc_passed']
    if repair and not dc_moves(run.target.get('levers')):
        return None
    changes = []
    for name, d, _ in next_moves(run, measurement, history):
        change = step_change(bounds, params, name, d)
        if not change or any(c['parameter'] == name for c in changes):
            continue
        if not repair:
            try:
                proposed = apply_changes(reference, before, run.target, [change])
            except ValueError:
                continue
            if not seen_before(run, proposed):
                return proposed, [change]
            continue
        changes.append(change)
        if len(changes) == DC_FALLBACK_PARAMS:
            break
    if repair and changes:
        try:
            proposed = apply_changes(reference, before, run.target, changes)
        except ValueError:
            return None
        if not seen_before(run, proposed):
            return proposed, changes
    return None


def memory_step(run, before, reference, repair=False):
    """The nearest remembered design, as ONE decision (all differing parameters at once): while DC fails, one that passed DC
    before; otherwise one that met the current targets. Each is tried at most once per run.
    Returns (proposed text, changes) or None."""
    params = parameters(before)
    pool = run.dc_candidates if repair else run.memory_candidates
    while pool:
        design = pool.pop(0)
        changes = [dict(parameter=n, old_value=params[n], new_value=design[n],
                        reason='nearest remembered design (toolchain)')
                   for n in run.names if not abs(number(design[n]) - number(params[n])) <= 1e-9 * abs(number(params[n]))]
        if not changes:
            continue
        try:
            proposed = apply_changes(reference, before, run.target, changes)
        except ValueError:
            continue
        if not run.visited.get(point_key(proposed, run.names)):
            return proposed, changes
    return None


def jump(run, runner, candidate, before, reference):
    """A large move to another region, found without the model: random jumps, each screened by a DC-only simulation.
    Returns (proposed text, changes) or None when no DC-valid jump was found."""
    bounds, params = run.target['optimization']['parameter_bounds'], parameters(before)
    for fraction in JUMP_FRACTIONS:
        for _ in range(JUMP_TRIES):
            changes = effective(jump_changes(run.rng, bounds, params, fraction))
            if not changes:
                continue
            try:
                proposed = apply_changes(reference, before, run.target, changes)
            except ValueError:
                continue
            if seen_before(run, proposed):
                continue
            candidate.write_text(proposed)
            if runner.run(candidate, mode='dc')['dc_passed']:
                return proposed, changes
    candidate.write_text(before)
    return None


def optimize(runner, agent, candidate, reference, target, results, history, state, baseline_only=False, feedback=None,
             memory_points=(), seed=0):
    """`candidate` is a file edited in place; `history` and `state` are filled for the caller.

    The search is a greedy climb: a step that does not improve the total miss of the targets is undone, so the model
    always edits the best point so far. Around the model, without it:
    - remembered designs (memory_points) that met the current targets are tried whole, nearest first (phase `memory`);
    - a refused proposal is re-asked with the moves still open, but not after the model repeats itself; when the model
      has no usable proposal the toolchain steps the next open lever itself (`fallback`), else the refusal is free (a
      few times per run);
    - points already simulated (here or remembered) and directions that already made things worse are refused;
    - a step that makes things worse, or breaks a passing DC, is undone;
    - after MAX_CONSECUTIVE_REVERTS undone steps in a row the toolchain jumps to another region (`explore`);
    - the best point found is kept in state['best'] and handed over at the end."""
    names = list(target['optimization']['allowed_parameters'])
    run, state['best'] = new_run(target, names, memory_points, seed, candidate.read_text()), None
    state['measurement'] = evaluate(runner, candidate)
    start_text = candidate.read_text()
    run.visited[point_key(start_text, names)] = brief(state['measurement'])
    note_best(state, target, start_text, state['measurement'])
    if baseline_only:
        return 'baseline_only'
    limits = target['optimization']
    while True:
        measurement = state['measurement']
        if measurement['all_targets_passed']:
            return 'targets_passed'
        if not measurement['dc_passed'] and state['dc_iterations'] >= limits['max_dc_iterations']:
            return settle(candidate, state, 'dc_iteration_limit')
        if len(charged(history)) >= limits['max_iterations']:
            return settle(candidate, state, 'max_iterations_reached')
        repair = not measurement['dc_passed']
        phase = 'dc_repair' if repair else 'performance'
        tick, before = time.perf_counter(), candidate.read_text()
        silent = dict(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        moved, fell_back, refusals = None, False, []
        if repair and run.dc_memory_left > 0 and (moved := memory_step(run, before, reference, repair=True)):
            run.dc_memory_left -= 1
            phase, why = 'memory', 'nearest remembered design that passed DC (toolchain)'
        elif phase == 'performance' and run.memory_left > 0 and (moved := memory_step(run, before, reference)):
            run.memory_left -= 1
            phase, why = 'memory', 'nearest remembered design that met the current targets (toolchain)'
        elif phase == 'performance' and run.stall >= MAX_CONSECUTIVE_REVERTS and run.jumps_left > 0:
            run.jumps_left, run.stall = run.jumps_left-1, 0
            moved = jump(run, runner, candidate, before, reference)
            phase, why = 'explore', f'{MAX_CONSECUTIVE_REVERTS} steps in a row did not improve: large jump (toolchain)'
            if not moved:
                moved = (before, [])
        if moved:
            reply = dict(analysis=dict(simulation_valid=True, dc_op_valid=True, main_problem=why), changes=[])
            proposed, changes = moved
            notes, usage, error = [], silent, (None if changes else 'no DC-valid large jump found')
        else:
            reply, proposed, changes, notes, refusals, usage, error = ask_until_usable(
                run, agent, before, measurement, history, reference, feedback)
            if error and (step := fallback(run, before, measurement, history, reference)):
                (proposed, changes), error, fell_back = step, None, True
        free = error is not None and phase != 'explore' and run.free_left > 0   # a fully refused decision costs no budget
        if free:
            run.free_left -= 1
        if repair and not free:
            state['dc_iterations'] += 1
        row = dict(iteration=len(history)+1, phase=phase, analysis=reply['analysis'], changes=changes, token_usage=usage)
        earlier = refusals[:-1] if error else refusals
        if earlier:
            row['rejected_attempts'] = earlier
        if notes:
            row['clamped'] = notes
        if free:
            row['free'] = True
        if fell_back:
            row['fallback'] = True
        if repair and phase == 'memory':
            row['repair'] = True   # a remembered design tried while DC fails: it counts against the DC-repair budget
        if not history:
            row['before'] = dict(brief(measurement), point=tunable_point(before, names))  # the starting point
        history.append(row)
        try:
            if error:
                row['changes'] = fill_old(parameters(before), reply['changes'])
                row['validation_error'] = error
            row['accepted'] = error is None
            if error is not None:
                row['result'] = brief(measurement)   # nothing changed: there is nothing new to simulate
            else:
                candidate.write_text(proposed)
                # An unchanged proposal (no change at all) still receives a fresh DC check.
                state['measurement'] = evaluate(runner, candidate)
                row['result'] = brief(state['measurement'])
                row['point'] = tunable_point(proposed, names)
                run.visited[point_key(proposed, names)] = row['result']
                follow_up(run, state, row, changes, proposed, before, measurement, phase, candidate)
        finally:
            row['seconds'] = time.perf_counter()-tick
            save(results/'history.json', history)
        print(f"  Iteration {row['iteration']} ({phase}{', fallback' if fell_back else ''}); DC={row['result']['dc_passed']}; "
              f"failed={row['result']['failed_dc_devices']}; metrics={row['result']['metrics']}"
              + (f"; {row['effect']}" if row.get('effect') else '') + ('; reverted' if row.get('rolled_back') else '')
              + ('; refused (free)' if free else '; refused' if error else ''), flush=True)


def follow_up(run, state, row, changes, proposed, before, measurement, phase, candidate):
    """What the simulation of a step means: its effect, the best point, forbidden directions, a rollback, the stall count."""
    new, targets = state['measurement'], run.target['targets']
    repair = not measurement['dc_passed']
    if repair and phase == 'memory':   # a remembered design while DC fails: kept only if it passes DC
        effect = 'better' if new['dc_passed'] else 'worse (DC fail)'
    else:
        effect = step_effect(shortfall(targets, measurement['metrics']), shortfall(targets, new['metrics'])) \
            if phase in ('performance', 'memory') else ''
    if phase == 'explore':
        effect = 'jump'   # a deliberate move to a new region: kept even though it is probably worse than the best point
    if changes and effect:
        row['effect'] = effect
    if new['dc_passed']:
        note_best(state, run.target, proposed, new)
    if effect in ('better', 'jump'):
        run.worse.clear()   # new ground: directions that failed before are worth a second look
        run.stall = 0
    elif phase == 'performance' and len(changes) == 1 and effect.startswith('worse'):
        run.worse.add((changes[0]['parameter'], direction(changes[0])))
    if phase in ('performance', 'memory') and proposed != before and effect.startswith('worse'):
        row['rolled_back'] = True  # a step that made things worse (or broke a passing DC) is undone; it stays in `visited`
        candidate.write_text(before)
        state['measurement'] = measurement
        if phase == 'performance':
            run.stall += 1


def settle(candidate, state, status):
    """A run that ends without passing hands over its best point, not wherever the last step happened to land."""
    best = state['best']
    if best and best['simulation_number'] != state['measurement']['simulation_number']:
        candidate.write_text(best['text'])
        state['measurement'] = best['measurement']
    return status


def note_best(state, target, text, measurement):
    """Keep the DC-passing point with the smallest total miss of the targets (None = not fully measured)."""
    miss = shortfall(target['targets'], measurement['metrics'])
    if miss is not None and (state['best'] is None or miss < state['best']['shortfall']):
        state['best'] = dict(text=text, shortfall=miss, simulation_number=measurement['simulation_number'],
                             measurement=measurement)
        return True
    return False
