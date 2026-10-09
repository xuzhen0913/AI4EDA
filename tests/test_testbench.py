import pytest
from simulator.testbench import check_circuit, deck, describe
from helpers import REF, REFS, SPECS

LIB = '/lib/sky130.lib.spice'


def statements(text):
    return [l for l in text.splitlines() if l.strip() and not l.startswith('*')]


def test_deck_is_circuit_plus_generated_testbench_and_identical_across_references():
    for rid, ref in REFS.items():
        full = deck(ref.text, SPECS, LIB, 'full').splitlines()
        assert full[0].startswith('* op-amp testbench') and full[-1] == '.end' and full.count('.end') == 1, rid
        assert full.index(f'.lib "{LIB}" tt') < full.index('.control') and 'VSUPPLY vdd 0 {VDD}' in full
        for line in ('meas ac ugb_hz WHEN gain=0 FALL=1', 'meas ac loop_real_lf FIND loop_real AT=1', 'print phase_margin_deg'):
            assert line in full
        # every MOS gets all seven properties printed; every node gets its voltage
        assert sum(l.startswith('print @m.') for l in full) == 7*len(ref.devices), rid


def test_dc_mode_has_no_ac():
    text = deck(REF, SPECS, LIB, 'dc')
    assert 'ac dec' not in text and 'meas ac' not in text and 'echo END_DC_OPERATING_POINT' in text
    with pytest.raises(ValueError):deck(REF, SPECS, LIB, 'tran')


def test_conditions_come_from_the_specs_only():
    changed = {**SPECS, 'conditions': {**SPECS['conditions'], 'vdd_v': 1.2, 'load_capacitance_f': 5e-12, 'temperature_c': 85}}
    text = deck(REF, changed, LIB, 'dc')
    assert '.param VDD=1.2' in text and '.param CLOAD=5e-12' in text and '.temp 85' in text
    assert '1.8' not in describe(changed).split('Supply')[1].split('V on node')[0]


@pytest.mark.parametrize('bad,message', [
    ('.lib "x" tt\n', 'testbench'), ('.temp 27\n', 'testbench'), ('.end\n', 'testbench'),
    ('VSUPPLY vdd 0 1.8\n', 'generated'), ('CLOAD_OUT out 0 1p\n', 'generated'), ('.param VDD=1.8\n', 'defined by the shared testbench')])
def test_a_reference_must_not_carry_testbench_statements(bad, message):
    with pytest.raises(ValueError, match=message):check_circuit(REF + '\n' + bad)


def test_circuit_must_use_the_four_ports():
    with pytest.raises(ValueError, match='ports'):check_circuit('R1 a b 1k\n')
