"""Judges a finished sizing run against the specs and assigns blame (topology or sizing)."""
import math
from pathlib import Path
from analog_agents.analog_calc import derive
from analog_agents.evidence import device_table, measurement_summary, node_voltages, residual_log, sig
from analog_agents import memory as design_memory
from analog_agents.schema import obj, enum
from analog_agents.search import advice, diagnosis, history_table, move_text, open_moves, spec_check  # spec_check lives in search; re-exported here
from analog_agents.spice import number, parameters
from simulator.testbench import describe

VERDICTS = ['pass', 'fail_topology', 'fail_sizing']
# Only the verdict is the model's judgement; diagnosis and revision advice are built from the evidence by Python.
SCHEMA = obj({'verdict': enum(VERDICTS)})


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


def build_evidence(n, max_rounds, specs, reference, target, summary, history, measurement, candidate, earlier):
    """Everything the review agent sees, each fact once."""
    checks = spec_check(specs['targets'], measurement['metrics'])
    derived = derive(target, parameters(candidate), measurement)
    kinds = {k: d['kind'] for k, d in target['dc_acceptance']['devices'].items()}
    evidence = dict(
        round=n, max_rounds=max_rounds,
        testbench=describe(specs, target.get('feedback_input')),
        spec_check=checks,
        topology=dict(id=reference.id, profile=reference.profile),
        final=measurement_summary(measurement, metrics=False),
        devices=device_table(measurement, kinds, derived.get('devices', {})),
        node_voltages=node_voltages(measurement),
        parameters=parameter_table(candidate, target['optimization']['parameter_bounds']),
        sizing=dict(status=summary['status'], decisions=summary['iteration_count'],
                    dc_repair_decisions=summary['dc_iteration_count'], simulations=summary['simulation_count'],
                    max_decisions=summary['max_iterations'], max_dc_repair_decisions=summary['max_dc_iterations']),
        sizing_history=history_table(history),
        open_moves=move_text(open_moves(target.get('levers'), specs['targets'], measurement['metrics'], history, set(),
                                         target['optimization']['allowed_parameters'])),
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
        reply['diagnosis'] = diagnosis(evidence)
        reply['revision_advice'] = '' if reply['verdict'] == 'pass' else advice(evidence)
        reply['restart_sizing_from_reference'] = False  # the next round continues from the best point found
        reply['reviewer_verdict'] = reply['verdict']
        numbers_pass = (all(v['passed'] is True for v in evidence['spec_check'].values())
                        and evidence['final']['simulation_valid'] and evidence['final']['dc_passed'])
        if reply['verdict'] == 'pass' and not numbers_pass:
            reply.update(verdict='fail_sizing', revision_advice=advice(evidence),
                         verdict_overridden='Reviewer said pass but the numeric check fails; treated as fail_sizing.')
        return reply

    def remember(self, path, circuit, reference, specs, history):
        """Store this round's simulated points (successes and failures) in the design memory file.

        Near-duplicates of points already stored for the same reference are dropped and the per-reference cap is
        applied by `analog_agents.memory.add`. Returns how many points the reference's section holds afterwards."""
        memory = design_memory.load(path)
        points = [(design_memory.classify(p['dc_passed'], spec_check(specs['targets'], p['metrics'])), p['metrics'], p['point'])
                  for p in design_memory.history_points(history)]
        kept = design_memory.add(memory, (circuit, reference.id, design_memory.condition_key(specs)), reference,
                                 specs['targets'], points)
        design_memory.save(memory, path)
        return kept
