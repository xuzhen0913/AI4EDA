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


def review(verdict, *_):
    return dict(verdict=verdict)


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
                 dc_numerical_valid=True, dc_acceptance=dict(passed=True, failed_devices=[], devices={},
                                    loop=dict(passed=True, output_error_v=0.0, maximum_output_error_v=0.05)),
                 bias='closed_loop', ac_polarity=dict(loop_real_lf=1e3, passed=True, feedback_input=self.target['feedback_input']),
                 warnings=[], errors=[], return_code=0, checks=checks, log=str(log),
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
    monkeypatch.setattr(main, 'MEMORY', tmp_path/'design_memory.txt')   # never touch the real memory file
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
    assert [bool(c['use_rules']) for c in env.clients['sizing'].calls] == [True]
    assert not any(c['use_rules'] for c in env.clients['topology'].calls + env.clients['review'].calls)


def test_sizing_feedback_loop_does_not_call_topology_again(env):
    # round 1 spends its 10-decision budget (baseline + one simulation per decision), round 2 passes at its baseline
    env.script([pick(TWO)], [SIZE]*10, [review('fail_sizing'), review('pass')], [BAD]*11 + [GOOD])
    status, s = env.run()
    assert s['status'] == 'targets_passed' and s['rounds_run'] == 2
    assert s['calls_by_agent']['topology'] == 1 and s['calls_by_agent']['sizing'] == 10
    first, second = s['rounds']
    assert first['decisions'] == 10 and not first['sizing_feedback_used']
    assert second['sizing_feedback_used'] and second['topology_agent_ran'] is False and second['reference'] == TWO
    assert env.clients['review'].payloads[0]['spec_check']['dc_gain_db']['passed'] is False


def test_sizing_agent_gets_the_reviewers_diagnosis_and_advice_only(env):
    env.script([pick(TWO)], [SIZE]*10 + [SIZE], [review('fail_sizing'), review('pass')], [BAD]*11 + [BAD, GOOD])
    env.run()
    assert 'reviewer_feedback' not in env.clients['sizing'].payloads[0]
    feedback = env.clients['sizing'].payloads[10]['reviewer_feedback']
    assert set(feedback) == {'diagnosis', 'revision_advice'} and feedback['diagnosis'] == 'Not met: dc_gain_db 40 (need min 60).'
    assert 'dc_gain_db 40 (need min 60)' in feedback['revision_advice']      # built by Python from spec_check


def test_topology_failure_excludes_that_topology_and_resets_sizing_budget(env):
    env.script([pick(TWO), pick(FOLD)], [SIZE]*10, [review('fail_topology'), review('pass')], [BAD]*11 + [GOOD])
    status, s = env.run()
    assert s['status'] == 'targets_passed' and s['rounds_run'] == 2
    assert [r['reference'] for r in s['rounds']] == [TWO, FOLD]
    topology = env.clients['topology'].payloads
    assert TWO not in [c['id'] for c in topology[1]['candidates']] and FOLD in [c['id'] for c in topology[1]['candidates']]
    assert 'dc_gain_db' in topology[1]['attempt_history'][-1]['revision_advice'] and 'review_feedback' not in topology[1]
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


def test_next_round_continues_from_the_best_point_not_the_last_one(env):
    # W_IN 12 is measured BAD (gain 40); the unchanged start point is never worse, so the best point is the start
    W_IN_SECOND = dict(SIZE, changes=[dict(parameter='CC', new_value='2p', reason='x')])
    sims = [BAD, dict(BAD, dc_gain_db=30.0), dict(BAD, dc_gain_db=20.0)] + [BAD] * 8 + [GOOD]
    env.script([pick(TWO)], [W_IN_UP, W_IN_SECOND] + [SIZE] * 8, [review('fail_sizing'), review('pass')], sims)
    env.run()
    assert '.param W_IN=10 ' in (env.base/'results/round_02/candidate.spice').read_text()


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
    assert {c['id'] for c in payload['candidates']} == set(REFS) and all(set(c) == {'id', 'profile', 'verified_points'} for c in payload['candidates'])
    assert set(payload) == {'targets', 'testbench', 'candidates'}
    with pytest.raises(ValueError):agent.select(SPECS, REFS, excluded=list(REFS))


