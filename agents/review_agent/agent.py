"""Judges a finished sizing run against the specs and assigns blame (topology or sizing)."""
import math
from pathlib import Path
from analog_agents.analog_calc import derive
from analog_agents.evidence import device_table, measurement_summary, node_voltages, outcome, residual_log, sig
from analog_agents.schema import obj, enum, TEXT, BOOL
from analog_agents.spice import number, parameters
from simulator.testbench import describe

VERDICTS = ['pass', 'fail_topology', 'fail_sizing']
SCHEMA = obj({'verdict': enum(VERDICTS), 'diagnosis': TEXT, 'revision_advice': TEXT,
              'restart_sizing_from_reference': BOOL})


def spec_check(targets, metrics):
    """Exact comparison of measured metrics with targets; None means not measured."""
    rows = {}
    for name, limits in targets.items():
        value = metrics.get(name)
        ok = None if value is None or not math.isfinite(value) else all(
            value >= limit if op == 'min' else value <= limit for op, limit in limits.items())
        margin = None if ok is None else {op: sig(value - limit if op == 'min' else limit - value)
                                          for op, limit in limits.items()}
        rows[name] = dict(target=limits, value=sig(value), passed=ok, margin=margin)
    return rows


def parameter_table(candidate, bounds):
    """Final values with their tune range; the last column flags parameters sitting on a bound."""
    rows = []
    for name, value in parameters(candidate).items():
        b = bounds.get(name)
        if not b:
            continue
        x = number(value)
        at = 'min' if math.isclose(x, b['min'], rel_tol=0.01) else 'max' if math.isclose(x, b['max'], rel_tol=0.01) else ''
        rows.append([name, value, sig(b['min']), sig(b['max']), b['unit'], at])
    return {'columns': ['parameter', 'value', 'min', 'max', 'unit', 'on_bound'], 'rows': rows}


def history_for_review(history):
    """Every decision with the sizing agent's stated reason and what the simulator then measured."""
    rows = []
    for row in history:
        item = dict(iteration=row['iteration'], phase=row['phase'], diagnosis=row['analysis']['main_problem'],
                    changes=[{k: c[k] for k in ('parameter', 'old_value', 'new_value', 'reason')} for c in row['changes']])
        if 'before' in row:
            item['before'] = outcome(row['before'])
        if row.get('validation_error'):
            item['rejected'] = row['validation_error']
        if 'result' in row:
            item['result'] = outcome(row['result'])
        rows.append(item)
    return rows


def build_evidence(n, max_rounds, specs, reference, target, summary, history, measurement, candidate, earlier):
    """Everything the review agent sees, each fact once."""
    checks = spec_check(specs['targets'], measurement['metrics'])
    derived = derive(target, parameters(candidate), measurement)
    kinds = {k: d['kind'] for k, d in target['dc_acceptance']['devices'].items()}
    evidence = dict(
        round=n, max_rounds=max_rounds,
        testbench=describe(specs),
        spec_check=checks,
        topology=dict(id=reference.id, profile=reference.profile),
        final=measurement_summary(measurement, metrics=False),
        devices=device_table(measurement, kinds, derived.get('devices', {})),
        node_voltages=node_voltages(measurement),
        parameters=parameter_table(candidate, target['optimization']['parameter_bounds']),
        sizing=dict(status=summary['status'], decisions=summary['iteration_count'],
                    dc_repair_decisions=summary['dc_iteration_count'], simulations=summary['simulation_count'],
                    max_decisions=summary['max_iterations'], max_dc_repair_decisions=summary['max_dc_iterations']),
        sizing_history=history_for_review(history),
        earlier_rounds=earlier)
    log = residual_log(Path(measurement['log']).read_text(), measurement)
    if log:
        evidence['simulator_log'] = log
    return evidence


class ReviewAgent:
    name = 'review'

    def __init__(self, client):
        self.client = client
        self.prompt = Path(__file__).with_name('prompt.md').read_text()

    def review(self, evidence):
        reply = self.client.ask(self.prompt, evidence, SCHEMA, agent_name=self.name)
        if reply['verdict'] == 'pass':
            reply['revision_advice'], reply['restart_sizing_from_reference'] = '', False
        elif not reply['revision_advice'].strip():
            raise ValueError('A failing verdict must come with revision advice')
        reply['reviewer_verdict'] = reply['verdict']
        numbers_pass = (all(v['passed'] is True for v in evidence['spec_check'].values())
                        and evidence['final']['simulation_valid'] and evidence['final']['dc_passed'])
        if reply['verdict'] == 'pass' and not numbers_pass:
            failing = ', '.join(k for k, v in evidence['spec_check'].items() if v['passed'] is not True) or 'simulation validity'
            reply.update(verdict='fail_sizing', revision_advice='Failing or unmeasured: ' + failing,
                         verdict_overridden='Reviewer said pass but the numeric check fails; treated as fail_sizing.')
        return reply
