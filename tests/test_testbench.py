import subprocess
import pytest
from simulator.ngspice_runner import parse_log, tool_paths
from simulator.testbench import check_circuit, deck, describe
from helpers import REF, REFS, SPECS

LIB = '/lib/sky130.lib.spice'


def test_deck_is_circuit_plus_generated_testbench_and_identical_across_references():
    for rid, ref in REFS.items():
        full = deck(ref.text, SPECS, LIB, 'full', ref.feedback_input).splitlines()
        assert full[0].startswith('* op-amp testbench') and full[-1] == '.end' and full.count('.end') == 1, rid
        assert full.index(f'.lib "{LIB}" tt') < full.index('.control') and 'VSUPPLY vdd 0 {VDD}' in full
        for line in ('meas ac ugb_hz WHEN gain=0 FALL=1', 'meas ac loop_real_lf FIND loop_real AT=1', 'print phase_margin_deg',
                     'let loop_gain = -v(out)/v(acin)'):
            assert line in full
        # every MOS gets all seven properties printed; every node gets its voltage
        assert sum(l.startswith('print @m.') for l in full) == 7*len(ref.devices), rid


@pytest.mark.parametrize('feedback,held', [('vinp', 'vinn'), ('vinn', 'vinp')])
def test_dc_loop_is_closed_through_an_inductor_and_ac_sees_the_open_loop(feedback, held):
    lines = deck(REF, SPECS, LIB, 'full', feedback).splitlines()
    assert f'LFB out {feedback} 1e9' in lines                  # DC: short, so out = feedback input (unity feedback)
    assert 'VAC acin 0 DC 0 AC 1' in lines and f'CAC acin {feedback} 1e3' in lines    # AC: injected through a DC block
    assert f'{held.upper()} {held} 0 DC {{VCM}}' in lines      # the other input is a plain DC reference, named as the reserved element
    assert not any('AC 0.5' in l or 'AC -0.5' in l for l in lines)   # no differential AC drive any more
    assert '.nodeset v(out)=0.9' in lines
    assert lines.index('op') < lines.index('echo END_DC_OPERATING_POINT') < next(i for i, l in enumerate(lines) if l.startswith('ac dec'))


def test_feedback_input_must_be_one_of_the_two_inputs():
    with pytest.raises(ValueError, match='feedback_input'):deck(REF, SPECS, LIB, 'dc', 'out')


def test_dc_mode_has_no_ac():
    text = deck(REF, SPECS, LIB, 'dc', 'vinp')
    assert 'ac dec' not in text and 'meas ac' not in text and 'echo END_DC_OPERATING_POINT' in text
    assert 'LFB out vinp' in text                               # but the DC point is still the closed-loop one
    with pytest.raises(ValueError):deck(REF, SPECS, LIB, 'tran', 'vinp')


def test_conditions_come_from_the_specs_only():
    changed = {**SPECS, 'conditions': {**SPECS['conditions'], 'vdd_v': 1.2, 'load_capacitance_f': 5e-12, 'temperature_c': 85,
                                       'input_common_mode_v': 0.6}}
    text = deck(REF, changed, LIB, 'dc', 'vinp')
    assert '.param VDD=1.2' in text and '.param CLOAD=5e-12' in text and '.temp 85' in text and '.nodeset v(out)=0.6' in text
    assert '1.8' not in describe(changed).split('Supply')[1].split('V on node')[0]


def test_description_is_generated_from_the_same_facts_as_the_deck():
    text = describe(SPECS, 'vinn')
    assert 'closed from out to the vinn input' in text and 'injected at the vinn input' in text and 'T = -V(out)/V(injected)' in text
    assert f'within {SPECS["dc_acceptance"]["maximum_output_error_v"]} V' in text
    assert 'declared by each reference' in describe(SPECS)          # the topology agent sees no single circuit


@pytest.mark.parametrize('bad,message', [
    ('.lib "x" tt\n', 'testbench'), ('.temp 27\n', 'testbench'), ('.end\n', 'testbench'), ('.nodeset v(out)=1\n', 'testbench'),
    ('VSUPPLY vdd 0 1.8\n', 'generated'), ('CLOAD_OUT out 0 1p\n', 'generated'), ('LFB out vinp 1\n', 'generated'),
    ('CAC acin vinp 1\n', 'generated'), ('.param VDD=1.8\n', 'defined by the shared testbench'), ('R9 acin 0 1k\n', 'acin')])
