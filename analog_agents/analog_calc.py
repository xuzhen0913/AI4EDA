"""Analog formula library and measurement-derived arithmetic for sizing prompts.

Pure functions implement textbook relations from ANALOG_DESIGN_RULES.md. `derive`
turns a simulator result into pre-computed numbers so the model never has to do
arithmetic. It reports relations, never decisions; every result is an estimate.
"""
import math
from analog_agents.spice import evaluate, number

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


def _round(x, digits=4):
    return None if x is None else float(f'{x:.{digits}g}')


def stack_resistance(stack, prop):
    """Output resistance looking into a series stack, listed from the output node inward.

    An item is a device name, or a list of names in parallel (a node loaded by several
    devices). r = 1/gds; each device above adds r + R_below + gm*r*R_below.
    Returns None if any needed gm/gds is missing.
    """
    below = None
    for item in reversed(stack):
        names = item if isinstance(item, list) else [item]
        conductance = [prop(n, 'gds') for n in names]
        if any(g is None or g <= 0 for g in conductance):
            return None
        r = 1 / sum(conductance)
        if below is None:
            below = r
            continue
        gm = prop(names[0], 'gm')
        if gm is None:
            return None
        below = r + below + abs(gm) * r * below
    return below


def derive(target, params, measurements):
    """Numbers computed from this run's evidence. Missing evidence yields no entry.

    Per-device tables and power are generic. Optional relations are enabled only when the
    selected reference declares them in its interface (`derived_analyses`).
    """
    op = measurements.get('dc_operating_point') or {}
    dims = target['optimization'].get('device_dimensions', {})
    specs = target.get('dc_acceptance', {}).get('devices', {})
    out = {}

    def prop(dev, key):
        spec = specs.get(dev)
        return op.get(spec['diagnostic_prefix'].lower() + '[' + key + ']') if spec else None

    def wl(dev):
        try:
            return evaluate(dims[dev]['W'], params) / evaluate(dims[dev]['L'], params)
        except (KeyError, ValueError):
            return None

    table = {}
    for dev in specs:
        i, gm, gds = prop(dev, 'id'), prop(dev, 'gm'), prop(dev, 'gds')
        vgs, vth, vds, vdsat = (prop(dev, k) for k in ('vgs', 'vth', 'vds', 'vdsat'))
        if None in (i, gm, gds, vgs, vth, vds, vdsat):
            continue
        row = {'W_over_L': _round(wl(dev)), 'id_uA': _round(abs(i) * 1e6), 'gm_uS': _round(gm * 1e6),
               'gm_over_id_per_V': _round(gm / abs(i)) if i else None,
               'gm_over_gds': _round(gm / gds) if gds else None}
        table[dev] = row
    if table:
        out['devices'] = {d: {k: v for k, v in r.items() if k != 'id_uA'} for d, r in table.items()}
        weak = [d for d, r in table.items() if r['gm_over_id_per_V'] and r['gm_over_id_per_V'] > 0.8 / (1.3 * UT)]
        if weak:
            out['weak_or_moderate_inversion'] = {'devices': weak,
                                                 'note': 'raising W barely raises gm there; gm needs current'}

    conditions = target.get('conditions', {})
    for spec in target.get('derived_analyses', []):
        kind = spec.get('type')
        if kind == 'current_balance':
            g, s, a = spec['gain_device'], spec['bias_device'], spec['mirror_reference_device']
            if all(table.get(d) for d in (g, s, a)):
                i_a, i_s = table[a]['id_uA'], table[s]['id_uA']
                out['stage_balance'] = {
                    'Rm': _round(mirror_ratio_mismatch(wl(g), wl(a), i_a, i_s)), 'Ia_uA': i_a, 'Is_uA': i_s,
                    'output_node_v': _round(op.get('v(out)')),
                    'target_W_over_L_of_gain_device_for_Rm_1': _round(target_wl_for_balance(wl(a), i_a, i_s))}
        elif kind == 'miller_compensation':
            g, s, inp = spec['gain_device'], spec['bias_device'], spec['input_device']
            a = spec.get('first_stage_load_device')
            cc = number(params[spec['capacitor_parameter']]) if spec['capacitor_parameter'] in params else None
            expr = spec.get('series_resistor_expression')
            try:
                rz = evaluate(expr, params) if expr else None
            except (KeyError, ValueError):
                rz = None
            if rz is not None:
                out['series_resistor_ohm'] = _round(rz)
            if not table.get(g):
                continue
            gm2 = table[g]['gm_uS'] * 1e-6
            comp = {'inv_gm_gain_device_ohm': _round(1 / gm2)}
            cl = conditions.get(spec.get('load_capacitance_condition', ''))
            if cl:
                comp['p2_approx_gm2_over_2pi_CL_MHz'] = _round(gm2 / (2 * math.pi * cl) / 1e6)
            if table.get(inp) and cc:
                gm1 = table[inp]['gm_uS'] * 1e-6
                comp['ugb_approx_gm1_over_2pi_CC_MHz'] = _round(unity_gain_hz(gm1, cc) / 1e6)
                gds_sum = (prop(inp, 'gds') or 0) + ((prop(a, 'gds') or 0) if a else 0)
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
        elif kind == 'cascode_stage':
            inp = spec['input_device']
            if not table.get(inp):
                continue
            gm1 = table[inp]['gm_uS'] * 1e-6
            stage = {'gm_input_uS': _round(gm1 * 1e6)}
            r = {name: stack_resistance(stack, prop) for name, stack in spec.get('stacks', {}).items()}
            for name, value in r.items():
                if value is not None:
                    stage['Rout_' + name + '_kohm'] = _round(value / 1e3)
            if r and all(v is not None for v in r.values()):
                rout = 1 / sum(1 / v for v in r.values())
                stage['Rout_total_kohm'] = _round(rout / 1e3)
                stage['A0_estimate_dB_gm1_times_Rout'] = _round(db(gm1 * rout))
            cl = conditions.get(spec.get('load_capacitance_condition', ''))
            if cl:
                stage['ugb_approx_gm1_over_2pi_CL_MHz'] = _round(unity_gain_hz(gm1, cl) / 1e6)
            out['cascode_stage'] = stage
    metrics = measurements.get('metrics', {})
    power = metrics.get('power_w')
    limit = target.get('targets', {}).get('power_w', {}).get('max')
    if power and limit:
        out['power'] = {'now_uW': _round(power * 1e6), 'limit_uW': _round(limit * 1e6),
                        'headroom_uW': _round((limit - power) * 1e6),
                        'supply_current_uA': _round(power / conditions['vdd_v'] * 1e6)}
    return out
