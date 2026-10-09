"""Shared fixtures: the specs and the library entry used as a concrete sizing example."""
import json
from pathlib import Path
from analog_agents.reference import design_target, load_references

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'circuits/opamp'
# The tests bring their own targets, so changing the numbers in target.json (e.g. to try other specs) never breaks them.
TEST_TARGETS = {'dc_gain_db': {'min': 60}, 'ugb_hz': {'min': 10000000}, 'phase_margin_deg': {'min': 60},
                'power_w': {'max': 0.0005}}
SPECS = {**json.loads((BASE/'specs/target.json').read_text()), 'targets': TEST_TARGETS}
REFS = load_references(BASE/'reference')
EXAMPLE = REFS['two_stage_nmos_input_pmos_stage2']
REF = EXAMPLE.text
TARGET = design_target(SPECS, EXAMPLE)
