"""Orchestration tests with scripted agents and a scripted simulator (no model, no ngspice)."""
import json
import shutil
from types import SimpleNamespace
import pytest
import main
from agents.review_agent.agent import ReviewAgent, parameter_table, spec_check
from agents.topology_agent.agent import TopologyAgent
from analog_agents.reference import parse_bounds
from helpers import BASE, REFS, SPECS

TWO, FOLD = 'two_stage_nmos_input_pmos_stage2', 'folded_cascode_nmos_input'


class ScriptedClient:
    """Answers from a queue and records calls like the real clients."""
    def __init__(self, script):
        self.script, self.calls, self.payloads = script, [], []

    def ask(self, prompt, payload, schema, agent_name='test', use_rules=False):
        self.payloads.append(payload)
        self.calls.append({'agent': agent_name, 'use_rules': use_rules,
                           'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
        reply = self.script.pop(0)
        return reply(payload) if callable(reply) else reply


def pick(ref_id):
    return lambda payload: dict(selected_reference=ref_id, reasoning='scripted', expected_risks='none',
        ranking=[dict(reference=c['id'], suitability='high' if c['id'] == ref_id else 'low', reason='scripted')
                 for c in payload['candidates']])


SIZE = dict(analysis=dict(simulation_valid=True, dc_op_valid=True, main_problem='scripted', reasoning='scripted'), changes=[])
W_IN_UP = dict(SIZE, changes=[dict(parameter='W_IN', old_value='10', new_value='12', reason='x')])


def review(verdict, advice='fix it', restart=False):
    return dict(verdict=verdict, diagnosis='d', revision_advice='' if verdict == 'pass' else advice,
                restart_sizing_from_reference=restart)


class FakeRunner:
    """Passes DC always; full-simulation metrics come from a shared queue."""
    queue = []

    def __init__(self, results, target):
        self.results, self.target, self.count = results, target, 0

    def run(self, candidate, mode='dc'):
        self.count += 1
        logs = self.results/'logs'
        logs.mkdir(exist_ok=True)
        log = logs/f'simulation_{self.count:03d}.log'
        log.write_text('scripted log\n')
        metrics = dict(dc_gain_db=None, ugb_hz=None, phase_margin_deg=None, power_w=1e-4)
        if mode == 'full':
            metrics = FakeRunner.queue.pop(0)
        checks = {k: None if v is None else all(v >= lim if op == 'min' else v <= lim for op, lim in self.target['targets'][k].items())
                  for k, v in metrics.items()}
        m = dict(analysis_mode=mode, metrics=metrics, dc_operating_point={}, simulation_valid=True, dc_passed=True,
                 dc_numerical_valid=True, dc_acceptance=dict(passed=True, failed_devices=[], devices={}),
                 ac_polarity={}, warnings=[], errors=[], return_code=0, checks=checks, log=str(log),
                 all_targets_passed=mode == 'full' and all(v is True for v in checks.values()),
                 simulation_number=self.count)
        (logs/f'simulation_{self.count:03d}.json').write_text(json.dumps(m))
        return m


GOOD = dict(dc_gain_db=70.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=2e-4)
BAD = dict(dc_gain_db=40.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=2e-4)


@pytest.fixture
def env(tmp_path, monkeypatch):
    base = tmp_path/'opamp'
    shutil.copytree(BASE/'reference', base/'reference')
    (base/'specs').mkdir()
    (base/'specs/target.json').write_text(json.dumps(SPECS))
    monkeypatch.setattr(main, 'BASE', base)
    monkeypatch.setattr(main, 'NgspiceRunner', FakeRunner)
    monkeypatch.setattr(main, 'generate', lambda results, language='en': results/'x.pdf')
    monkeypatch.setattr(main, 'backend', lambda: SimpleNamespace(kind='claude', alias='fake', model_id='fake-model'))
    clients = {}

    def script(topology, sizing, reviewer, sims):
        FakeRunner.queue = list(sims)
        clients.update(topology=ScriptedClient(topology), sizing=ScriptedClient(sizing), review=ScriptedClient(reviewer))
        monkeypatch.setattr(main, 'new_client', lambda selection, order=iter(('topology', 'sizing', 'review')): clients[next(order)])

    def run():
        status = main.run()
        return status, json.loads((base/'results/summary.json').read_text())
    return SimpleNamespace(base=base, clients=clients, script=script, run=run)


def test_first_round_pass(env):
    env.script([pick(TWO)], [], [review('pass')], [GOOD])
    status, s = env.run()
    assert status == 0 and s['status'] == 'targets_passed' and s['rounds_run'] == 1
    assert s['final_reference'] == TWO and s['calls_by_agent'] == {'topology': 1, 'sizing': 0, 'review': 1}
    assert s['final_candidate'] == 'round_01/candidate.spice' and (env.base/'results'/s['final_candidate']).exists()
    assert (env.base/'results/round_01/topology_selection.json').exists() and (env.base/'results/specs.json').exists()


def test_only_the_sizing_agent_receives_the_handbook(env):
    env.script([pick(TWO)], [SIZE], [review('pass')], [BAD, GOOD])
    env.run()
    assert [c['use_rules'] for c in env.clients['sizing'].calls] == [True]
    assert not any(c['use_rules'] for c in env.clients['topology'].calls + env.clients['review'].calls)


def test_sizing_feedback_loop_does_not_call_topology_again(env):
    # round 1 spends its 10-decision budget (baseline + one simulation per decision), round 2 passes at its baseline
    env.script([pick(TWO)], [SIZE]*10, [review('fail_sizing', 'raise gain'), review('pass')], [BAD]*11 + [GOOD])
    status, s = env.run()
    assert s['status'] == 'targets_passed' and s['rounds_run'] == 2
    assert s['calls_by_agent']['topology'] == 1 and s['calls_by_agent']['sizing'] == 10
    first, second = s['rounds']
    assert first['decisions'] == 10 and not first['sizing_feedback_used']
    assert second['sizing_feedback_used'] and second['topology_agent_ran'] is False and second['reference'] == TWO
    assert env.clients['review'].payloads[0]['spec_check']['dc_gain_db']['passed'] is False


def test_sizing_agent_gets_the_reviewers_diagnosis_and_advice_only(env):
    env.script([pick(TWO)], [SIZE]*10 + [SIZE], [review('fail_sizing', 'raise gain'), review('pass')], [BAD]*11 + [BAD, GOOD])
    env.run()
    assert 'reviewer_feedback' not in env.clients['sizing'].payloads[0]
    assert env.clients['sizing'].payloads[10]['reviewer_feedback'] == {'diagnosis': 'd', 'revision_advice': 'raise gain'}


def test_topology_failure_excludes_that_topology_and_resets_sizing_budget(env):
    env.script([pick(TWO), pick(FOLD)], [SIZE]*10, [review('fail_topology', 'needs cascode'), review('pass')], [BAD]*11 + [GOOD])
    status, s = env.run()
    assert s['status'] == 'targets_passed' and s['rounds_run'] == 2
    assert [r['reference'] for r in s['rounds']] == [TWO, FOLD]
    topology = env.clients['topology'].payloads
    assert TWO not in [c['id'] for c in topology[1]['candidates']] and FOLD in [c['id'] for c in topology[1]['candidates']]
    assert topology[1]['review_feedback']['revision_advice'] == 'needs cascode'
    assert s['rounds'][1]['decisions'] == 0 and s['rounds'][1]['topology_agent_ran'] and not s['rounds'][1]['sizing_feedback_used']
    assert 'tune' in (env.base/'results/round_02/candidate.spice').read_text()


def test_at_most_three_rounds_but_sizing_exceeds_three_decisions(env):
    env.script([pick(TWO)], [SIZE]*30, [review('fail_sizing')]*3, [BAD]*33)
    status, s = env.run()
    assert s['status'] == 'max_rounds_reached' and s['rounds_run'] == 3 and status == 0
    assert sum(r['decisions'] for r in s['rounds']) == 30


def test_pass_verdict_cannot_override_failed_spec(env):
    env.script([pick(TWO)], [SIZE]*10, [review('pass'), review('pass')], [BAD]*11 + [GOOD])
    status, s = env.run()
    assert s['rounds'][0]['verdict'] == 'fail_sizing' and s['rounds_run'] == 2 and s['status'] == 'targets_passed'
    saved = json.loads((env.base/'results/round_01/review.json').read_text())
    assert saved['reviewer_verdict'] == 'pass' and 'verdict_overridden' in saved


def test_restart_flag_starts_from_reference_and_continue_keeps_last_candidate(env):
    for restart, expected in ((True, '.param W_IN=10 '), (False, '.param W_IN=12 ')):
        env.script([pick(TWO)], [W_IN_UP]*10, [review('fail_sizing', restart=restart), review('pass')], [BAD]*11 + [GOOD])
        env.run()
        assert expected in (env.base/'results/round_02/candidate.spice').read_text()


def test_stored_history_has_no_duplicated_state(env):
    env.script([pick(TWO)], [W_IN_UP, SIZE], [review('pass')], [BAD, BAD, GOOD])
    env.run()
    rows = json.loads((env.base/'results/round_01/history.json').read_text())
    assert [r['iteration'] for r in rows] == [1, 2] and 'before' in rows[0] and 'before' not in rows[1]
    assert all(set(r) >= {'phase', 'analysis', 'changes', 'accepted', 'result', 'token_usage'} for r in rows)
    assert not any(k in rows[0] for k in ('parameters_before', 'parameters_after', 'measurements', 'qwen_analysis'))
    logs = sorted(p.name for p in (env.base/'results/round_01/logs').iterdir())
    assert not (env.base/'results/round_01/measurements.json').exists() and not (env.base/'results/round_01/current.log').exists()
    assert 'simulation_001.log' in logs and not (env.base/'working').exists()


def test_previous_run_is_moved_into_runs(env):
    env.script([pick(TWO)], [], [review('pass')], [GOOD])
    env.run()
    env.script([pick(TWO)], [], [review('pass')], [GOOD])
    env.run()
    archived = list((env.base/'results/runs').iterdir())
    assert len(archived) == 1 and (archived[0]/'round_01/candidate.spice').exists()


def test_budget_validation():
    for dc, total, rounds in [(6, 10, 3), (5, 11, 3), (5, 10, 4), (0, 10, 3)]:
        with pytest.raises(ValueError):main.check_budgets(dict(budgets=dict(max_dc_iterations=dc, max_iterations=total, max_rounds=rounds)))
    main.check_budgets(dict(budgets=dict(max_dc_iterations=5, max_iterations=10, max_rounds=3)))


def test_topology_agent_offers_only_profiles_and_rejects_unknown_choice():
    client = ScriptedClient([lambda p: dict(selected_reference='nope', reasoning='', expected_risks='', ranking=[])])
    agent = TopologyAgent(client)
    with pytest.raises(ValueError):agent.select(SPECS, REFS)
    payload = client.payloads[0]
    assert {c['id'] for c in payload['candidates']} == set(REFS) and all(set(c) == {'id', 'profile'} for c in payload['candidates'])
    assert set(payload) == {'targets', 'testbench', 'candidates'}
    with pytest.raises(ValueError):agent.select(SPECS, REFS, excluded=list(REFS))


def test_spec_check_and_parameter_table_helpers():
    rows = spec_check({'a': {'min': 5}, 'b': {'max': 2}, 'c': {'min': 1}}, {'a': 5.0, 'b': 3.0, 'c': None})
    assert rows['a']['passed'] and rows['b']['passed'] is False and rows['c']['passed'] is None
    text = REFS[TWO].text.replace('.param W_IN=10 ', '.param W_IN=100')
    table = parameter_table(text, parse_bounds(text))
    row = {r[0]: r for r in table['rows']}
    assert row['W_IN'][-1] == 'max' and row['L_IN'][-1] == '' and 'RSH_RZ' not in row


def test_review_requires_advice_when_failing():
    agent = ReviewAgent(ScriptedClient([dict(verdict='fail_sizing', diagnosis='', revision_advice=' ', restart_sizing_from_reference=False)]))
    with pytest.raises(ValueError):agent.review({'spec_check': {}, 'final': {'simulation_valid': True, 'dc_passed': True}})
