"""The library is the only home of topology-specific information; everything else must be generic."""
import re
import pytest
from agents.sizing_agent.agent import check_library, validate_candidate
from analog_agents.reference import agent_netlist, design_target, parse_reference
import main
from helpers import ROOT, BASE, REFS, REAL_SPECS, SPECS, REF

NAME = re.compile(r'^(two_stage_(nmos|pmos)_input_(nmos|pmos)_stage2|(folded|telescopic)_cascode_(nmos|pmos)_input)$')


def test_library_names_say_which_topology_it_is():
    assert len(REFS) == 6 and all(NAME.match(i) for i in REFS)
    for rid, ref in REFS.items():
        assert ref.path.name == rid + '.spice'
        polarity = re.search(r'_(nmos|pmos)_input', rid)[1]
        assert ('NMOS input' if polarity == 'nmos' else 'PMOS input') in ref.profile.split('\n')[0]


@pytest.mark.parametrize('rid', sorted(REFS))
def test_each_reference_is_self_consistent(rid):
    ref = REFS[rid]
    target = design_target(SPECS, ref)
    assert validate_candidate(ref.text, ref.text, target)
    for section in ('ADVANTAGES', 'DISADVANTAGES', 'BEST WHEN', 'AVOID WHEN', 'STRUCTURE'):
        assert section in ref.profile, section
    assert ref.text.index('@profile-begin') < ref.text.index('@analyses-begin') < ref.text.index('.param')
    # constraints are read from the netlist, never declared a second time
    assert set(target['dc_acceptance']['devices']) == set(ref.devices) == set(target['optimization']['device_dimensions'])
    agent_view = agent_netlist(ref.text)
    assert '@profile' not in agent_view and '@analyses' not in agent_view and 'NOTES' in agent_view
    assert not re.search(r'^\.(lib|temp|control|end)\b|^(VSUPPLY|VINP|VINN|CLOAD_OUT)\b', ref.text, re.M | re.I)


def test_reference_format_is_enforced():
    def bad(text, match):
        with pytest.raises(ValueError, match=match):parse_reference(text, 'x')
    bad(REF.replace('* @profile-begin', '* nothing').replace('* @profile-end', ''), 'profile')
    bad(REF.replace('.param W_IN=10          ; tune 1..100 um', '.param W_IN=10 L_IN=1'), 'one .param assignment per line')
    bad(REF.replace('.param W_IN=10          ; tune 1..100 um', '.param W_IN=500         ; tune 1..100 um'), 'outside tune range')
    bad(REF.replace('.param N_TAIL=1         ; tune 1..20 int', '.param N_TAIL=1.5       ; tune 1..20 int'), 'non-integer')
    bad(REF.replace('.param W_IN=10          ; tune 1..100 um', '.param W_IN=10\n.param UNUSED=3   ; tune 1..9'), 'not used')
    bad(re.sub(r'; tune [^\n]*', '', REF), 'no tunable')
    bad(REF + '\n.param VDD=1.8\n', 'testbench')
    bad(REF.replace('* @feedback-input: vinp\n', ''), 'feedback-input')
    bad(REF.replace('* @feedback-input: vinp\n', '* @feedback-input: out\n'), 'feedback-input')
    bad(REF.replace('* @feedback-input: vinp\n', '* @feedback-input: vinp\n* @feedback-input: vinn\n'), 'feedback-input')
    bad(REF.replace('{"type": "current_balance", "gain_device": "XM7"', '{"type": "current_balance", "gain_device": "XM99"'), 'unknown devices')


def test_declared_feedback_inputs_follow_how_each_topology_inverts():
    """Closing the loop on the wrong input is positive feedback. Two inverting stages (out falls when vinp rises) close on
    vinp; one mirror-loaded stage (out rises with vinp) closes on vinn. Simulation checks are in test_pdk.py."""
    expected = {'two_stage_nmos_input_pmos_stage2': 'vinp', 'two_stage_pmos_input_nmos_stage2': 'vinp',
                'folded_cascode_nmos_input': 'vinn', 'folded_cascode_pmos_input': 'vinn',
                'telescopic_cascode_nmos_input': 'vinn', 'telescopic_cascode_pmos_input': 'vinn'}
    assert {rid: ref.feedback_input for rid, ref in REFS.items()} == expected
    assert all(design_target(SPECS, ref)['feedback_input'] == ref.feedback_input for ref in REFS.values())
    assert not any('@feedback-input' in agent_netlist(ref.text) for ref in REFS.values())      # the agents get it from the testbench text


def test_the_real_specs_file_has_the_shape_the_tests_assume_and_works_with_every_reference():
    """The other tests use pinned specs (helpers.SPECS); this is the one place where target.json itself is checked."""
    assert set(REAL_SPECS) - {'reference_tags'} == set(SPECS)   # reference_tags is optional
    for section, value in SPECS.items():
        if isinstance(value, dict) and section != 'targets':
            assert set(REAL_SPECS[section]) == set(value), section
    assert set(REAL_SPECS['ac_validation']['sweep']) == set(SPECS['ac_validation']['sweep'])
    assert all(isinstance(limits, dict) and set(limits) <= {'min', 'max'} for limits in REAL_SPECS['targets'].values())
    main.check_budgets(REAL_SPECS)
    check_library(REAL_SPECS, REFS)


def test_specs_file_contains_no_topology_information():
    text = (BASE/'specs/target.json').read_text()
    assert not re.search(r'\bXM\w*|W_IN|N_TAIL|vbias|"topology"|allowed_parameters|device_dimensions', text)


GENERIC_FILES = [ROOT/'ANALOG_DESIGN_RULES.md', ROOT/'main.py', BASE/'specs/target.json',
                 *(ROOT/'agents').glob('*/*.py'), *(ROOT/'agents').glob('*/*.md'),
                 *(ROOT/'analog_agents').glob('*.py'), *(ROOT/'simulator').glob('*.py')]
FORBIDDEN = re.compile(r'\bXM[A-Z0-9_]*\b|\bW_IN\b|\bN_TAIL\b|\bWBN0\b|\bW_STAGE2\b|\bIBIAS\b|\bVBN_|\bVBP_|'
                       r'two_stage_|folded_cascode|telescopic_cascode|PMOS gain|NMOS bias')


@pytest.mark.parametrize('path', GENERIC_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_circuit_specific_names_outside_the_references(path):
    hits = FORBIDDEN.findall(path.read_text())
    assert not hits, f'{path.name} mentions circuit-specific identifiers: {sorted(set(hits))}'


def test_exactly_three_agents():
    agents = sorted(p.name for p in (ROOT/'agents').iterdir() if p.is_dir() and not p.name.startswith('__'))
    assert agents == ['review_agent', 'sizing_agent', 'topology_agent']
