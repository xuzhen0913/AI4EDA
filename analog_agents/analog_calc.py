"""Analog formula library and measurement-derived arithmetic for sizing prompts.

Pure functions implement textbook relations from ANALOG_DESIGN_RULES.md. `derive`
turns a simulator result into pre-computed numbers so the model never has to do
arithmetic. It reports relations, never decisions; every result is an estimate.
"""
import math
import re

UT = 0.02585  # kB*T/q at 300 K


def vov(vgs_mag, vth_mag):
    return vgs_mag - vth_mag


def gm_over_id(gm, i):
    return gm / i if i else None


def intrinsic_gain(gm, gds):
    return gm / gds if gds else None


def db(x):
    return 20 * math.log10(abs(x)) if x else None


def ft(gm, cgs, cgd):
    return gm / (2 * math.pi * (cgs + cgd))


def sheet_resistor(rsheet, length, width):
    return rsheet * length / width


def unity_gain_hz(gm1, cc):
    return gm1 / (2 * math.pi * cc)


def second_pole_hz(gm2, c1, c2, cc):
    return gm2 * cc / (c1 * c2 + c1 * cc + c2 * cc) / (2 * math.pi)


def zero_hz(gm2, cc, rz):
    """Signed: positive = RHP, negative = LHP, None = at infinity (rz == 1/gm2)."""
    d = cc * (1 / gm2 - rz)
    return None if d == 0 else 1 / (2 * math.pi * d)


def rz_cancel_second_pole(gm2, cc, p2_hz):
    return 1 / gm2 + 1 / (cc * 2 * math.pi * p2_hz)


def mirror_ratio_mismatch(wl_g, wl_a, i_a, i_s):
    """Rm = capability current of second-stage device / forced sink current."""
    return (wl_g / wl_a) * (i_a / i_s)


def target_wl_for_balance(wl_a, i_a, i_s):
    return wl_a * i_s / i_a


def pm_estimate_deg(ugb, p2, zero_signed=None, p3=None):
    pm = 90 - math.degrees(math.atan(ugb / p2))
    if zero_signed:
        pm += -math.copysign(1, zero_signed) * math.degrees(math.atan(ugb / abs(zero_signed)))
    if p3:
        pm -= math.degrees(math.atan(ugb / p3))
    return pm


def _eval(expression, params, number):
    """Restricted product/quotient of named scalars or numbers; never eval()."""
    value = 1.0
    for op, token in re.findall(r'([*/]?)\s*([A-Za-z_]\w*|[-+]?[\d.]+(?:[eE][-+]?\d+)?)', expression):
        factor = number(params[token]) if token in params else float(token)
        value = value / factor if op == '/' else value * factor
    return value


def _round(x, digits=4):
    return None if x is None else float(f'{x:.{digits}g}')


