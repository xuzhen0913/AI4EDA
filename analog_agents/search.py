"""Deterministic scaffolding around the sizing model's decisions: what Python can settle is not left to the model.

Bookkeeping (old values, clamping to the tune range), the set of already simulated points, the progress score used to
keep the best point, the compact history table the model reads, and the revision advice given after a failed run.
Nothing here knows a circuit, a process or a metric by name.
"""
import math
from analog_agents.evidence import outcome, sig
from analog_agents.spice import number, parameters

MAX_CHANGES = 1   # one lever per decision: every measured effect then has exactly one cause
MAX_CHANGES_DC = 4  # DC repair: bias voltages are coupled (one alone changes nothing), so several may move together
DC_FALLBACK_PARAMS = 2  # the toolchain's own DC-repair step moves this many open DC levers at once
MAX_RETRIES = 2   # re-asks inside one decision after an unusable proposal; they do not use up the decision budget
MAX_FREE_REFUSALS = 3  # per run: a decision whose every attempt was refused costs no budget, this many times
MAX_CONSECUTIVE_REVERTS = 3   # this many undone steps in a row: stop climbing here and jump to another region
MAX_JUMPS = 2                 # jumps per sizing run
MAX_MEMORY_STEPS = 2          # remembered designs that met the current targets and are tried (whole) per sizing run
STEP_FACTOR = 1.5             # a toolchain step: x1.5 (/1.5) on wide ranges, +-1 on integers,
STEP_SHARE = 0.2              # +-20 % of the tune range on narrow ones
JUMP_PARAMETERS = 2           # a jump moves up to this many parameters at once ...
JUMP_FRACTIONS = (0.35, 0.25, 0.15)  # ... each by at least this fraction of its tune range (tried in this order)
JUMP_TRIES = 4                # random jumps per fraction; each is screened by a DC-only simulation


def text_number(x):
    return format(x, '.6g')


def tunable_point(text, names):
    params = parameters(text)
    return {n: params[n] for n in names}


def key_of_params(params, names):
    """Numeric identity of a parameter set (formatting such as '1p' vs '1.0p' does not matter)."""
    return tuple(float(text_number(number(params[n]))) for n in names)


def point_key(text, names):
    return key_of_params(parameters(text), names)


def fill_old(params, changes):
    """The model names only the new value; the old one is whatever the candidate holds now."""
    return [dict(c, old_value=params[c['parameter']]) if c.get('parameter') in params else dict(c) for c in changes]


def clamp(bounds, changes):
    """Out-of-range values are moved onto the tune range (integers rounded) instead of being rejected."""
    result, notes = [], []
    for change in changes:
        b = bounds.get(change.get('parameter'))
        try:
            x = number(change['new_value'])
        except (KeyError, ValueError):
            result.append(change)
            continue
        if b:
            y = min(max(x, b['min']), b['max'])
            if b['integer']:
                y = float(min(max(round(y), math.ceil(b['min'])), math.floor(b['max'])))
            if y != x:
                notes.append(f"{change['parameter']}: {change['new_value']} -> {text_number(y)} (tune range "
                             f"{text_number(b['min'])}..{text_number(b['max'])}{', integer' if b['integer'] else ''})")
                change = dict(change, new_value=text_number(y))
        result.append(change)
    return result, notes


def _log_scale(b):
    return not b['integer'] and b['min'] > 0 and b['max'] / b['min'] >= 10


def to_unit(b, x):
    """Position of a value inside its tune range, 0..1 (logarithmic for ranges that span a decade or more)."""
    lo, hi = (math.log(b['min']), math.log(b['max'])) if _log_scale(b) else (b['min'], b['max'])
    return ((math.log(x) if _log_scale(b) else x) - lo) / (hi - lo)


def from_unit(b, u):
    lo, hi = (math.log(b['min']), math.log(b['max'])) if _log_scale(b) else (b['min'], b['max'])
    x = lo + u * (hi - lo)
    x = math.exp(x) if _log_scale(b) else x
    return float(min(max(round(x), math.ceil(b['min'])), math.floor(b['max']))) if b['integer'] else x


def jump_changes(rng, bounds, params, fraction):
    """One large move to another region: up to JUMP_PARAMETERS parameters, each at least `fraction` of its range away."""
    changes = []
    for name in rng.sample(list(bounds), min(JUMP_PARAMETERS, len(bounds))):
        b, here = bounds[name], to_unit(bounds[name], number(params[name]))
        for _ in range(50):
            u = rng.random()
            if abs(u - here) >= fraction:
                changes.append(dict(parameter=name, old_value=params[name], new_value=text_number(from_unit(b, u)),
                                    reason=f'large jump to a new region (toolchain, >= {fraction:.0%} of the tune range)'))
                break
    return changes


def miss_by_metric(targets, metrics):
    """{metric: (relative miss, +1 if it must be raised / -1 if lowered)} for the targets that are missed and measured."""
    out = {}
    for name, limits in targets.items():
        value = metrics.get(name)
        if value is None or not math.isfinite(value):
            continue
        for op, limit in limits.items():
            gap = limit - value if op == 'min' else value - limit
            if gap > 0:
                out[name] = (gap / abs(limit) if limit else gap, 1 if op == 'min' else -1)
    return out


