"""Shared fixtures: the specs and the library entry used as a concrete sizing example."""
import json
from pathlib import Path
from analog_agents.reference import design_target, load_references

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'circuits/opamp'
# The tests bring their own specs, so editing target.json (to try other targets, supply or sweep) never breaks them.
# test_references.py checks that the real file still has this shape and works with every reference in the library.
SPECS = {
    'process': 'sky130', 'corner': 'tt',
    'conditions': {'vdd_v': 1.8, 'temperature_c': 27, 'input_common_mode_v': 0.9, 'load_capacitance_f': 2e-12},
    'targets': {'dc_gain_db': {'min': 60}, 'ugb_hz': {'min': 10000000}, 'phase_margin_deg': {'min': 60},
                'power_w': {'max': 0.0005}},
    'device_limits': {'min_w_um': 1, 'max_w_um': 100, 'min_l_um': 0.15, 'max_l_um': 2},
    'dc_acceptance': {'minimum_drain_current_a': 1e-09, 'minimum_overdrive_v': 0.0, 'minimum_saturation_margin_v': 0.0,
                      'maximum_output_error_v': 0.05},
    'ac_validation': {'require_positive_loop_real_lf': True,
                      'sweep': {'points_per_decade': 100, 'start_hz': 1, 'stop_hz': 1000000000}},
    'budgets': {'max_rounds': 3, 'max_dc_iterations': 5, 'max_iterations': 10}}
REAL_SPECS = json.loads((BASE/'specs/target.json').read_text())
REFS = load_references(BASE/'reference')
EXAMPLE = REFS['two_stage_nmos_input_pmos_stage2']
REF = EXAMPLE.text
TARGET = design_target(SPECS, EXAMPLE)
