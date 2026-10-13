"""The deterministic scaffolding around the model: clamping, no repeated points, rollback, best point, tables, handbook."""
from types import SimpleNamespace
from agents.sizing_agent.agent import schema, tunable_table
from agents.sizing_agent.loop import optimize
from analog_agents.rules import select_sections, RULES_PATH
import pytest
from analog_agents.search import (MAX_JUMPS, clamp, effective, fill_old, from_unit, history_table, jump_changes, point_key,
                                  shortfall, to_unit)
from analog_agents.spice import number, parameters
from helpers import REF, TARGET

BOUNDS = TARGET['optimization']['parameter_bounds']
NAMES = list(TARGET['optimization']['allowed_parameters'])


def change(parameter, value):
    return dict(parameter=parameter, new_value=value, reason='fixture')


class Script:
    """Agent fixture: answers from a queue and remembers what it was shown."""
    def __init__(self, proposals):
        self.proposals, self.client, self.calls = list(proposals), SimpleNamespace(calls=[]), []

    def run(self, target, candidate, measurement, history, feedback=None, rejections=None):
        self.client.calls.append({'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
        self.calls.append(dict(candidate=candidate, measurement=measurement, rejections=list(rejections or [])))
        changes = self.proposals.pop(0) if self.proposals else []
        return {'analysis': {'simulation_valid': True, 'dc_op_valid': True, 'main_problem': 'fixture'}, 'changes': changes}


class WidthRunner:
    """DC fails for W_IN >= dc_limit; gain = 60 - 10*|W_IN-12| + 5*(CC in pF - 1): the 60 dB target needs W_IN = 12."""
    def __init__(self, dc_limit=50):
        self.n, self.dc_limit = 0, dc_limit

    def run(self, candidate, mode):
        self.n += 1
        params = parameters(candidate.read_text())
        w, cc = number(params['W_IN']), number(params['CC'])/1e-12
        passed = w < self.dc_limit
        metrics = dict(dc_gain_db=60-abs(w-12)*10+5*(cc-1), ugb_hz=2e7, phase_margin_deg=70.0, power_w=1e-4) if passed and mode == 'full' \
            else dict(dc_gain_db=None, ugb_hz=None, phase_margin_deg=None, power_w=1e-4)
        return dict(dc_passed=passed, all_targets_passed=False, simulation_number=self.n, metrics=metrics,
                    dc_acceptance={'failed_devices': [] if passed else ['XM7']}, analysis_mode=mode,
                    simulation_valid=True, return_code=0, warnings=[], errors=[])


def run_loop(tmp_path, proposals, runner=None):
    candidate = tmp_path/'candidate.spice'
    candidate.write_text(REF)
    agent, state, history = Script(proposals), {'dc_iterations': 0}, []
    status = optimize(runner or WidthRunner(), agent, candidate, REF, TARGET, tmp_path, history, state)
    return status, agent, state, history, candidate


def test_values_outside_the_tune_range_are_moved_onto_it_and_integers_rounded():
    changes, notes = clamp(BOUNDS, [change('W_IN', '500'), change('N_TAIL', '2.6'), change('CC', '1p'), change('N_TAIL', '99')])
    assert [c['new_value'] for c in changes] == ['100', '3', '1p', '20'] and len(notes) == 3 and 'tune range 1..100' in notes[0]


def test_old_value_is_filled_in_and_a_no_op_is_dropped():
    changes = fill_old(parameters(REF), [change('W_IN', '10.0'), change('CC', '2p')])
    assert [c['old_value'] for c in changes] == ['10', '1p'] and [c['parameter'] for c in effective(changes)] == ['CC']


def test_sizing_schema_names_only_tunable_parameters_and_has_no_old_value():
    item = schema(NAMES)['properties']['changes']['items']
    assert item['properties']['parameter']['enum'] == NAMES and 'old_value' not in item['properties']
    assert list(schema(NAMES)['properties']) == ['changes', 'analysis'] and 'maxLength' not in str(schema(NAMES))


def test_a_point_that_was_already_simulated_is_refused_and_the_model_is_asked_again(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '12')], [change('W_IN', '10')], [change('W_IN', '14')]])
    second = history[1]
    assert second['accepted'] and second['changes'][0]['new_value'] == '14' and second['changes'][0]['old_value'] == '12'
    assert 'already simulated' in second['rejected_attempts'][0]['error'] and len(second['rejected_attempts']) == 1
    assert agent.calls[2]['rejections'] and not agent.calls[1]['rejections']
    assert second['token_usage']['total_tokens'] == 4          # both asks are counted


