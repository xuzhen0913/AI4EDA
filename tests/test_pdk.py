"""A few real SKY130/ngspice simulations of library circuits through the shared closed-loop testbench
(opt-in, about 3 minutes in total: `pytest -m pdk`).

They guard what the unit tests cannot: that the generated deck works on the real PDK and that the declared feedback
inputs, the verified designs quoted in the profiles and the closed-loop bias still behave as documented.
"""
import subprocess
import pytest
from agents.sizing_agent.loop import evaluate
from analog_agents.reference import design_target
from analog_agents.spice import PARAM
from simulator.ngspice_runner import NgspiceRunner, parse_log, tool_paths
from simulator.testbench import deck
from helpers import REFS, SPECS

pytestmark = pytest.mark.pdk

TWO = 'two_stage_nmos_input_pmos_stage2'
FIRST = dict(W_STAGE2='23', R_RZ='7k')
SECOND = dict(W_STAGE2='69', N_STAGE2_BIAS='3', IBIAS='35u', CC='0.65p', R_RZ='5k')
FOLDED_POINT = dict(VBN_TAIL='0.74', VBN_CAS='0.73', VBP_CAS='0.24', VBP_FOLD='0.55')
# found by an ngspice-only bias search: the loop holds out at VCM, weak inversion (only the overdrive criterion fails)
FOLDED_PMOS_POINT = dict(L_IN='0.15', L_TAIL='0.15', W_IN='44.58', W_TAIL='41.93', W_FOLD='25.45', W_CAS='24.6', W_LOAD='8.06',
                         VBP_TAIL='1.065', VBN_FOLD='0.591', VBN_CAS='0.787', VBP_CAS='0.993')


def measure(tmp_path, rid, changes, feedback=None):
    try:
        tool_paths()
    except (FileNotFoundError, StopIteration):
        pytest.skip('ngspice or the SKY130 library is not installed')
    target = design_target(SPECS, REFS[rid])
    if feedback:
        target['feedback_input'] = feedback
    text = PARAM.sub(lambda m: m[1]+m[2]+m[3]+changes.get(m[2], m[4])+m[5], REFS[rid].text)
    candidate = tmp_path/'candidate.spice'
    candidate.write_text(text)
    return evaluate(NgspiceRunner(tmp_path, target), candidate)


def test_the_baseline_two_stage_passes_dc_with_the_output_held_at_vcm(tmp_path):
    m = measure(tmp_path, TWO, {})
    assert m['dc_passed'] and m['simulation_valid'] and m['dc_acceptance']['loop']['output_error_v'] == pytest.approx(0, abs=1e-3)
    assert m['metrics']['dc_gain_db'] == pytest.approx(75.0, abs=0.5)
    assert m['metrics']['phase_margin_deg'] == pytest.approx(24.1, abs=1.0)         # only PM fails: the series R is too small


@pytest.mark.parametrize('changes,gain,ugb_mhz,pm', [(FIRST, 74.6, 22.1, 63.3), (SECOND, 73.3, 99.1, 71.0)])
def test_the_two_verified_two_stage_designs_quoted_in_the_profile(tmp_path, changes, gain, ugb_mhz, pm):
    m = measure(tmp_path, TWO, changes)
    assert m['all_targets_passed']
    assert m['metrics']['dc_gain_db'] == pytest.approx(gain, abs=0.3)
    assert m['metrics']['ugb_hz']/1e6 == pytest.approx(ugb_mhz, rel=0.02)
    assert m['metrics']['phase_margin_deg'] == pytest.approx(pm, abs=1.0)


def test_declaring_the_other_input_is_caught_by_the_sign_of_the_loop_gain(tmp_path):
    m = measure(tmp_path, TWO, FIRST, feedback='vinn')
    assert not m['simulation_valid'] and m['ac_polarity']['loop_real_lf'] < 0
    assert any('wrong feedback input' in e for e in m['errors'])


def test_the_folded_cascode_point_found_by_sizing_is_dc_and_ac_valid_on_vinn(tmp_path):
    m = measure(tmp_path, 'folded_cascode_nmos_input', FOLDED_POINT)
    assert m['dc_passed'] and m['simulation_valid'] and m['ac_polarity']['feedback_input'] == 'vinn'
    assert m['metrics']['dc_gain_db'] == pytest.approx(57.7, abs=0.4)
    assert m['metrics']['ugb_hz']/1e6 == pytest.approx(51.6, rel=0.03)
    assert m['metrics']['phase_margin_deg'] == pytest.approx(76.9, abs=1.0)         # not 256 deg: the loop polarity is right


def loop_gain(tmp_path, rid, changes, feedback):
    """The full deck, run directly: at a point that fails DC the sizing loop would stop before the AC analysis."""
    try:
        executable, library = tool_paths()
    except (FileNotFoundError, StopIteration):
        pytest.skip('ngspice or the SKY130 library is not installed')
    target = design_target(SPECS, REFS[rid])
    target['feedback_input'] = feedback
    text = PARAM.sub(lambda m: m[1]+m[2]+m[3]+changes.get(m[2], m[4])+m[5], REFS[rid].text)
    path = tmp_path/f'{rid}_{feedback}.sp'
    path.write_text(deck(text, SPECS, str(library), 'full', feedback))
    done = subprocess.run([str(executable), '-b', str(path)], capture_output=True, text=True, cwd=tmp_path, timeout=300)
    return parse_log(done.stdout, done.returncode, target, 'full')


@pytest.mark.parametrize('rid,changes', [('two_stage_pmos_input_nmos_stage2', {}), ('telescopic_cascode_nmos_input', {}),
                                         ('telescopic_cascode_pmos_input', {}), ('folded_cascode_pmos_input', FOLDED_PMOS_POINT)])
def test_the_declared_feedback_input_gives_a_positive_loop_gain_and_the_other_input_does_not(tmp_path, rid, changes):
    """Together with the two tests above this covers all six declarations. These points still fail some DC criterion (the
    loop holds out or has gain there), which is enough to read the sign of the loop gain."""
    declared = REFS[rid].feedback_input
    right = loop_gain(tmp_path, rid, changes, declared)
    wrong = loop_gain(tmp_path, rid, changes, 'vinn' if declared == 'vinp' else 'vinp')
    assert right['simulation_valid'] and right['ac_polarity']['loop_real_lf'] > 0 and right['metrics']['dc_gain_db'] > 20
    assert not wrong['simulation_valid'] and wrong['ac_polarity']['loop_real_lf'] < 0
