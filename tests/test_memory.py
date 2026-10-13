"""The design memory: compact text format, near-duplicate removal, per-reference cap, and its use by the agents."""
from types import SimpleNamespace
import pytest
from agents.review_agent.agent import ReviewAgent
from agents.sizing_agent.agent import SizingAgent
from agents.topology_agent.agent import TopologyAgent
from analog_agents import memory as M
from analog_agents.spice import number
from helpers import EXAMPLE, REFS, SPECS

TARGETS = SPECS['targets']
KEY = ('opamp', EXAMPLE.id, M.condition_key(SPECS))
GOOD = dict(dc_gain_db=70.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=2e-4)
BAD = dict(dc_gain_db=40.0, ugb_hz=5e6, phase_margin_deg=30.0, power_w=2e-4)


def point(status, metrics, **params):
    return (status, metrics, {k: str(v) for k, v in params.items()})


def test_eng_is_short_and_round_trips():
    assert [M.eng(x) for x in (7000, 1.5e-12, 0.74, 35e-6, 700, 0)] == ['7k', '1.5p', '0.74', '35u', '700', '0']
    for x in (7000, 1.5e-12, 0.74, 35e-6, 0.65e-12, 12.5, 2.5e6):
        assert number(M.eng(x)) == pytest.approx(x, rel=1e-3)


def test_rows_store_only_parameters_that_differ_from_the_start_and_use_short_units(tmp_path):
    memory = {}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('P', GOOD, W_IN=12, CC='1p', R_RZ=7000), point('D', {}, W_IN=99)])
    path = tmp_path/'m.txt'
    M.save(memory, path)
    text = path.read_text()
    assert f'[opamp/{EXAMPLE.id}] sky130 tt vdd_v=1.8' in text and 'cols dc_gain_db ugb_hz[MHz] phase_margin_deg power_w[uW]' in text
    assert 'P 70 20 70 200 | W_IN=12 R_RZ=7k' in text and '\nD | W_IN=99\n' in text      # CC=1p is the start value: omitted
    assert M.load(path) == memory                                                       # exact round trip


def test_near_duplicates_are_removed_keeping_the_better_one_and_far_points_stay():
    memory = {}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('F', BAD, W_IN=12.0), point('P', GOOD, W_IN=12.3),   # same cluster (0.3 of 99 um)
                                          point('F', BAD, W_IN=60), point('D', {}, W_IN=12.1)])       # far; D is its own class
    rows = memory[KEY].rows
    assert sorted(r.status for r in rows) == ['D', 'F', 'P'] and {r.params['W_IN'] for r in rows} == {'12.3', '60', '12.1'}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('F', BAD, W_IN=12.4)])                                # close to the P row -> dropped
    assert len(memory[KEY].rows) == 3


def test_per_reference_cap_keeps_the_best_and_the_newest_dc_failures():
    memory = {}
    grid = [(a, b) for a in range(5) for b in range(6)]                       # 30 points far apart in W_IN and L_IN
    spread = [point('F', dict(BAD, dc_gain_db=40 + i / 10), W_IN=1 + 20 * a, L_IN=0.15 + 0.35 * b) for i, (a, b) in enumerate(grid)]
    spread += [point('D', {}, CC=0.2e-12 * 1.4 ** i) for i in range(12)]
    M.add(memory, KEY, EXAMPLE, TARGETS, spread)
    rows = memory[KEY].rows
    dc = [r for r in rows if r.status == 'D']
    assert len(rows) == M.CAP and len(dc) == M.CAP // M.DC_SHARE
    assert [r.params['CC'] for r in dc] == [M.eng(0.2e-12 * 1.4 ** i) for i in range(2, 12)]            # the 10 newest
    best, worst = grid[-1], grid[0]
    kept = {(r.params.get('W_IN', '1'), r.params.get('L_IN', '0.15')) for r in rows if r.status == 'F'}
    assert (M.eng(1 + 20 * best[0]), M.eng(0.15 + 0.35 * best[1])) in kept and ('1', '0.15') not in kept   # worst F rows fell out


def test_status_classification():
    ok = {'a': {'passed': True}}
    assert M.classify(False, ok) == 'D' and M.classify(True, ok) == 'P' and M.classify(True, {'a': {'passed': None}}) == 'F'
    assert M.classify(True, {}) == 'F'


def test_agent_views_are_compact_and_computed_against_the_current_targets():
    memory = {}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('P', GOOD, W_IN=12), point('F', BAD, W_IN=40), point('D', {}, W_IN=80)])
    view = M.view(memory, *KEY, TARGETS)
    assert view['cols'] == 'dc_gain_db ugb_hz[MHz] phase_margin_deg power_w[uW]' and view['rows'][0].startswith('P 70 20 70 200 m0 |')
    assert view['rows'][-1] == 'D | W_IN=80' and view['rows'][1].startswith('F 40 5 30 200 m')
    summary = M.summary(memory, *KEY, TARGETS)
    assert summary['points'] == 3 and summary['dc_failures'] == 1 and summary['best_meets_current_targets'] is True
    hard = dict(TARGETS, ugb_hz={'min': 1e9})
    assert M.summary(memory, *KEY, hard)['best_misses'] == ['ugb_hz']
    assert M.view(memory, 'opamp', 'other', KEY[2], TARGETS) is None and M.summary({}, *KEY, TARGETS) is None