def lever_moves(levers, targets, metrics):
    """[(parameter, direction, metric)]: moves that first-order improve the missed metrics, the worst-missed first."""
    moves, seen = [], set()
    for metric, (_, wanted) in sorted(miss_by_metric(targets, metrics).items(), key=lambda kv: -kv[1][0]):
        for name, sign in (levers or {}).get(metric, {}).items():
            d = wanted * (1 if sign == '+' else -1)
            if (name, d) not in seen:
                seen.add((name, d))
                moves.append((name, d, metric))
    return moves


def tried_moves(history):
    """(parameter, direction) of every step that was actually simulated in this run."""
    return {(c['parameter'], direction(c)) for r in history if r.get('point') is not None for c in r['changes']}


def dc_moves(levers):
    """The reference's DC levers (key "dc": raising a "+" parameter / lowering a "-" one makes the circuit conduct more)."""
    return [(name, 1 if sign == '+' else -1, 'DC') for name, sign in ((levers or {}).get('dc') or {}).items()]


def open_moves(levers, targets, metrics, history, closed, names, dc_failed=False):
    """Moves worth trying next: the levers of the missed metrics not yet tried and not closed (while DC fails: the DC
    levers); when the reference declares none, every never-moved parameter in both directions."""
    done = tried_moves(history) | set(closed)
    moves = dc_moves(levers) if dc_failed else lever_moves(levers, targets, metrics)
    if not moves:
        moved = {n for n, _ in tried_moves(history)}
        moves = [(n, d, None) for n in names if n not in moved for d in (1, -1)]
    return [m for m in moves if (m[0], m[1]) not in done]


def move_text(moves, limit=4):
    return ', '.join(f"{'raise' if d > 0 else 'lower'} {n}" + (f' (for {m})' if m else '') for n, d, m in moves[:limit])


def circuit_is_off(measurement, devices):
    """True when DC failed for every MOS: nothing conducts, so only bias levers can change anything."""
    failed = (measurement.get('dc_acceptance') or {}).get('failed_devices') or []
    return not measurement['dc_passed'] and bool(devices) and set(devices) <= set(failed)


def step_change(bounds, params, name, d):
    """One toolchain step of a parameter in direction d (+1/-1); None when it cannot move that way."""
    b, x = bounds[name], number(params[name])
    if b['integer']:
        y = x + d
    elif _log_scale(b):
        y = x * STEP_FACTOR ** d
    else:
        y = x + d * STEP_SHARE * (b['max'] - b['min'])
    y = min(max(y, b['min']), b['max'])
    if y == x:
        return None
    return dict(parameter=name, old_value=params[name], new_value=text_number(y),
                reason=f"toolchain step: {'raise' if d > 0 else 'lower'} {name} (first-order lever)")


def effective(changes):
    """Drop changes that leave the value as it is."""
    keep = []
    for c in changes:
        try:
            same = math.isclose(number(c['new_value']), number(c['old_value']), rel_tol=1e-9, abs_tol=0)
        except (KeyError, ValueError):
            same = False
        if not same:
            keep.append(c)
    return keep


def shortfall(targets, metrics):
    """Total relative miss of all targets (0 = every target met); None when a metric is not measured."""
    total = 0.0
    for name, limits in targets.items():
        value = metrics.get(name)
        if value is None or not math.isfinite(value):
            return None
        for op, limit in limits.items():
            gap = limit - value if op == 'min' else value - limit
            total += max(0.0, gap / abs(limit) if limit else gap)
    return total


def spec_check(targets, metrics):
    """Exact comparison of measured metrics with targets; None means not measured."""
    rows = {}
    for name, limits in targets.items():
        value = metrics.get(name)
        ok = None if value is None or not math.isfinite(value) else all(
            value >= limit if op == 'min' else value <= limit for op, limit in limits.items())
        margin = None if ok is None else {op: sig(value - limit if op == 'min' else limit - value)
                                          for op, limit in limits.items()}
        rows[name] = dict(target=limits, value=sig(value), passed=ok, margin=margin)
    return rows


def direction(change):
    """+1 if the change raises the parameter, -1 if it lowers it (0 when unreadable)."""
    try:
        return (number(change['new_value']) > number(change['old_value'])) - (number(change['new_value']) < number(change['old_value']))
    except (KeyError, ValueError):
        return 0


def step_effect(before_miss, after_miss):
    """How a step changed the total miss of the targets: better / worse / same; a point that is not fully measured
    (DC failed) is worse."""
    if after_miss is None:
        return 'worse (DC fail)'
    if before_miss is None or after_miss < before_miss - 1e-9:
        return 'better'
    return 'worse' if after_miss > before_miss + 1e-9 else 'same'


def charged(history):
    """The decisions that count against the budget (a refused decision within the free allowance does not)."""
    return [r for r in history if not r.get('free')]


def proposal(changes):
    return ', '.join(f"{c.get('parameter')}->{c.get('new_value')}" for c in changes) or 'no change'


