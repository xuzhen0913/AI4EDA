"""Offline validation of a reference's series R-C compensation constraints and the report's netlist table."""
import pytest
from agents.sizing_agent.agent import apply_changes, validate_candidate
from analog_agents.spice import number, parameters
from simulator.report_generator import mos_table
from helpers import REF, TARGET


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


def test_connectivity_table_is_parsed_from_netlist_not_hardcoded():
    rows=mos_table(REF,parameters(REF))
    by_name={r[0]:r for r in rows}
    assert len(rows)==8 and by_name['XM7'][1]=='PMOS' and by_name['XM7'][2:6]==['out','n2','vdd','vdd']
    assert by_name['XM5'][6]=='10' and by_name['XM5'][7]=='1'
    swapped=REF.replace('XM7 out n2 vdd vdd','XM7 out n1 vdd vdd')
    assert {r[0]:r for r in mos_table(swapped,parameters(swapped))}['XM7'][3]=='n1'
