"""The global formula handbook: circuit-independent engineering input of the sizing agent."""
import hashlib
import re
from .config import ROOT

RULES_PATH = ROOT / 'ANALOG_DESIGN_RULES.md'


def select_sections(content, sections):
    """The handbook preamble plus the `## N.` sections listed (all of them when `sections` is True/None)."""
    if sections is True or sections is None:
        return content
    wanted = {int(n) for n in sections}
    head, *parts = re.split(r'(?m)^(?=## \d+\. )', content)
    kept = [p for p in parts if int(re.match(r'## (\d+)\.', p)[1]) in wanted]
    if not kept:
        raise ValueError('None of the requested handbook sections exist')
    return head + ''.join(kept)


def with_global_rules(prompt, payload, record, sections=None):
    """Load afresh and fail closed; never silently omit the global input.

    `sections` limits the handbook to the listed section numbers (the sizing agent sends only the ones its current
    phase needs); the hash recorded is that of the whole file.

    Applied at the shared public call boundary of all model adapters (`ask(..., use_rules=True)`).
    Does not mutate the caller's payload or accept its replacement rules.
    """
    content = RULES_PATH.read_text(encoding='utf-8')
    if not content.strip():
        raise ValueError('Global analog design rules file is empty')
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    record['global_rules_path'] = str(RULES_PATH)
    record['global_rules_sha256'] = digest
    enriched = dict(payload)
    record['global_rules_sections'] = 'all' if sections in (None, True) else sorted(sections)
    enriched['global_analog_design_rules'] = select_sections(content, sections)  # the hash is kept in the call record, not sent
    instruction = (
        '\nBefore reasoning on every invocation, read the '
        'global_analog_design_rules formula handbook supplied in this input. '
        'Its equations include assumptions and notation and are independent of any particular circuit.\n')
    return prompt + instruction, enriched
