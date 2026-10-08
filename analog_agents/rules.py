"""Shared, backend-independent engineering input for every agent invocation."""
import hashlib
from .config import ROOT

RULES_PATH = ROOT / 'ANALOG_DESIGN_RULES.md'


def with_global_rules(prompt, payload, record):
    """Load afresh and fail closed; never silently omit the global input.

    All model adapters must use this at their shared public call boundary.
    Do not mutate a caller's payload or accept its replacement rules.
    """
    content = RULES_PATH.read_text(encoding='utf-8')
    if not content.strip():
        raise ValueError('Global analog design rules file is empty')
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    record['global_rules_path'] = str(RULES_PATH)
    record['global_rules_sha256'] = digest
    enriched = dict(payload)
    enriched['global_analog_design_rules'] = {
        'filename': RULES_PATH.name, 'sha256': digest, 'content': content}
    instruction = (
        '\nBefore reasoning on every invocation, read the complete '
        'global_analog_design_rules formula handbook supplied in this input. '
        'Its equations include assumptions and notation; it contains no prescribed '
        'parameter-adjustment strategy.\n')
    return prompt + instruction, enriched