def history_table(history):
    """Every simulated point of this run, one row each, plus notes on what was refused or reverted."""
    if not history:
        return None
    points, notes = [], []
    start = history[0].get('before')
    if start and 'point' in start:
        points.append(('start', start['point'], start, False, ''))
    for row in history:
        i = row['iteration']
        if row.get('point') is not None:
            points.append((i, row['point'], row['result'], row.get('rolled_back', False), row.get('effect', '')))
        if row.get('validation_error') and row.get('phase') != 'explore':
            notes.append(f"#{i}: {proposal(row['changes'])} not applied ({row['validation_error']}); nothing changed"
                         + ('; this refusal did not use a decision' if row.get('free') else ''))
        for attempt in row.get('rejected_attempts', []):
            notes.append(f"#{i}: earlier attempt {attempt['proposal']} refused ({attempt['error']})")
        for clamped in row.get('clamped', []):
            notes.append(f"#{i}: {clamped}")
        if row.get('phase') == 'memory':
            kind = 'passed DC' if row.get('repair') else 'met the current targets'
            notes.append(f"#{i}: tried the nearest remembered design that {kind} ({proposal(row['changes'])}); "
                         + ('it did not verify, the previous point was restored' if row.get('rolled_back') else 'kept'))
        elif row.get('fallback'):
            notes.append(f"#{i}: the model's proposals were refused; the toolchain stepped the next untried lever instead")
        if row.get('phase') == 'explore':
            notes.append(f"#{i}: {MAX_CONSECUTIVE_REVERTS} undone steps in a row, so the toolchain stopped climbing and "
                         + ('jumped to a new region: ' + proposal(row['changes']) if row.get('accepted')
                            else 'found no DC-valid point for a large jump; climbing resumes'))
        elif row.get('rolled_back'):
            why = ('broke DC ('+', '.join(row['result']['failed_dc_devices'])+')' if not row['result']['dc_passed']
                   else 'made the targets worse')
            notes.append(f"#{i}: {proposal(row['changes'])} {why}; the previous point was restored")
    varied = [n for n in points[0][1] if len({p[1][n] for p in points}) > 1] if points else []
    metric_names = list(points[0][2]['metrics']) if points else []
    rows = []
    for label, pt, result, reverted, effect in points:
        status = 'ok' if result['dc_passed'] else 'DC fail ' + (','.join(result['failed_dc_devices'])
                                                                or 'loop does not hold out at VCM')
        rows.append([label] + [pt[n] for n in varied] + [status + (' (reverted)' if reverted else ''), effect]
                    + [sig(result['metrics'].get(m)) for m in metric_names])
    current = next((p[0] for p in reversed(points) if not p[3]), 'start')
    table = dict(columns=['step'] + varied + ['dc', 'vs_previous'] + metric_names, rows=rows, current_step=current)
    if notes:
        table['notes'] = notes
    return table


def history_outcomes(history):
    """Per decision what was proposed and measured, for the reviewer (no model prose)."""
    return [dict(iteration=r['iteration'], phase=r['phase'], proposed=proposal(r['changes']),
                 applied='validation_error' not in r, **({'result': outcome(r['result'])} if 'result' in r else {}))
            for r in history]


def failing_targets(evidence):
    return [(k, v) for k, v in evidence.get('spec_check', {}).items() if v.get('passed') is not True]


def num(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def target_text(v):
    return ', '.join(f'{op} {num(x)}' for op, x in v['target'].items())


def diagnosis(evidence):
    """What the evidence shows, with the numbers copied from it (a model quotes numbers unreliably)."""
    failing = failing_targets(evidence)
    if not failing:
        return 'All targets are met.'
    text = '; '.join(f"{k} {num(v.get('value'))} (need {target_text(v)})" for k, v in failing)
    final = evidence.get('final') or {}
    if final.get('dc_passed') is False:
        return f'DC gate failed, so these are not measured: {text}.'
    return f'Not met: {text}.'


def advice(evidence):
    """Revision advice built from the evidence, not written by a model."""
    parts = []
    failing = failing_targets(evidence)
    if failing:
        parts.append('Failing: ' + '; '.join(f"{k} {num(v.get('value'))} (need {target_text(v)})" for k, v in failing) + '.')
    rows = (evidence.get('parameters') or {}).get('rows', [])
    at = [f"{r[0]} at its {r[-1]} (can only go {'up' if r[-1] == 'min' else 'down'})" for r in rows if r[-1]]
    if at:
        parts.append('At a tune bound: ' + ', '.join(at) + '.')
    if evidence.get('open_moves'):
        parts.append('Untried levers: ' + evidence['open_moves'] + '.')
    else:
        moved = set((evidence.get('sizing_history') or {}).get('columns', []))
        unmoved = [r[0] for r in rows if r[0] not in moved][:4]
        if unmoved:
            parts.append('Never moved in the last run: ' + ', '.join(unmoved) + '.')
    if (evidence.get('sizing') or {}).get('status') == 'dc_iteration_limit':
        parts.append('DC was not recovered within the budget.')
    parts.append('Every simulated point is in `history`: do not propose one again, and do not continue in a direction '
                 'whose `vs_previous` was worse.')
    return ' '.join(parts)
