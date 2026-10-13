"""DC repair: remembered designs that passed DC, several coupled changes, DC levers, and the 'circuit is off' rule."""
import pytest
from agents.sizing_agent.loop import optimize
from analog_agents.search import circuit_is_off, dc_moves, history_table, open_moves
from analog_agents.spice import number, parameters
from helpers import REF, TARGET
from test_search import NAMES, Script, change

DEVICES = list(TARGET['dc_acceptance']['devices'])
GOOD = dict(dc_gain_db=60.0, ugb_hz=2e7, phase_margin_deg=70.0, power_w=1e-4)
DC_TARGET = dict(TARGET, levers={**TARGET['levers'], 'dc': {'W_IN': '+', 'L_IN': '-'}})


class OffRunner:
    """Every device fails DC while W_IN < threshold (the circuit is 'off'); above it everything passes."""
    def __init__(self, threshold=12):
        self.n, self.threshold = 0, threshold

    def run(self, candidate, mode):
        self.n += 1
        passed = number(parameters(candidate.read_text())['W_IN']) >= self.threshold
        metrics = dict(GOOD) if passed and mode == 'full' else dict(dc_gain_db=None, ugb_hz=None, phase_margin_deg=None, power_w=3e-7)
        return dict(dc_passed=passed, all_targets_passed=False, simulation_number=self.n, metrics=metrics,
                    dc_acceptance={'failed_devices': [] if passed else list(DEVICES)}, analysis_mode=mode,
                    simulation_valid=True, return_code=0, warnings=[], errors=[])


def run(tmp_path, proposals, memory_points=(), target=TARGET, runner=None):
    candidate = tmp_path/'candidate.spice'
    candidate.write_text(REF)
    agent, state, history = Script(proposals), {'dc_iterations': 0}, []
    status = optimize(runner or OffRunner(), agent, candidate, REF, target, tmp_path, history, state, memory_points=memory_points)
    return status, agent, state, history, candidate


def remembered(w_in):
    return ('F', dict(GOOD, dc_gain_db=50.0), {**{k: v for k, v in parameters(REF).items() if k in NAMES}, 'W_IN': w_in})


def test_a_remembered_design_that_passed_dc_is_tried_whole_while_dc_fails(tmp_path):
    status, agent, state, history, candidate = run(tmp_path, [], [remembered('14')])
    first = history[0]
    assert first['phase'] == 'memory' and first['repair'] and first['effect'] == 'better' and not first.get('rolled_back')
    assert [c['parameter'] for c in first['changes']] == ['W_IN'] and first['token_usage']['total_tokens'] == 0
    assert state['dc_iterations'] == 1                                         # it used one DC-repair decision
    assert history[1]['phase'] == 'performance' and agent.calls[0]['candidate'] != REF
    assert any('passed DC' in n for n in history_table(history[:1])['notes'])


def test_a_remembered_design_that_still_fails_dc_is_undone(tmp_path):
    status, agent, state, history, candidate = run(tmp_path, [[change('W_IN', '14')]], [remembered('11')])   # 11 < threshold
    first = history[0]
    assert first['phase'] == 'memory' and first['rolled_back'] and first['effect'] == 'worse (DC fail)'
    assert state['dc_iterations'] == 2 and history[1]['phase'] == 'dc_repair' and history[1]['accepted']   # the model then repaired DC


def test_dc_repair_allows_coupled_changes_but_performance_allows_one(tmp_path):
    status, agent, state, history, candidate = run(tmp_path, [[change('W_IN', '14'), change('CC', '2p')],
                                                                [change('CC', '1.5p'), change('L_STAGE2', '0.6')]] + [[]] * 10)
    first, second = history[0], history[1]
    assert first['phase'] == 'dc_repair' and len(first['changes']) == 2 and first['accepted']
    assert second['phase'] == 'performance' and 'at most 1 change' in second['rejected_attempts'][0]['error']


def test_when_the_model_has_nothing_usable_the_dc_levers_are_stepped_together(tmp_path):
    status, agent, state, history, candidate = run(tmp_path, [[change('CC', '2p')]] * 6, target=DC_TARGET)
    first = history[0]
    assert first['fallback'] and [c['parameter'] for c in first['changes']] == ['W_IN', 'L_IN']
    assert number(first['changes'][0]['new_value']) == pytest.approx(15) and number(first['changes'][1]['new_value']) == pytest.approx(0.5/1.5)
    assert first['result']['dc_passed'] and state['dc_iterations'] == 1


def test_sizes_are_refused_while_nothing_conducts_when_the_reference_names_bias_levers(tmp_path):
    status, agent, state, history, candidate = run(tmp_path, [[change('CC', '2p')], [change('W_IN', '14')]], target=DC_TARGET)
    first = history[0]
    assert first['accepted'] and first['changes'][0]['parameter'] == 'W_IN'                  # the second answer, a bias lever
    assert 'no device conducts' in first['rejected_attempts'][0]['error'] and 'raise W_IN (for DC)' in first['rejected_attempts'][0]['error']
    assert first['rejected_attempts'][0]['try_instead'].startswith('raise W_IN (for DC), lower L_IN (for DC)')


def test_without_dc_levers_nothing_changes_for_the_model_or_the_fallback(tmp_path):
    status, agent, state, history, candidate = run(tmp_path, [[change('CC', '2p')]] * 3)    # TARGET has no "dc" levers
    assert history[0]['accepted'] and history[0]['phase'] == 'dc_repair' and not history[0].get('fallback')
    assert dc_moves(TARGET['levers']) == [] and dc_moves(DC_TARGET['levers']) == [('W_IN', 1, 'DC'), ('L_IN', -1, 'DC')]


def test_open_moves_while_dc_fails_are_the_dc_levers_and_the_off_test():
    assert open_moves(DC_TARGET['levers'], TARGET['targets'], {}, [], set(), NAMES, dc_failed=True)[:2] == [('W_IN', 1, 'DC'), ('L_IN', -1, 'DC')]
    assert open_moves(DC_TARGET['levers'], TARGET['targets'], {}, [], {('W_IN', 1)}, NAMES, dc_failed=True)[0][:2] == ('L_IN', -1)
    off = dict(dc_passed=False, dc_acceptance=dict(failed_devices=list(DEVICES)))
    assert circuit_is_off(off, DEVICES) and not circuit_is_off(dict(off, dc_acceptance=dict(failed_devices=DEVICES[:2])), DEVICES)
    assert not circuit_is_off(dict(off, dc_passed=True), DEVICES)
