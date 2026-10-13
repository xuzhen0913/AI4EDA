"""Design memory: the simulated design points of earlier runs, kept in one token-lean text file.

One section per (circuit type, reference, operating condition); one line per design point:

    P 74.6 22.1 63.3 106 | PARAM_A=23 PARAM_B=7k

`P` = met that run's targets, `F` = simulated but missed them, `D` = failed the DC gate (no metrics, `-`). Metrics
follow the section's `cols` line (units in brackets); after `|` come only the parameters that differ from the reference's
start values. Writing a point first removes near-duplicates (same reference, parameters within CLOSE of each other
as a share of the tune range) and then enforces CAP points per section. The review agent writes it after every round;
the topology and sizing agents read it.
"""
import math
from collections import namedtuple
from pathlib import Path
from .config import ROOT
from .search import shortfall, spec_check, to_unit
from .spice import number

PATH = ROOT / 'design_memory.txt'
CAP = 30          # points kept per reference and operating condition
CLOSE = 0.04      # two points closer than this in every parameter (share of the tune range) count as one
DC_SHARE = 3      # at most CAP // DC_SHARE of the kept points are DC failures
UNITS = {'ugb_hz': ('MHz', 1e6), 'power_w': ('uW', 1e-6)}   # shown in these units; any other metric is stored as is
HEADER = ('# design memory. [circuit/reference] conditions; cols = metrics (units); row = status metrics | parameters that '
          'differ from the reference start values.\n# status: P met that run\'s targets, F simulated but missed, D failed '
          'the DC gate (metrics -). Oldest row first.\n')
SCALES = ((1e6, 'meg'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, 'u'), (1e-9, 'n'), (1e-12, 'p'), (1e-15, 'f'))

Row = namedtuple('Row', 'status metrics params')   # metrics: list in the section's column order (None = not measured)
Section = namedtuple('Section', 'cols rows')       # cols: metric names


def eng(x):
    """Shortest SPICE spelling of x within 0.1 %: 7000 -> 7k, 1.5e-12 -> 1.5p, 0.74 -> 0.74 (plain wins ties)."""
    if x == 0:
        return '0'
    options = [f'{x / scale:.4g}{suffix}' for scale, suffix in SCALES]
    options = [o for o, (scale, _) in zip(options, SCALES) if 'e' not in o and abs(number(o) - x) <= 1e-3 * abs(x)]
    return min(options, key=lambda o: (len(o), not o[-1].isdigit())) if options else f'{x:.4g}'


def condition_key(specs):
    c = specs['conditions']
    return f"{specs['process']} {specs['corner']} " + ' '.join(f'{k}={eng(v)}' for k, v in c.items())


def to_shown(name, value):
    unit, scale = UNITS.get(name, ('', 1))
    return None if value is None else float(f'{value / scale:.3g}')


def from_shown(name, value):
    return None if value is None else value * UNITS.get(name, ('', 1))[1]


def col_label(name):
    unit = UNITS.get(name, ('', 1))[0]
    return f'{name}[{unit}]' if unit else name


def parse_col(label):
    return label.split('[')[0]


def row_text(row, extra=''):
    shown = ' '.join('-' if v is None else f'{v:.3g}' for v in row.metrics) if any(v is not None for v in row.metrics) else ''
    params = ' '.join(f'{k}={v}' for k, v in row.params.items())
    return f'{row.status}' + (f' {shown}' if shown else '') + extra + (f' | {params}' if params else '')


def parse_row(text, width):
    head, _, tail = text.partition('|')
    fields = head.split()
    params = dict(p.split('=', 1) for p in tail.split())
    values = [None if f == '-' else float(f) for f in fields[1:1 + width] if not f.startswith('m')]
    return Row(fields[0], values + [None] * (width - len(values)), params)


def load(path=PATH):
    """{(circuit, reference, conditions): Section} from the file (empty when it does not exist)."""
    memory, key = {}, None
    path = Path(path)
    if not path.exists():
        return memory
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        if line.startswith('['):
            name, _, cond = line[1:].partition('] ')
            circuit, _, reference = name.partition('/')
            key = (circuit, reference, cond.strip())
            memory[key] = Section([], [])
        elif line.startswith('cols'):
            memory[key].cols.extend(parse_col(c) for c in line[4:].split())
        else:
            memory[key].rows.append(parse_row(line, len(memory[key].cols)))
    return memory


def save(memory, path=PATH):
    out = [HEADER]
    for (circuit, reference, cond), section in sorted(memory.items()):
        if not section.rows:
            continue
        out.append(f'[{circuit}/{reference}] {cond}\ncols ' + ' '.join(col_label(c) for c in section.cols) + '\n')
        out.extend(row_text(r) + '\n' for r in section.rows)
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(''.join(out))
    temporary.replace(path)


def actual(section, row):
    """The row's metrics as {name: value in SI units}."""
    return {c: from_shown(c, v) for c, v in zip(section.cols, row.metrics)}


def unit_vector(row, initial, bounds):
    return [to_unit(b, number(row.params.get(n, initial[n]))) for n, b in bounds.items()]


def too_close(a, b):
    return max(abs(x - y) for x, y in zip(a, b)) <= CLOSE


