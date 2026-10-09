"""Topology-independent sizing: declarative constraint enforcement plus the model call."""
import math
from pathlib import Path
from analog_agents.analog_calc import derive
from analog_agents.evidence import device_table, measurement_summary, node_voltages, outcome, residual_log
from analog_agents.reference import agent_netlist, design_target
from analog_agents.schema import obj, array, TEXT
from analog_agents.spice import PARAM, evaluate, number, parameters
from simulator.testbench import describe

SCHEMA = obj({'analysis': obj({'simulation_valid': {'type': 'boolean'}, 'dc_op_valid': {'type': 'boolean'},
                               'main_problem': TEXT, 'reasoning': TEXT}),
              'changes': array(obj({'parameter': TEXT, 'old_value': TEXT, 'new_value': TEXT, 'reason': TEXT}), 3)})


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
            raise ValueError(f'{name} out of bounds')
    for name in optimization.get('integer_parameters', []):
        if not number(params[name]).is_integer():
            raise ValueError(f'{name} must be an integer within its declared bounds')
    for device, dimensions in optimization.get('device_dimensions', {}).items():
        limits = optimization['device_bounds'][device]
        for dimension, expression in dimensions.items():
            if not limits['min_'+dimension.lower()+'_um'] <= evaluate(expression, params) <= limits['max_'+dimension.lower()+'_um']:
                raise ValueError('Effective device dimension out of bounds: '+device+' '+dimension)
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
            raise ValueError('Disallowed or duplicate parameter')
        if not math.isclose(number(change['old_value']), number(before[key]), rel_tol=1e-9, abs_tol=0):
            raise ValueError('Model old_value does not match current parameter')
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
        targets=target['targets'], testbench=describe(target),
        dc_criteria={k: v for k, v in target['dc_acceptance'].items() if k.startswith('minimum')},
        effective_device_size_limits_um=(
            {'W': [first['min_w_um'], first['max_w_um']], 'L': [first['min_l_um'], first['max_l_um']]}
            if len(limits) == 1 else optimization['device_bounds']),
        budgets=dict(max_dc_repair_decisions=optimization['max_dc_iterations'],
                     max_total_decisions=optimization['max_iterations'],
                     used_dc_repair=sum(1 for r in history if r['phase'] == 'dc_repair'), used_total=len(history)))


def compact_history(history):
    """Decisions so far: what was changed and what the simulator then measured. Model prose is not evidence."""
    rows = []
    for i, row in enumerate(history):
        item = dict(iteration=row['iteration'], phase=row['phase'],
                    changes=[{'parameter': c['parameter'], 'old': c['old_value'], 'new': c['new_value']}
                             for c in row['changes']])
        if 'before' in row:
            item['before'] = outcome(row['before'])
        if row.get('validation_error'):
            item['rejected'] = row['validation_error']
        item['result'] = 'current measurement' if i == len(history)-1 else outcome(row['result'])
        rows.append(item)
    return rows


class SizingAgent:
    """Sizes the tunable parameters of whichever reference was selected; holds no topology knowledge."""
    name = 'sizing'

    def __init__(self, client):
        self.client = client
        self.prompt = Path(__file__).with_name('prompt.md').read_text()

    def run(self, target, candidate, measurement, history, feedback=None):
        try:
            derived = derive(target, parameters(candidate), measurement)
        except Exception as exc:  # arithmetic aid only; never block a sizing call
            derived = {'error': 'derived calculations unavailable: '+str(exc)}
        kinds = {n: d['kind'] for n, d in target['dc_acceptance']['devices'].items()}
        payload = dict(specs=sizing_specs(target, history), netlist=agent_netlist(candidate),
                       measurement=measurement_summary(measurement),
                       devices=device_table(measurement, kinds, derived.pop('devices', {})),
                       node_voltages=node_voltages(measurement), derived_calculations=derived,
                       history=compact_history(history))
        log = residual_log(Path(measurement['log']).read_text(), measurement)
        if log:
            payload['simulator_log'] = log
        if feedback:
            payload['reviewer_feedback'] = feedback
        return self.client.ask(self.prompt, payload, SCHEMA, agent_name=self.name, use_rules=True)
