import math
import pytest
from analog_agents.spice import parameters
from analog_agents import analog_calc as ac
from analog_agents.reference import design_target
from helpers import REF, TARGET, REFS, SPECS


def test_formulas():
    assert math.isclose(ac.sheet_resistor(100, 10, 1), 1000)
    assert ac.zero_hz(1 / 3000, 1e-12, 1000) > 0          # R < 1/gm -> RHP
    assert ac.zero_hz(1 / 3000, 1e-12, 5000) < 0          # R > 1/gm -> LHP
    assert ac.zero_hz(1 / 3000, 1e-12, 3000) is None
    assert math.isclose(ac.mirror_ratio_mismatch(60, 20, 9.4, 21.3), 1.32, abs_tol=0.01)
    assert math.isclose(ac.target_wl_for_balance(20, 9.4, 21.3), 45.3, abs_tol=0.1)


def fake_op(target, **over):
    op = {'v(out)': 1.7}
    for name, spec in target['dc_acceptance']['devices'].items():
        prefix = spec['diagnostic_prefix'].lower()
        values = dict(id=2e-5, gm=4e-4, gds=2e-6, vgs=.7, vds=.7, vth=.5, vdsat=.1)
        values.update(over.get(name, {}))
        op.update({prefix + '[' + k + ']': v for k, v in values.items()})
    return op


def test_two_stage_relations_come_from_the_reference_declaration():
    d = ac.derive(TARGET, parameters(REF), {'dc_operating_point': fake_op(TARGET, XM6={'id': 1e-5}), 'metrics': {}})
    assert d['stage_balance']['Rm'] > 1.5 and d['series_resistor_ohm'] == 1000
    assert 'output_node_v' not in d['stage_balance']        # the closed loop pins out at VCM, so it says nothing about the balance
    assert d['compensation']['zero_side'].startswith('RHP')
    assert 'XM1' in d['devices'] and 'cascode_stage' not in d


def test_stack_resistance_formula():
    prop = lambda dev, key: {'A': {'gds': 1e-5, 'gm': 1e-3}, 'B': {'gds': 2e-5, 'gm': 1e-3}}[dev][key]
    r = ac.stack_resistance(['A', 'B'], prop)
    assert math.isclose(r, 1e5 + 5e4 + 1e-3 * 1e5 * 5e4)
    assert math.isclose(ac.stack_resistance([["A", "B"]], prop), 1 / 3e-5)
    assert ac.stack_resistance(['A', 'Z'], lambda d, k: None) is None


def test_cascode_analysis_available_for_every_cascode_reference():
    for rid, ref in REFS.items():
        if 'cascode' not in rid:
            continue
        target = design_target(SPECS, ref)
        d = ac.derive(target, parameters(ref.text), {'dc_operating_point': fake_op(target), 'metrics': {'power_w': 1e-4}})
        stage = d['cascode_stage']
        assert stage['A0_estimate_dB_gm1_times_Rout'] > 40 and stage['ugb_upper_bound_gm1_over_2pi_CL_MHz'] > 0, rid
        assert 'stage_balance' not in d and 'compensation' not in d


def test_single_stage_ugb_estimate_is_an_upper_bound_and_the_parasitic_c_is_recovered_from_the_measurement():
    ref = REFS['folded_cascode_nmos_input']
    target = design_target(SPECS, ref)
    op = fake_op(target)                                   # gm of every device: 400 uS
    measured = 1 / (2 * math.pi * 2.5e-12) * 400e-6        # as if the real output capacitance were 2.5 pF for CL = 2 pF
    d = ac.derive(target, parameters(ref.text), {'dc_operating_point': op, 'metrics': {'ugb_hz': measured}})['cascode_stage']
    assert d['ugb_upper_bound_gm1_over_2pi_CL_MHz'] > measured / 1e6
    assert math.isclose(d['effective_output_C_pF_from_measured_ugb'], 2.5, rel_tol=1e-3)
    assert math.isclose(d['parasitic_C_pF'], 0.5, rel_tol=1e-2)


def test_stage_balance_reports_how_far_the_loop_had_to_shift_the_gain_device_gate_drive():
    op = fake_op(TARGET, XM7={'vgs': -1.02}, XM3={'vgs': -1.07})        # |VSG7| is 50 mV lower than the mirror reference's
    d = ac.derive(TARGET, parameters(REF), {'dc_operating_point': op, 'metrics': {}})['stage_balance']
    assert d['gain_device_gate_drive_shift_mV'] == pytest.approx(-50.0)
