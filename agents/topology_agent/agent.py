"""Chooses one reference topology for the specs. Knows topologies only through their profiles."""
import math
from pathlib import Path
from analog_agents import memory as design_memory
from analog_agents.schema import obj, array, enum, TEXT
from analog_agents.search import num, spec_check, target_text
from simulator.testbench import describe


def schema(ids):
    return obj({'selected_reference': enum(ids),
                'reasoning': TEXT,
                'ranking': array(obj({'reference': enum(ids), 'suitability': enum(['high', 'medium', 'low']),
                                      'reason': TEXT})),
                'expected_risks': TEXT})


def verified_points(specs, reference):
    """The reference's simulated designs, compared with these specs by Python: the model never does that arithmetic.

    `meets_specs` is null when the design was simulated under other conditions (supply, load), so it proves nothing here."""
    points = []
    for point in reference.verified:
        same = all(math.isclose(v, specs['conditions'].get(k, math.nan), rel_tol=1e-9) for k, v in point['conditions'].items())
        checks = spec_check(specs['targets'], point['metrics']) if same else {}
        points.append(dict(metrics=point['metrics'], conditions_match=same,
                           meets_specs=all(c['passed'] is True for c in checks.values()) if same else None,
                           shortfalls=[f"{k} {num(c['value'])} (need {target_text(c)})"
                                       for k, c in checks.items() if c['passed'] is not True]))
    return points


def validate_selection(reply, ids):
    if reply['selected_reference'] not in ids:
        raise ValueError('Selected reference is not an offered candidate')
    if sorted(r['reference'] for r in reply['ranking']) != sorted(ids):
        raise ValueError('Ranking must list every offered candidate exactly once')
    return reply


class TopologyAgent:
    name = 'topology'

    def __init__(self, client):
        self.client = client
        self.prompt = Path(__file__).with_name('prompt.md').read_text()

    def select(self, specs, references, excluded=(), attempt_history=None, memory=None, circuit='opamp'):
        offered = [r for r in references.values() if r.id not in excluded]
        if not offered:
            raise ValueError('No candidate topology left to offer')
        ids = [r.id for r in offered]
        cond = design_memory.condition_key(specs)
        candidates = []
        for r in offered:
            item = {'id': r.id, 'profile': r.profile, 'verified_points': verified_points(specs, r)}
            known = design_memory.summary(memory or {}, circuit, r.id, cond, specs['targets'])
            if known:
                item['memory'] = known
            candidates.append(item)
        payload = dict(targets=specs['targets'], testbench=describe(specs), candidates=candidates)
        if attempt_history:
            payload['attempt_history'] = attempt_history
        return validate_selection(self.client.ask(self.prompt, payload, schema(ids), agent_name=self.name), ids)