def derive(target, params, measurements, number):
    """Numbers computed from this run's evidence. Missing evidence yields no entry."""
    op = measurements.get('dc_operating_point') or {}
    dims = target['optimization'].get('device_dimensions', {})
    specs = target.get('dc_acceptance', {}).get('devices', {})
    out = {}

    def prop(dev, key):
        spec = specs.get(dev)
        return op.get(spec['diagnostic_prefix'].lower() + '[' + key + ']') if spec else None

    def wl(dev):
        try:
            return _eval(dims[dev]['W'], params, number) / _eval(dims[dev]['L'], params, number)
        except (KeyError, ValueError):
            return None

    table = {}
    for dev in specs:
        i, gm, gds = prop(dev, 'id'), prop(dev, 'gm'), prop(dev, 'gds')
        vgs, vth, vds, vdsat = (prop(dev, k) for k in ('vgs', 'vth', 'vds', 'vdsat'))
        if None in (i, gm, gds, vgs, vth, vds, vdsat):
            continue
        sign = 1 if specs[dev]['kind'] == 'nfet' else -1
        row = {'W_over_L': _round(wl(dev)), 'id_uA': _round(abs(i) * 1e6), 'gm_uS': _round(gm * 1e6),
               'gm_over_id_per_V': _round(gm / abs(i)) if i else None,
               'gm_over_gds': _round(gm / gds) if gds else None}
        if row['gm_over_id_per_V'] and row['gm_over_id_per_V'] > 0.8 / (1.3 * UT):
            row['inversion'] = 'weak/moderate: raising W barely raises gm; gm needs current'
        table[dev] = row
    if table:
        out['devices'] = {d: {k: v for k, v in r.items() if k != 'id_uA'} for d, r in table.items()}

    topo = target.get('topology', {})
    g, s = topo.get('second_stage_gain_device'), topo.get('second_stage_bias_device')
    a = topo.get('mirror_reference_device')
    if not a:
        mirrors = [m for m in target['optimization'].get('mirror_constraints', []) if m.get('fixed_ratio') == 1]
        a = mirrors[0]['reference'] if mirrors else None
    tail = topo.get('tail_device')
    if g and s and a and all(table.get(d) for d in (g, s, a)):
        i_a, i_s = table[a]['id_uA'], table[s]['id_uA']
        rm = mirror_ratio_mismatch(wl(g), wl(a), i_a, i_s)
        out['stage_balance'] = {
            'Rm': _round(rm), 'Ia_uA': i_a, 'Is_uA': i_s,
            'output_node_v': op.get('v(out)'),
            'target_W_over_L_of_gain_device_for_Rm_1': _round(target_wl_for_balance(wl(a), i_a, i_s)),
        }
    p = prop
    cc = number(params['CC']) if 'CC' in params else None
    rcomp = target.get('passive_components', {}).get('RCOMP')
    rz = None
    if rcomp and 'resistance_expression' in rcomp:
        rsh = rcomp.get('fixed_sheet_resistance_ohm_per_square')
        expr = rcomp['resistance_expression']
        try:
            rz = _eval(expr, dict(params), number) if all(
                t in params or re.fullmatch(r'[\d.eE+-]+', t) for t in re.findall(r'[A-Za-z_]\w*', expr)) else None
        except (KeyError, ValueError):
            rz = None
        if rz is not None:
            out['series_resistor_ohm'] = _round(rz)
    if g and table.get(g) and tail is not None or g and table.get(g):
        gm2 = table[g]['gm_uS'] * 1e-6
        comp = {'inv_gm_gain_device_ohm': _round(1 / gm2)}
        cl = target.get('conditions', {}).get('load_capacitance_f')
        if cl:
            p2 = gm2 / (2 * math.pi * cl)
            comp['p2_approx_gm2_over_2pi_CL_MHz'] = _round(p2 / 1e6)
        inp = topo.get('input_pair_device')
        if inp and table.get(inp) and cc:
            gm1 = table[inp]['gm_uS'] * 1e-6
            comp['ugb_approx_gm1_over_2pi_CC_MHz'] = _round(unity_gain_hz(gm1, cc) / 1e6)
            if table.get(s):
                gds_sum = ((prop(inp, 'gds') or 0) + (prop(a, 'gds') or 0)) if a else 0
                if gds_sum:
                    comp['A1_dB'] = _round(db(gm1 / gds_sum))
                gds2 = (prop(g, 'gds') or 0) + (prop(s, 'gds') or 0)
                if gds2:
                    comp['A2_dB'] = _round(db(gm2 / gds2))
        if cc and rz is not None:
            z = zero_hz(gm2, cc, rz)
            comp['zero_MHz_signed'] = None if z is None else _round(z / 1e6)
            comp['zero_side'] = 'LHP (R > 1/gm2)' if rz > 1 / gm2 else ('at infinity' if rz == 1 / gm2 else 'RHP (R < 1/gm2)')
            if cl:
                comp['R_for_zero_to_cancel_p2_ohm'] = _round(rz_cancel_second_pole(gm2, cc, gm2 / (2 * math.pi * cl)))
        out['compensation'] = comp
    metrics = measurements.get('metrics', {})
    power = metrics.get('power_w')
    limit = target.get('targets', {}).get('power_w', {}).get('max')
    if power and limit:
        out['power'] = {'now_uW': _round(power * 1e6), 'limit_uW': _round(limit * 1e6),
                        'headroom_uW': _round((limit - power) * 1e6),
                        'supply_current_uA': _round(power / target['conditions']['vdd_v'] * 1e6)}
    return out