def rank(section, row, targets):
    """Smaller is better: met targets, then the miss of the missed ones, then DC failures."""
    if row.status == 'D':
        return (2, 0.0)
    miss = shortfall(targets, actual(section, row))
    return (0, 0.0) if row.status == 'P' else (1, 20.0 if miss is None else miss)


def reduce(section, initial, bounds, targets):
    """Drop near-duplicates (the better one stays, the newer one on a tie), then keep at most CAP rows."""
    indexed = list(enumerate(section.rows))
    order = sorted(indexed, key=lambda t: (rank(section, t[1], targets), -t[0]))
    kept, vectors = [], []
    for i, row in order:
        v = unit_vector(row, initial, bounds)
        if any((row.status == 'D') == (k.status == 'D') and too_close(v, w) for (_, k), w in zip(kept, vectors)):
            continue
        kept.append((i, row))
        vectors.append(v)
    dc = sorted((t for t in kept if t[1].status == 'D'), key=lambda t: -t[0])[:CAP // DC_SHARE]   # the newest DC failures
    good = sorted((t for t in kept if t[1].status != 'D'), key=lambda t: (rank(section, t[1], targets), -t[0]))[:CAP - len(dc)]
    keep = sorted(dc + good, key=lambda t: t[0])
    return Section(section.cols, [r for _, r in keep])


def make_row(section, status, metrics, params, initial, bounds):
    """A row from SI metrics and the full parameter values of a design point; new metric names extend the columns."""
    for name in metrics:
        if name not in section.cols:
            section.cols.append(name)
            section.rows[:] = [Row(r.status, r.metrics + [None], r.params) for r in section.rows]
    shown = [None if status == 'D' else to_shown(c, metrics.get(c)) for c in section.cols]
    diff = {n: eng(number(params[n])) for n in bounds
            if n in params and not math.isclose(number(params[n]), number(initial[n]), rel_tol=1e-3, abs_tol=0)}
    return Row(status, shown, diff)


def add(memory, key, reference, targets, points):
    """Store design points under `key`; `reference` supplies the start values and tune ranges.

    points: (status, metrics {name: SI value or None}, parameter values {name: text}). Returns the number of rows kept."""
    initial = reference.initial
    bounds = {n: b for n, b in reference.bounds.items()}
    section = memory.setdefault(key, Section([], []))
    if not section.cols:
        section.cols.extend(targets)   # the metric columns of a new section: the targets' metrics, in their order
    for status, metrics, params in points:
        section.rows.append(make_row(section, status, metrics, params, initial, bounds))
    memory[key] = reduce(section, initial, bounds, targets)
    return len(memory[key].rows)


def classify(dc_passed, checks):
    """D = DC gate failed, P = every target met, F = otherwise."""
    if not dc_passed:
        return 'D'
    return 'P' if checks and all(c['passed'] is True for c in checks.values()) else 'F'


def view(memory, circuit, reference, cond, targets, limit=8):
    """The sizing agent's view of one reference under the current conditions: the best rows (by miss of the CURRENT
    targets) and a few DC failures, in the file's own format plus `m` = miss of the current targets."""
    section = memory.get((circuit, reference, cond))
    if not section or not section.rows:
        return None
    ranked = sorted(section.rows, key=lambda r: rank(section, r, targets))
    dc = [r for r in ranked if r.status == 'D'][:max(1, limit // 4)]
    chosen = [r for r in ranked if r.status != 'D'][:limit - len(dc)] + dc
    rows = []
    for r in chosen:
        miss = None if r.status == 'D' else shortfall(targets, actual(section, r))
        now = r if miss is None else r._replace(status='P' if miss == 0 else 'F')   # status as of the CURRENT targets
        rows.append(row_text(now, '' if miss is None else f' m{miss:.2g}'))
    return dict(cols=' '.join(col_label(c) for c in section.cols), rows=rows, points_stored=len(section.rows))


def summary(memory, circuit, reference, cond, targets):
    """The topology agent's view of one candidate: how much is known and how close the best point is to the targets."""
    section = memory.get((circuit, reference, cond))
    if not section or not section.rows:
        return None
    measured = [r for r in section.rows if r.status != 'D']
    out = dict(points=len(section.rows), dc_failures=len(section.rows) - len(measured))
    if measured:
        best = min(measured, key=lambda r: rank(section, r, targets))
        misses = [k for k, v in spec_check(targets, actual(section, best)).items() if v['passed'] is not True]
        out.update(best=row_text(best).split('|')[0].strip(), best_cols=' '.join(col_label(c) for c in section.cols),
                   best_meets_current_targets=not misses, best_misses=misses)
    return out


def history_points(history):
    """The distinct design points a sizing run simulated: [{dc_passed, metrics, point}] (start point included)."""
    points = []
    if history and 'point' in history[0].get('before', {}):
        points.append(history[0]['before'])
    points += [dict(dc_passed=r['result']['dc_passed'], metrics=r['result']['metrics'], point=r['point'])
               for r in history if r.get('point') is not None]
    unique = {tuple(sorted(p['point'].items())): p for p in points}
    return list(unique.values())


def known_points(memory, key, reference):
    """Every row of one section as [(status, metrics in SI units or None, full tunable parameter values {name: text})]."""
    section = memory.get(key)
    if not section:
        return []
    return [(r.status, None if r.status == 'D' else actual(section, r),
             {n: r.params.get(n, reference.initial[n]) for n in reference.bounds}) for r in section.rows]