def test_a_step_that_breaks_a_passing_dc_is_undone_and_never_repeated(tmp_path):
    runner = WidthRunner()
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '60')], [change('W_IN', '60')], [change('W_IN', '20')]], runner)
    first = history[0]
    assert first['rolled_back'] and not first['result']['dc_passed'] and first['phase'] == 'performance'
    assert parameters(candidate.read_text())['W_IN'] == '10'                   # the run ends on its best point, the start
    assert state['dc_iterations'] == 0                                         # no DC-repair budget was used
    assert agent.calls[1]['candidate'] == REF and agent.calls[1]['measurement']['dc_passed']
    assert 'already made the result worse' in history[1]['rejected_attempts'][0]['error']   # that direction is closed
    table = history_table(history[:1])
    assert table['current_step'] == 'start' and 'reverted' in table['rows'][1][table['columns'].index('dc')]
    assert 'broke DC' in table['notes'][-1]


def test_a_run_that_ends_hands_over_its_best_point(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '12')], [change('W_IN', '30')]])
    assert status == 'max_iterations_reached'
    assert parameters(candidate.read_text())['W_IN'] == '12' and state['best']['text'] == candidate.read_text()
    assert state['measurement']['simulation_number'] == state['best']['simulation_number']


def test_history_table_lists_only_varied_parameters_and_the_current_step(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '12')], [change('CC', '2p')]])
    table = history_table(history[:2])
    assert table['columns'][:4] == ['step', 'W_IN', 'CC', 'dc'] and len(table['rows']) == 3 and table['current_step'] == 2
    assert table['rows'][0][:3] == ['start', '10', '1p'] and table['rows'][2][:3] == [2, '12', '2p']
    assert history_table([]) is None


def test_shortfall_and_point_key():
    targets = {'g': {'min': 60}, 'p': {'max': 1.0}}
    assert shortfall(targets, {'g': 70, 'p': 0.5}) == 0 and abs(shortfall(targets, {'g': 30, 'p': 2.0}) - 1.5) < 1e-12
    assert shortfall(targets, {'g': None, 'p': 0.5}) is None
    assert point_key(REF, NAMES) == point_key(REF.replace('CC=1p ', 'CC=1.0p'), NAMES)


def test_tunable_table_has_current_values_and_ranges():
    rows = {r[0]: r for r in tunable_table(REF, TARGET)['rows']}
    assert rows['W_IN'][1:4] == ['10', 1, 100] and rows['N_TAIL'][-1].startswith('int') and rows['R_RZ'][1] == '1000'


def test_handbook_sections_are_selected_by_number_and_the_phase_sections_exist():
    content = RULES_PATH.read_text(encoding='utf-8')
    dc = select_sections(content, (3, 12))
    assert '## 3.' in dc and '## 12.' in dc and '## 9.' not in dc and dc.startswith('# ')
    assert select_sections(content, True) == content
    from agents.sizing_agent.agent import DC_SECTIONS, PERFORMANCE_SECTIONS
    assert len(select_sections(content, DC_SECTIONS)) < len(select_sections(content, PERFORMANCE_SECTIONS)) < len(content)


def test_a_step_that_worsens_the_targets_is_undone_and_its_direction_closed(tmp_path):
    # gain at the start is 40; W_IN 30 is worse -> undone, raising W_IN is then refused and the model asks again
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '30')], [change('W_IN', '31')], [change('CC', '2p')]])
    first, second = history[:2]
    assert first['effect'].startswith('worse') and first['rolled_back'] and 'point' in first
    assert 'already made the result worse' in second['rejected_attempts'][0]['error']
    assert second['changes'][0]['new_value'] == '2p' and second['effect'] == 'better' and not second.get('rolled_back')
    assert agent.calls[1]['candidate'] == REF                      # the model edited the restored point


def test_an_improvement_reopens_closed_directions(tmp_path):
    proposals = [[change('W_IN', '30')], [change('CC', '2p')], [change('W_IN', '30')]]
    status, agent, state, history, candidate = run_loop(tmp_path, proposals)
    assert history[0]['rolled_back'] and history[1]['effect'] == 'better'
    assert history[2]['changes'][0]['new_value'] == '30' and 'rejected_attempts' not in history[2]   # allowed again


def test_history_table_has_the_effect_of_every_step(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '30')], [change('CC', '2p')]])
    table = history_table(history[:2])
    effect = table['columns'].index('vs_previous')
    assert [r[effect] for r in table['rows']] == ['', 'worse (DC fail)', 'better'] or [r[effect] for r in table['rows']] == ['', 'worse', 'better']
    assert any('previous point was restored' in n for n in table['notes'])


def test_refusals_cost_nothing_up_to_the_allowance_and_do_not_resimulate(tmp_path):
    runner = WidthRunner(dc_limit=0)                                # DC never passes: DC repair, where there is no fallback
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '10')]] * 40, runner)
    assert [bool(r.get('free')) for r in history[:5]] == [True, True, True, False, False]
    assert runner.n == 1                                            # only the start point was ever simulated
    assert len([r for r in history if not r.get('free')]) == 5 and status == 'dc_iteration_limit'


