"""Topology-independent sizing: declarative constraint enforcement plus the model call."""
import math
from pathlib import Path
from analog_agents.analog_calc import derive
from analog_agents.evidence import device_table, measurement_summary, node_voltages, residual_log
from analog_agents.reference import agent_netlist, design_target
from analog_agents.schema import obj, array, enum, TEXT
from analog_agents.search import MAX_CHANGES, MAX_CHANGES_DC, MAX_FREE_REFUSALS, charged, history_table
from analog_agents.spice import PARAM, evaluate, number, parameters
from simulator.testbench import describe

DC_SECTIONS = (1, 3, 4, 6, 12, 14)             # handbook sections the DC-repair phase needs
PERFORMANCE_SECTIONS = (1, 3, 4, 6, 8, 9, 12, 13, 14)


def schema(parameters):
    """`changes` first: if the free text after it ever runs away, the decision itself is already complete.
    The parameter is an enum of the tunable names and the old value is filled in by the loop, so neither can be wrong."""
    return obj({'changes': array(obj({'parameter': enum(parameters), 'new_value': TEXT, 'reason': TEXT})),
                'analysis': obj({'simulation_valid': {'type': 'boolean'}, 'dc_op_valid': {'type': 'boolean'},
                                 'main_problem': TEXT})})


def validate_candidate(reference, candidate, target):
    """The candidate may differ from the reference only in allowed parameter values, all within bounds."""
    optimization = target['optimization']
    allowed = optimization['allowed_parameters']

    def fixed(text):
        return PARAM.sub(lambda m: m[1]+m[2]+m[3]+'<SIZE>'+m[5] if m[2] in allowed else m[0], text)
    if fixed(reference) != fixed(candidate):
        raise ValueError('Topology or fixed conditions changed')
    params = parameters(candidate)
    for name in allowed:
        bounds = optimization['parameter_bounds'][name]
        if not bounds['min'] <= number(params[name]) <= bounds['max']:
            raise ValueError(f"{name}={params[name]} is outside its tune range {bounds['min']:g}..{bounds['max']:g}")
    for name in optimization.get('integer_parameters', []):
        if not number(params[name]).is_integer():
            raise ValueError(f'{name}={params[name]} must be an integer')
    for device, dimensions in optimization.get('device_dimensions', {}).items():
        limits = optimization['device_bounds'][device]
        for dimension, expression in dimensions.items():
            if not limits['min_'+dimension.lower()+'_um'] <= evaluate(expression, params) <= limits['max_'+dimension.lower()+'_um']:
                raise ValueError(f"Effective {dimension} of {device} is {evaluate(expression, params):g} um, outside its limit "
                                 f"{limits['min_'+dimension.lower()+'_um']:g}..{limits['max_'+dimension.lower()+'_um']:g} um")
    return params


def check_library(specs, references):
    """Fail before any model call if a library entry cannot be sized with these specs."""
    for ref in references.values():
        validate_candidate(ref.text, ref.text, design_target(specs, ref))


def apply_changes(reference, candidate, target, changes):
    before = validate_candidate(reference, candidate, target)
    updates = {}
    for change in changes:
        key = change['parameter']
        if key not in target['optimization']['allowed_parameters'] or key in updates:
            raise ValueError(f"{key}: not a tunable parameter, or named twice")
        if 'old_value' in change and not math.isclose(number(change['old_value']), number(before[key]), rel_tol=1e-9, abs_tol=0):
            raise ValueError(f"{key}: old_value {change['old_value']} does not match the current value {before[key]}")
        number(change['new_value'])
        updates[key] = change['new_value']
    result = PARAM.sub(lambda m: m[1]+m[2]+m[3]+updates.get(m[2], m[4])+m[5], candidate)
    validate_candidate(reference, result, target)
    return result


def sizing_specs(target, history):
    """The specs part of the sizing input: what must be met, under which fixed testbench, within which budgets."""
    optimization = target['optimization']
    limits = {tuple(sorted(b.items())) for b in optimization['device_bounds'].values()}
    first = next(iter(optimization['device_bounds'].values()), {})
    return dict(
        targets=target['targets'], testbench=describe(target, target.get('feedback_input')),
        dc_criteria={k: v for k, v in target['dc_acceptance'].items() if k.startswith(('minimum', 'maximum'))},
        effective_device_size_limits_um=(
            {'W': [first['min_w_um'], first['max_w_um']], 'L': [first['min_l_um'], first['max_l_um']]}
            if len(limits) == 1 else optimization['device_bounds']),
        budgets=dict(max_dc_repair_decisions=optimization['max_dc_iterations'],
                     max_total_decisions=optimization['max_iterations'],
                     used_dc_repair=sum(1 for r in charged(history) if r['phase'] == 'dc_repair' or r.get('repair')),
                     used_total=len(charged(history)),
                     cost_free_refusals_left=MAX_FREE_REFUSALS-(len(history)-len(charged(history)))),
        max_changes_per_decision=dict(performance=MAX_CHANGES, dc_repair=MAX_CHANGES_DC))


def levers_table(target):
    """For each target metric the reference declares levers for: '+X' = raising X raises the metric, '-X' = lowering it."""
    levers = target.get('levers') or {}
    return {m: ' '.join(f"{'+' if sign == '+' else '-'}{p}" for p, sign in levers[m].items())
            for m in [*target['targets'], 'dc'] if m in levers}


def tunable_table(candidate, target):
    """Current value, tune range and unit of every tunable parameter, so nothing has to be read off the netlist."""
    bounds = target['optimization']['parameter_bounds']
    values = parameters(candidate)
    return {'columns': ['parameter', 'current', 'min', 'max', 'unit'],
            'rows': [[n, values[n], b['min'], b['max'], ('int ' if b.get('integer') else '')+b.get('unit', '')]
                     for n, b in bounds.items()]}


class SizingAgent:
    """Sizes the tunable parameters of whichever reference was selected; holds no topology knowledge."""
    name = 'sizing'

    def __init__(self, client):
        self.client = client
        self.memory = None   # design-memory view of the selected reference (set by the orchestrator before each run)
        self.prompt = Path(__file__).with_name('prompt.md').read_text()

    def run(self, target, candidate, measurement, history, feedback=None, rejections=None):
        try:
            derived = derive(target, parameters(candidate), measurement)
        except Exception as exc:  # arithmetic aid only; never block a sizing call
            derived = {'error': 'derived calculations unavailable: '+str(exc)}
        kinds = {n: d['kind'] for n, d in target['dc_acceptance']['devices'].items()}
        payload = dict(specs=sizing_specs(target, history), netlist=agent_netlist(candidate),
                       tunable=tunable_table(candidate, target), measurement=measurement_summary(measurement),
                       devices=device_table(measurement, kinds, derived.pop('devices', {})),
                       node_voltages=node_voltages(measurement), derived_calculations=derived)
        if self.memory:
            payload['memory'] = self.memory
        if levers_table(target):
            payload['levers'] = levers_table(target)
        table = history_table(history)
        if table:
            payload['history'] = table
        log = residual_log(Path(measurement['log']).read_text(), measurement)
        if log:
            payload['simulator_log'] = log
        if feedback:
            payload['reviewer_feedback'] = feedback
        if rejections:
            payload['rejected_this_decision'] = rejections
        sections = DC_SECTIONS if not measurement['dc_passed'] else PERFORMANCE_SECTIONS
        return self.client.ask(self.prompt, payload, schema(list(target['optimization']['allowed_parameters'])),
                               agent_name=self.name, use_rules=sections)
