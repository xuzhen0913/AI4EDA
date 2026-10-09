"""Compact views of simulator evidence for the agents: each fact appears once, in one table.

The simulator record carries the same operating-point numbers in several shapes (raw diagnostics, DC-acceptance
details, derived estimates, the log). The agents get one merged device table, the node voltages, a short measurement
summary, and only those log lines that carry information found nowhere else.
"""
import math
import re
from analog_agents.spice import SCALAR

DEVICE_COLUMNS = ['device', 'type', 'W/L', 'Id_uA', '|Vgs|_V', '|Vds|_V', '|Vth|_V', '|Vdsat|_V', 'overdrive_V',
                  'sat_margin_V', 'gm_uS', 'gm/Id_per_V', 'gm/gds', 'failed_checks']
NOISE = re.compile(r'^(COMMAND:|RETURN_CODE:|Note: No compatibility|Circuit:|Doing analysis at|Using SPARSE|'
                   r'Reference value|No\. of Data Rows|DC_OPERATING_POINT|END_DC_OPERATING_POINT|ngspice-\d+ done)', re.I)
SCALAR_LINE = re.compile(r'^\s*[^\s=]+\s*=\s*' + SCALAR + r'\s*$')


def sig(value, digits=5):
    """Round to significant digits; None and non-numbers pass through."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value == 0:
        return value
    return float(f'{value:.{digits}g}')


def outcome(r):
    """What a past decision led to: DC status and metrics (a stored history row's `result` or `before`)."""
    return dict(dc_passed=r['dc_passed'], failed_dc_devices=r['failed_dc_devices'],
                metrics={k: sig(v) for k, v in r['metrics'].items()})


def measurement_summary(m, metrics=True):
    """Validity and metrics of the latest simulation. Failed devices are in the device table, not repeated here.
    The review agent passes metrics=False: its spec_check already carries every value and verdict."""
    summary = dict(analysis=m['analysis_mode'], simulation_valid=m['simulation_valid'], dc_passed=m['dc_passed'])
    if metrics:
        summary.update(metrics={k: sig(v) for k, v in m['metrics'].items()},
                       failed_metrics=[k for k, v in m['checks'].items() if v is False])
    if m['errors']:
        summary['errors'] = m['errors']
    if m['warnings']:
        summary['warnings'] = m['warnings']
    polarity = m.get('ac_polarity') or {}
    if polarity.get('passed') is False:
        summary['ac_polarity_invalid'] = polarity.get('loop_real_lf')
    return summary


def node_voltages(m):
    return {k[2:-1]: sig(v) for k, v in m['dc_operating_point'].items() if k.startswith('v(') and k.endswith(')')}


def device_table(m, kinds, derived=None):
    """One row per MOS: operating point (sign-normalised), small-signal estimates, failed DC criteria."""
    derived = derived or {}
    rows = []
    for name, d in m['dc_acceptance']['devices'].items():
        extra = derived.get(name, {})
        if 'id_a' not in d:
            rows.append([name, kinds.get(name), extra.get('W_over_L')] + [None] * 10 + [d.get('reason', 'no diagnostics')])
            continue
        failed = ','.join(k for k, ok in d['checks'].items() if not ok)
        rows.append([name, kinds.get(name), extra.get('W_over_L'), sig(d['id_a'] * 1e6), sig(d['vgs_or_vsg_v']),
                     sig(d['vds_or_vsd_v']), sig(d['vth_magnitude_v']), sig(d['vdsat_magnitude_v']),
                     sig(d['overdrive_v']), sig(d['saturation_margin_v']), extra.get('gm_uS'),
                     extra.get('gm_over_id_per_V'), extra.get('gm_over_gds'), failed])
    return {'columns': DEVICE_COLUMNS, 'rows': rows}


def residual_log(text, m):
    """Log lines not already represented by the structured fields (usually none)."""
    represented = set(m['errors']) | set(m['warnings'])
    keep = [l.rstrip() for l in text.splitlines()
            if l.strip() and not NOISE.match(l.strip()) and not SCALAR_LINE.match(l) and not l.startswith('DEVICE_')
            and l.rstrip() not in represented]
    return '\n'.join(keep)
