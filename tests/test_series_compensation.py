"""Offline validation of the series RC topology; no simulator/model invocation."""
import json
from pathlib import Path
import pytest
from agents.sizing_agent.agent import apply_changes, parameters, number, validate_candidate
from simulator.report_generator import topology
from reportlab.graphics.shapes import Rect
ROOT=Path(__file__).resolve().parents[1]
REF=(ROOT/'circuits/two_stage_opamp/reference/reference.spice').read_text()
TARGET=json.loads((ROOT/'circuits/two_stage_opamp/specs/target.json').read_text())


def test_resistor_geometry_is_adjustable_but_sheet_resistance_fixed():
    after=apply_changes(REF,REF,TARGET,[dict(parameter='L_RZ',old_value='10',new_value='30')])
    p=parameters(after)
    assert number(p['RSH_RZ'])*number(p['L_RZ'])/number(p['W_RZ'])==3000
    assert 'CCOMP n2 ncomp {CC}' in after
    assert 'RCOMP ncomp out {RSH_RZ*L_RZ/W_RZ}' in after
    for change in [dict(parameter='RSH_RZ',old_value='100',new_value='200'),
                   dict(parameter='W_RZ',old_value='1',new_value='0'),
                   dict(parameter='L_RZ',old_value='10',new_value='101')]:
        with pytest.raises(ValueError):apply_changes(REF,REF,TARGET,[change])
    with pytest.raises(ValueError):validate_candidate(REF,after.replace('RCOMP ncomp out','RCOMP ncomp 0'),TARGET)


def test_new_and_capacitor_only_report_drawings():
    assert any(isinstance(x,Rect) for x in topology(REF).contents)
    old=REF.replace('CCOMP n2 ncomp {CC}','CCOMP n2 out {CC}').replace('RCOMP ncomp out {RSH_RZ*L_RZ/W_RZ}\n','')
    assert not any(isinstance(x,Rect) for x in topology(old).contents)
    wrong=REF.replace('RCOMP ncomp out','RCOMP ncomp 0')
    with pytest.raises(ValueError):topology(wrong)
