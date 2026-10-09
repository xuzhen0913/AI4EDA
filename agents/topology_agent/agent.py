"""Chooses one reference topology for the specs. Knows topologies only through their profiles."""
from pathlib import Path
from analog_agents.schema import obj, array, enum, TEXT
from simulator.testbench import describe


def schema(ids):
    return obj({'selected_reference': enum(ids),
                'reasoning': TEXT,
                'ranking': array(obj({'reference': enum(ids), 'suitability': enum(['high', 'medium', 'low']),
                                      'reason': TEXT})),
                'expected_risks': TEXT})


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

    def select(self, specs, references, excluded=(), attempt_history=None, review_feedback=None):
        offered = [r for r in references.values() if r.id not in excluded]
        if not offered:
            raise ValueError('No candidate topology left to offer')
        ids = [r.id for r in offered]
        payload = dict(targets=specs['targets'], testbench=describe(specs),
                       candidates=[{'id': r.id, 'profile': r.profile} for r in offered])
        if attempt_history:
            payload['attempt_history'] = attempt_history
        if review_feedback:
            payload['review_feedback'] = review_feedback
        return validate_selection(self.client.ask(self.prompt, payload, schema(ids), agent_name=self.name), ids)
