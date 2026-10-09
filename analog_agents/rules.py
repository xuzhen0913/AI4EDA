"""The global formula handbook: circuit-independent engineering input of the sizing agent."""
import hashlib
from .config import ROOT

RULES_PATH = ROOT / 'ANALOG_DESIGN_RULES.md'


def with_global_rules(prompt, payload, record):
    """Load afresh and fail closed; never silently omit the global input.

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
    enriched['global_analog_design_rules'] = content  # the hash is kept in the call record, not sent
    instruction = (
        '\nBefore reasoning on every invocation, read the complete '
        'global_analog_design_rules formula handbook supplied in this input. '
        'Its equations include assumptions and notation and are independent of any particular circuit.\n')
    return prompt + instruction, enriched