def test_a_reference_must_not_carry_testbench_statements(bad, message):
    with pytest.raises(ValueError, match=message):check_circuit(REF + '\n' + bad)


def test_circuit_must_use_the_four_ports():
    with pytest.raises(ValueError, match='ports'):check_circuit('R1 a b 1k\n')


def simulate(tmp_path, source, feedback, mode='full', extra=''):
    """Real ngspice on a one-pole VCVS amplifier (gain 100, pole ~1 MHz), through the shared testbench."""
    try:
        executable, _ = tool_paths()
    except (FileNotFoundError, StopIteration):
        pytest.skip('ngspice is not installed')
    lib = tmp_path/'empty.lib'
    lib.write_text('.lib tt\n.endl tt\n')
    circuit = f'* ideal single-pole amplifier\n{extra}{source}\nR1 n1 out 1k\nC1 out 0 159p\n'
    path = tmp_path/'amp.sp'
    path.write_text(deck(circuit, SPECS, str(lib), mode, feedback))
    done = subprocess.run([str(executable), '-b', str(path)], capture_output=True, text=True, cwd=tmp_path, timeout=120)
    target = {'targets': SPECS['targets'], 'conditions': SPECS['conditions'], 'feedback_input': feedback,
              'dc_acceptance': {**SPECS['dc_acceptance'], 'devices': {}}, 'ac_validation': SPECS['ac_validation']}
    return parse_log(done.stdout, done.returncode, target, mode)


INVERTING_FROM_VINP, NON_INVERTING = 'E1 n1 0 vinn vinp 100', 'E1 n1 0 vinp vinn 100'


@pytest.mark.parametrize('source,feedback', [(INVERTING_FROM_VINP, 'vinp'), (NON_INVERTING, 'vinn')])
def test_the_loop_closed_on_the_declared_input_gives_the_right_phase_margin(tmp_path, source, feedback):
    """Whichever way the circuit inverts, closing the loop on its inverting input gives T positive at low frequency and PM ~ 90.6 deg
    (history: with the loop gain fixed as -A and no feedback input, a circuit whose output rises with vinp read PM = 270 deg)."""
    result = simulate(tmp_path, source, feedback)
    assert result['simulation_valid'] and result['ac_polarity']['passed'] and result['ac_polarity']['feedback_input'] == feedback
    assert result['bias'] == 'closed_loop' and result['dc_acceptance']['loop']['passed']
    assert result['metrics']['dc_gain_db'] == pytest.approx(40.0, abs=0.01)
    assert result['metrics']['ugb_hz'] == pytest.approx(98.9e6, rel=0.02)
    assert result['metrics']['phase_margin_deg'] == pytest.approx(90.6, abs=0.3)


@pytest.mark.parametrize('source,wrong', [(INVERTING_FROM_VINP, 'vinn'), (NON_INVERTING, 'vinp')])
def test_a_wrong_feedback_input_is_caught_by_the_sign_of_the_loop_gain(tmp_path, source, wrong):
    result = simulate(tmp_path, source, wrong)
    assert not result['simulation_valid'] and result['ac_polarity']['passed'] is False
    assert any('wrong feedback input' in e for e in result['errors'])


def test_zero_gain_is_invalid_and_says_why(tmp_path):
    result = simulate(tmp_path, 'E1 n1 0 vinp vinn 0', 'vinn')
    assert not result['simulation_valid'] and result['metrics']['ugb_hz'] is None
    assert any('below 0 dB' in e for e in result['errors'])


def test_the_closed_loop_holds_the_output_at_vcm_despite_gain_times_offset(tmp_path):
    """A 20 mV input offset times a gain of 1000 would put an open-loop output at 20 V; the loop keeps it within the window."""
    offset = 'VOFF vx vinn 20m\n'
    result = simulate(tmp_path, 'E1 n1 0 vx vinp 1000', 'vinp', mode='dc', extra=offset)
    loop = result['dc_acceptance']['loop']
    assert loop['passed'] and loop['output_error_v'] == pytest.approx(0.0199, abs=0.002)
    assert result['dc_operating_point']['v(out)'] == pytest.approx(0.92, abs=0.002)
