"""Toolchain moves around the model: lever fallback, remembered designs tried whole, seeded jumps."""
import pytest
from agents.sizing_agent.loop import optimize
from analog_agents.search import history_table, move_text, open_moves, step_change
from analog_agents.spice import number, parameters
from helpers import REF, TARGET
from test_search import AnyChangeIsWorse, BOUNDS, NAMES, Script, THREE_WORSE, WidthRunner, change, run_loop

GOOD_DESIGN = ('P', dict(dc_gain_db=60.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=1e-4),
               {**{k: v for k, v in parameters(REF).items() if k in NAMES}, 'W_IN': '12'})


def run_with_memory(tmp_path, proposals, memory_points, seed=0, runner=None):
    candidate = tmp_path/'candidate.spice'
    candidate.write_text(REF)
    agent, state, history = Script(proposals), {'dc_iterations': 0}, []
    status = optimize(runner or WidthRunner(), agent, candidate, REF, TARGET, tmp_path, history, state,
                      memory_points=memory_points, seed=seed)
    return status, agent, state, history, candidate


def test_when_the_model_has_nothing_usable_the_toolchain_steps_the_next_open_lever(tmp_path):
    # start gain is 40 (target 60): the reference's levers for dc_gain_db are L_IN, L_STAGE2, L_LOAD (all "+")
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '10')]] * 40)
    first = history[0]
    assert first['fallback'] and first['accepted'] and not first.get('free') and 'point' in first
    assert first['changes'][0]['parameter'] == 'L_IN' and number(first['changes'][0]['new_value']) == pytest.approx(0.75)
    assert [r['changes'][0]['parameter'] for r in history if r.get('fallback')] == ['L_IN', 'L_STAGE2', 'L_LOAD']
    assert any('stepped the next untried lever' in n for n in history_table(history[:1])['notes'])


def test_open_moves_follow_the_levers_of_the_worst_missed_metric_and_skip_tried_and_closed():
    levers = TARGET['levers']
    metrics = dict(dc_gain_db=75.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=1e-4)
    moves = open_moves(levers, {'ugb_hz': {'min': 4e7}, 'phase_margin_deg': {'min': 78}}, metrics, [], set(), NAMES)
    assert [m[:2] for m in moves][:5] == [('IBIAS', 1), ('W_IN', 1), ('N_TAIL', 1), ('N_STAGE2_BIAS', 1), ('CC', -1)]   # UGB misses most
    assert ('R_RZ', 1) in [m[:2] for m in moves] and move_text(moves[:2]) == 'raise IBIAS (for ugb_hz), raise W_IN (for ugb_hz)'
    ugb = {'ugb_hz': {'min': 4e7}}
    assert ('IBIAS', 1) not in [m[:2] for m in open_moves(levers, ugb, metrics, [], {('IBIAS', 1)}, NAMES)]
    history = [dict(point={}, changes=[dict(parameter='W_IN', old_value='10', new_value='12')])]
    assert ('W_IN', 1) not in [m[:2] for m in open_moves(levers, ugb, metrics, history, set(), NAMES)]
    assert open_moves({}, ugb, metrics, history, set(), NAMES)[0][:2] == ('L_IN', 1)      # no levers: a never-moved parameter


def test_step_change_sizes():
    params = parameters(REF)
    assert number(step_change(BOUNDS, params, 'IBIAS', 1)['new_value']) == pytest.approx(30e-6, rel=1e-3)   # wide range: x1.5
    assert step_change(BOUNDS, params, 'N_TAIL', 1)['new_value'] == '2' and step_change(BOUNDS, params, 'N_TAIL', -1) is None
    assert number(step_change(BOUNDS, params, 'L_IN', 1)['new_value']) == pytest.approx(0.75)


def test_a_remembered_design_that_met_the_targets_is_tried_whole_first_without_the_model(tmp_path):
    status, agent, state, history, candidate = run_with_memory(tmp_path, [], [GOOD_DESIGN])
    first = history[0]
    assert first['phase'] == 'memory' and first['effect'] == 'better' and not first.get('rolled_back')
    assert [c['parameter'] for c in first['changes']] == ['W_IN'] and first['token_usage']['total_tokens'] == 0
    assert agent.calls[0]['candidate'] != REF and any('remembered design' in n for n in history_table(history[:1])['notes'])


def test_a_remembered_design_that_does_not_verify_is_undone_and_does_not_count_as_a_failed_step(tmp_path):
    bad = ('P', GOOD_DESIGN[1], {**GOOD_DESIGN[2], 'W_IN': '30'})            # the runner measures gain -120 there
    status, agent, state, history, candidate = run_with_memory(tmp_path, [[change('CC', '2p')]], [bad])
    assert history[0]['phase'] == 'memory' and history[0]['rolled_back'] and history[1]['phase'] == 'performance'
    assert history[1]['effect'] == 'better'                                  # the model then continued from the restored start


def test_remembered_points_close_revisits_with_their_known_outcome(tmp_path):
    seen = ('F', dict(dc_gain_db=45.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=1e-4), {**GOOD_DESIGN[2], 'W_IN': '14'})
    status, agent, state, history, candidate = run_with_memory(tmp_path, [[change('W_IN', '14')], [change('CC', '2p')]], [seen])
    error = history[0]['rejected_attempts'][0]['error'] if history[0].get('rejected_attempts') else history[0]['validation_error']
    assert 'already simulated' in error and '45.0' in error


def test_jumps_differ_with_the_seed(tmp_path):
    def first_jump(seed, sub):
        d = tmp_path/sub
        d.mkdir()
        history = run_with_memory(d, THREE_WORSE, [], seed, AnyChangeIsWorse())[3]
        return [(c['parameter'], c['new_value']) for c in next(r for r in history if r['phase'] == 'explore')['changes']]
    same, again, other = first_jump(0, 'a'), first_jump(0, 'b'), first_jump(1, 'c')
    assert same == again and same != other and len(same) <= 2                                       # a jump moves at most two parameters