def test_the_model_is_not_asked_a_third_time_after_it_repeats_a_refused_proposal(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, [[change('W_IN', '10')]] * 40, WidthRunner(dc_limit=0))
    assert len(agent.calls) == 2 * len(history)                      # 2 asks per decision (the second was a repeat)
    assert all('try_instead' in a for r in history for a in r['rejected_attempts'])


class AnyChangeIsWorse(WidthRunner):
    """gain = 40 - 2 * (total log-distance of every tunable parameter from its start value); DC fails if some parameter
    moved by more than `dc_factor` (None: never)."""
    def __init__(self, dc_factor=None):
        super().__init__()
        self.dc_factor, self.start = dc_factor, {k: number(v) for k, v in parameters(REF).items() if k in NAMES}

    def run(self, candidate, mode):
        import math
        self.n += 1
        params = parameters(candidate.read_text())
        dist = [abs(math.log(number(params[k])/v)) for k, v in self.start.items()]
        passed = self.dc_factor is None or max(dist) < math.log(self.dc_factor)
        metrics = dict(dc_gain_db=40-2*sum(dist), ugb_hz=2e7, phase_margin_deg=70.0, power_w=1e-4) if passed and mode == 'full' \
            else dict(dc_gain_db=None, ugb_hz=None, phase_margin_deg=None, power_w=1e-4)
        return dict(dc_passed=passed, all_targets_passed=False, simulation_number=self.n, metrics=metrics,
                    dc_acceptance={'failed_devices': [] if passed else ['XM7']}, analysis_mode=mode,
                    simulation_valid=True, return_code=0, warnings=[], errors=[])


THREE_WORSE = [[change('W_IN', '11')], [change('CC', '1.1p')], [change('L_IN', '0.55')]]


def test_three_undone_steps_in_a_row_trigger_a_large_jump_without_the_model(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, THREE_WORSE, AnyChangeIsWorse())
    assert [bool(r.get('rolled_back')) for r in history[:3]] == [True, True, True]
    jumped = history[3]
    assert jumped['phase'] == 'explore' and jumped['accepted'] and not jumped.get('rolled_back') and jumped['effect'] == 'jump'
    assert 1 <= len(jumped['changes']) <= 3 and jumped['token_usage']['total_tokens'] == 0
    assert len(agent.calls) == 3 + (len(history) - 4)                  # the model was not asked for the jump itself
    assert agent.calls[3]['candidate'] != REF                         # it edits the new region afterwards
    for c in jumped['changes']:                                       # every moved parameter went far (>= 15% of its range)
        b = BOUNDS[c['parameter']]
        assert abs(to_unit(b, number(c['new_value'])) - to_unit(b, number(c['old_value']))) >= 0.15 - 1e-9


def test_a_run_ends_on_its_best_point_after_a_jump_and_jumps_are_limited(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, THREE_WORSE * 6, AnyChangeIsWorse())
    assert parameters(candidate.read_text())['W_IN'] == '10' and parameters(candidate.read_text())['CC'] == '1p'   # the start
    assert len([r for r in history if r['phase'] == 'explore']) <= MAX_JUMPS


def test_a_jump_must_pass_dc_and_failing_to_find_one_resumes_the_climb(tmp_path):
    status, agent, state, history, candidate = run_loop(tmp_path, THREE_WORSE, AnyChangeIsWorse(dc_factor=1.0000001))
    # any change at all fails DC -> in the climb every step is DC-fail+undone, and no DC-valid jump exists
    explore = [r for r in history if r['phase'] == 'explore']
    assert explore and not explore[0]['accepted'] and explore[0]['validation_error'] == 'no DC-valid large jump found'
    assert candidate.read_text() == REF
    table = history_table(history)
    assert any('no DC-valid point for a large jump' in n for n in table['notes'])


def test_an_improvement_resets_the_count_of_undone_steps(tmp_path):
    proposals = [[change('W_IN', '30')], [change('CC', '2p')], [change('W_IN', '30')], [change('L_IN', '0.55')]]
    status, agent, state, history, candidate = run_loop(tmp_path, proposals)        # WidthRunner: CC 2p improves
    assert not any(r['phase'] == 'explore' for r in history)


def test_jump_changes_move_each_parameter_far_inside_its_range_and_respect_integers():
    import random
    rng = random.Random(3)
    for _ in range(50):
        changes = jump_changes(rng, BOUNDS, parameters(REF), 0.35)
        assert 1 <= len(changes) <= 3
        for c in changes:
            b, x = BOUNDS[c['parameter']], number(c['new_value'])
            assert b['min'] - 1e-9 <= x <= b['max'] + 1e-9 and (not b['integer'] or x == int(x))
    assert from_unit(BOUNDS['CC'], 0.5) == pytest.approx((0.1e-12*10e-12)**0.5)       # wide ranges are logarithmic