def test_spec_check_and_parameter_table_helpers():
    rows = spec_check({'a': {'min': 5}, 'b': {'max': 2}, 'c': {'min': 1}}, {'a': 5.0, 'b': 3.0, 'c': None})
    assert rows['a']['passed'] and rows['b']['passed'] is False and rows['c']['passed'] is None
    text = REFS[TWO].text.replace('.param W_IN=10 ', '.param W_IN=100')
    table = parameter_table(text, parse_bounds(text))
    row = {r[0]: r for r in table['rows']}
    assert row['W_IN'][-1] == 'max' and row['L_IN'][-1] == '' and 'RSH_RZ' not in row


def test_revision_advice_is_built_from_the_evidence_not_from_the_model():
    evidence = {'spec_check': {'ugb_hz': {'target': {'min': 4.5e7}, 'value': 1.9e7, 'passed': False},
                               'power_w': {'target': {'max': 4e-4}, 'value': 1e-4, 'passed': True}},
                'final': {'simulation_valid': True, 'dc_passed': True},
                'parameters': {'rows': [['CC', '10p', 0.1e-12, 1e-11, 'F', 'max'], ['W_IN', '10', 1, 100, 'um', '']]}}
    agent = ReviewAgent(ScriptedClient([dict(verdict='fail_sizing')]))
    reply = agent.review(evidence)
    assert reply['revision_advice'].startswith('Failing: ugb_hz 19000000 (need min 45000000).')
    assert reply['diagnosis'] == 'Not met: ugb_hz 19000000 (need min 45000000).'
    assert 'CC at its max (can only go down)' in reply['revision_advice'] and 'Never moved in the last run: CC, W_IN.' in reply['revision_advice'] and 'power_w' not in reply['revision_advice']
    assert reply['restart_sizing_from_reference'] is False


def test_each_round_records_only_its_own_model_calls(env):
    """Regression: the clients keep the calls of every round, and round files used to contain all of them."""
    env.script([pick(TWO), pick(FOLD)], [SIZE]*10 + [SIZE], [review('fail_topology'), review('pass')], [BAD]*11 + [BAD, GOOD])
    status, s = env.run()
    results = env.base/'results'
    load = lambda name: json.loads((results/name).read_text())
    assert [len(load(f'round_0{n}/sizing_calls.json')) for n in (1, 2)] == [10, 1]
    assert [len(load(f'round_0{n}/review_calls.json')) for n in (1, 2)] == [1, 1]
    assert [len(load(f'round_0{n}/topology_calls.json')) for n in (1, 2)] == [1, 1]
    assert [load(f'round_0{n}/summary.json')['call_count'] for n in (1, 2)] == [10, 1]
    assert [load(f'round_0{n}/summary.json')['tokens']['total_tokens'] for n in (1, 2)] == [150, 15]
    assert s['calls_by_agent'] == {'topology': 2, 'sizing': 11, 'review': 2} and s['tokens']['total_tokens'] == 15*15


def story_text(monkeypatch, results, language):
    """Everything the PDF would contain, taken from the platypus story (no PDF parser needed)."""
    from simulator import report_generator
    captured = []
    monkeypatch.setattr(report_generator.SimpleDocTemplate, 'build', lambda self, story, **kw: captured.extend(story))
    try:
        report_generator.generate(results, language)
    except OSError:
        pytest.skip('the report fonts are not installed')
    text = []
    for item in captured:
        if hasattr(item, 'getPlainText'):
            text.append(item.getPlainText())
        elif hasattr(item, 'lines'):
            text.append('\n'.join(item.lines))
        elif hasattr(item, '_cellvalues'):
            text += [cell.getPlainText() for row in item._cellvalues for cell in row]
    return '\n'.join(text)


@pytest.mark.parametrize('language,words', [
    ('en', ['unity negative feedback closed from OUT to VINP', 'T=-V(out)/V(injected)', 'Closed loop: V(out) - VCM = 0 V (limit 0.05 V): regulated']),
    ('zh', ['单位负反馈', 'T=-V(out)/V(注入)', '闭环：V(out) - VCM = 0 V（限值 0.05 V）：已稳在 VCM'])])
def test_report_describes_the_closed_loop_bench_the_run_used(env, monkeypatch, language, words):
    env.script([pick(TWO)], [], [review('pass')], [GOOD])
    env.run()
    text = story_text(monkeypatch, env.base/'results', language)
    assert all(w in text for w in words) and 'L=-A' not in text