def test_review_agent_stores_the_rounds_points_and_prunes_what_is_already_there(tmp_path):
    history = [dict(iteration=1, phase='performance', changes=[], point={'W_IN': '40'},
                    result=dict(dc_passed=True, failed_dc_devices=[], metrics=GOOD), before=dict(
                        dc_passed=True, failed_dc_devices=[], metrics=BAD, point={'W_IN': '10'})),
               dict(iteration=2, phase='performance', changes=[], point={'W_IN': '80'},
                    result=dict(dc_passed=False, failed_dc_devices=['XM7'], metrics={'dc_gain_db': None}))]
    path = tmp_path/'m.txt'
    agent = ReviewAgent(SimpleNamespace(calls=[]))
    assert agent.remember(path, 'opamp', EXAMPLE, SPECS, history) == 3
    assert [r.status for r in M.load(path)[KEY].rows] == ['F', 'P', 'D']
    assert agent.remember(path, 'opamp', EXAMPLE, SPECS, history) == 3        # the same round again changes nothing


class Recorder:
    def __init__(self):
        self.payloads = []

    def ask(self, prompt, payload, schema, agent_name='test', use_rules=False):
        self.payloads.append(payload)
        ids = [c['id'] for c in payload['candidates']]
        return dict(selected_reference=ids[0], reasoning='x', expected_risks='x',
                    ranking=[dict(reference=i, suitability='high', reason='x') for i in ids])


def test_topology_candidates_carry_their_memory_summary_only_when_there_is_one():
    memory = {}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('P', GOOD, W_IN=12)])
    client = Recorder()
    TopologyAgent(client).select(SPECS, REFS, memory=memory)
    by_id = {c['id']: c for c in client.payloads[0]['candidates']}
    assert by_id[EXAMPLE.id]['memory']['best_meets_current_targets'] is True
    assert all('memory' not in c for i, c in by_id.items() if i != EXAMPLE.id)


def test_sizing_payload_gets_the_memory_view_only_when_set():
    from helpers import TARGET
    client = SimpleNamespace(calls=[], payloads=[], ask=lambda *a, **k: client.payloads.append(a[1]) or {'analysis': {}, 'changes': []})
    agent = SizingAgent(client)
    from test_search import WidthRunner
    from pathlib import Path
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d/'c.spice').write_text(EXAMPLE.text)
    m = WidthRunner().run(d/'c.spice', 'full')
    m['log'] = str(d/'l.log')
    (d/'l.log').write_text('')
    m.update(checks={}, dc_operating_point={}, errors=[], warnings=[], ac_polarity={}, bias='closed_loop',
             dc_acceptance=dict(devices={}, failed_devices=[], loop=dict(passed=True, output_error_v=0.0)))
    agent.run(TARGET, EXAMPLE.text, m, [])
    assert 'memory' not in client.payloads[0]
    agent.memory = dict(cols='a', rows=['P 1'])
    agent.run(TARGET, EXAMPLE.text, m, [])
    assert client.payloads[1]['memory'] == dict(cols='a', rows=['P 1'])


def test_the_view_shows_the_status_against_the_current_targets_not_the_one_stored():
    memory = {}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('P', GOOD, W_IN=12)])                      # stored as P under TARGETS
    harder = dict(TARGETS, ugb_hz={'min': 1e9})
    assert M.view(memory, *KEY, harder)['rows'][0].startswith('F ') and M.view(memory, *KEY, TARGETS)['rows'][0].startswith('P ')


def test_known_points_are_full_parameter_sets_with_si_metrics():
    memory = {}
    M.add(memory, KEY, EXAMPLE, TARGETS, [point('P', GOOD, W_IN=12), point('D', {}, W_IN=90)])
    (s1, m1, p1), (s2, m2, p2) = M.known_points(memory, KEY, EXAMPLE)
    assert s1 == 'P' and m1['ugb_hz'] == pytest.approx(2e7) and p1['W_IN'] == '12' and p1['CC'] == EXAMPLE.initial['CC']
    assert s2 == 'D' and m2 is None and set(p1) == set(EXAMPLE.bounds)


def test_levers_are_validated_and_reach_the_sizing_input_and_the_review_advice():
    import pytest as _p
    from agents.sizing_agent.agent import levers_table
    from analog_agents.reference import parse_reference
    from analog_agents.search import advice
    from helpers import TARGET
    assert levers_table(TARGET)['ugb_hz'] == '+IBIAS +W_IN +N_TAIL +N_STAGE2_BIAS -CC'
    broken = EXAMPLE.text.replace('"ugb_hz": {"IBIAS": "+"', '"ugb_hz": {"NOT_A_PARAMETER": "+"')
    with _p.raises(ValueError):
        parse_reference(broken, 'broken')
    evidence = {'spec_check': {'ugb_hz': {'target': {'min': 4e7}, 'value': 2e7, 'passed': False}}, 'final': {'dc_passed': True},
                'open_moves': 'raise IBIAS (for ugb_hz), lower CC (for ugb_hz)'}
    assert 'Untried levers: raise IBIAS (for ugb_hz), lower CC (for ugb_hz).' in advice(evidence)
