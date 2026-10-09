import pytest
from analog_agents.spice import circuit_nodes, evaluate, logical_lines, mos_devices, parameters

NET = '''* comment
.param W=10          ; tune 1..100 um
.param N=2
XM1 d g s 0 sky130_fd_pr__nfet_01v8
+ W={N*W} L=0.5
M2 d2 g2 vdd vdd pmos W={W} L=1u
R1 d out {W}   ; inline comment
C1 out 0 1p
.control
op
.endc
'''


def test_parameters_and_expressions():
    p = parameters(NET)
    assert p == {'W': '10', 'N': '2'}
    assert evaluate('N*W', p) == 20 and evaluate('W/N', p) == 5 and evaluate('2*N', p) == 4 and evaluate('1u', p) == 1e-6
    for bad in ('N+W', 'N*(W)', 'N*Z', ''):
        with pytest.raises(ValueError):evaluate(bad, p)
    with pytest.raises(ValueError):parameters('.param A=1\n.param A=2\n')


def test_mos_devices_read_terminals_polarity_and_prefix_from_the_netlist():
    d = mos_devices(NET)
    assert set(d) == {'XM1', 'M2'}
    assert d['XM1'] == dict(kind='nfet', drain='d', gate='g', source='s', body='0', model='sky130_fd_pr__nfet_01v8',
                            W='N*W', L='0.5', diagnostic_prefix='@m.xm1.msky130_fd_pr__nfet_01v8')
    assert d['M2']['kind'] == 'pfet' and d['M2']['diagnostic_prefix'] == '@m2'


def test_nodes_and_statements_ignore_comments_and_control_text():
    assert circuit_nodes(NET) == ['d', 'g', 's', 'd2', 'g2', 'vdd', 'out']
    assert 'R1 d out {W}' in logical_lines(NET) and not any(l.startswith('*') for l in logical_lines(NET))