def test_report_flags_a_loop_that_does_not_hold_the_output_at_vcm(env, monkeypatch):
    env.script([pick(TWO)], [], [review('pass')], [GOOD])
    env.run()
    results = env.base/'results'
    record = results/'round_01/logs/simulation_002.json'
    data = json.loads(record.read_text())
    data['dc_passed'] = False
    data['dc_acceptance']['loop'] = dict(passed=False, output_error_v=-0.5088, maximum_output_error_v=0.05)
    record.write_text(json.dumps(data))
    assert 'Closed loop: V(out) - VCM = -0.5088 V (limit 0.05 V): NOT regulating' in story_text(monkeypatch, results, 'en')
    assert '未稳在 VCM' in story_text(monkeypatch, results, 'zh')


def test_report_keeps_the_open_loop_wording_for_results_recorded_before_the_closed_loop_bench(env, monkeypatch):
    env.script([pick(TWO)], [], [review('pass')], [GOOD])
    env.run()
    results = env.base/'results'
    record = results/'round_01/logs/simulation_002.json'
    data = json.loads(record.read_text())
    del data['bias']
    record.write_text(json.dumps(data))
    text = story_text(monkeypatch, results, 'en')
    assert 'L=-A' in text and 'unity negative feedback closed from' not in text


def test_baseline_only_report_says_that_no_model_was_called(env, monkeypatch):
    FakeRunner.queue = [GOOD]
    assert main.run(baseline_only=True, only_reference=TWO) == 0
    results = env.base/'results'
    assert 'No model was called' in story_text(monkeypatch, results, 'en') and '未调用模型' in story_text(monkeypatch, results, 'zh')


def test_profile_is_reflowed_into_one_line_per_item():
    from simulator.report_generator import reflow
    profile = 'TOPOLOGY: a\nFAMILY: single stage,\nVB_X, VB_Y as parameters.\nADVANTAGES\n- first bullet\n  continued here\n- second\nBEST WHEN: x\ny'
    assert reflow(profile) == ['TOPOLOGY: a', 'FAMILY: single stage, VB_X, VB_Y as parameters.', 'ADVANTAGES',
                               '- first bullet continued here', '- second', 'BEST WHEN: x y']


def test_every_reference_gets_a_wired_schematic_with_all_devices_and_nets_and_stacks_read_top_down():
    from reportlab.graphics.shapes import Line, String
    from simulator.report_generator import schematic
    from analog_agents.spice import circuit_nodes, parameters
    for rid, ref in REFS.items():
        drawing = schematic(ref.text, parameters(ref.text))
        words = {s.text for s in drawing.contents if isinstance(s, String)}
        assert all(any(w == d for w in words) for d in ref.devices), rid
        nets = set(circuit_nodes(ref.text)) - {'vdd'}
        assert all(any(w == n for w in words) for n in nets), rid
        assert sum(isinstance(s, Line) for s in drawing.contents) > 6 * len(ref.devices), rid
    ref = REFS['telescopic_cascode_nmos_input']
    y = {s.text: s.y for s in schematic(ref.text, parameters(ref.text)).contents if isinstance(s, String)}
    assert y['XMP1'] > y['XML1'] > y['XMC1'] > y['XM1'] > y['XMTAIL']


def test_every_round_is_remembered_and_the_next_sizing_call_reads_the_memory(env):
    env.script([pick(TWO)], [W_IN_UP] + [SIZE]*9 + [SIZE], [review('fail_sizing'), review('pass')], [BAD]*11 + [BAD, GOOD])
    status, s = env.run()
    sizing = env.clients['sizing'].payloads
    assert 'memory' not in sizing[0]                                          # nothing was stored before round 1
    memory = sizing[10]['memory']                                             # round 2 reads what round 1 stored
    assert memory['cols'].startswith('dc_gain_db') and any(r.startswith('F 40') and 'W_IN=12' in r for r in memory['rows'])
    text = (env.base.parent/'design_memory.txt').read_text()
    assert f'[opamp/{TWO}]' in text
    assert text.splitlines()[-1] == 'P 70 20 70 200' and '\nF ' not in text    # round 2's passing start point replaced its near-duplicate F rows
    assert s['status'] == 'targets_passed'


def test_reference_tags_limit_the_structures_offered_to_the_topology_agent(env):
    specs = dict(SPECS, reference_tags=['cascode'])
    (env.base/'specs/target.json').write_text(json.dumps(specs))
    env.script([pick(FOLD)], [], [review('pass')], [GOOD])
    env.run()
    offered = [c['id'] for c in env.clients['topology'].payloads[0]['candidates']]
    assert offered and len(offered) == 4 and all('cascode' in i for i in offered) and TWO not in offered
    (env.base/'specs/target.json').write_text(json.dumps(dict(SPECS, reference_tags=['nothing_like_this'])))
    with pytest.raises(ValueError):
        main.run()
