"""One registry for every selectable sizing model.

Select with SIZING_MODEL=<name> (or `run_all.sh --model <name>`). The legacy
SIZING_BACKEND=qwen|claude|codex still works and picks that backend's default model.
"""
import os

MODELS = {
    'qwen':   ('qwen',   None),
    'fable':  ('claude', 'claude-fable-5-1'),
    'sonnet': ('claude', 'claude-sonnet-5-5'),
    'opus':   ('claude', 'claude-opus-5-5'),
    'astra':  ('codex',  'gpt-6-astra'),
    'sol':    ('codex',  'gpt-6-sol'),
    'luna':   ('codex',  'gpt-6-luna'),
}
DEFAULTS = {'qwen': 'qwen', 'claude': 'sonnet', 'codex': 'astra'}
USAGE = ("Select a model, e.g. SIZING_MODEL=sonnet bash scripts/run_all.sh  (or: bash scripts/run_all.sh --model sol). "
         "Available: " + ', '.join(MODELS))


def resolve(model=None, backend=None):
    """Return (backend, alias, model_id). Explicit full ids with a known prefix are accepted."""
    model = (model or os.environ.get('SIZING_MODEL') or '').strip().lower() or None
    backend = (backend or os.environ.get('SIZING_BACKEND') or '').strip().lower() or None
    if backend and backend not in DEFAULTS:
        raise RuntimeError(f"Unknown SIZING_BACKEND {backend!r}. " + USAGE)
    if model is None:
        if backend is None:
            raise RuntimeError('No model selected. ' + USAGE)
        model = DEFAULTS[backend]
    if model in MODELS:
        kind, model_id = MODELS[model]
        alias = model
    elif model.startswith('claude-'):
        kind, model_id, alias = 'claude', model, model
    elif model.startswith('gpt-'):
        kind, model_id, alias = 'codex', model, model
    else:
        raise RuntimeError(f'Unknown model {model!r}. ' + USAGE)
    if backend and backend != kind:
        raise RuntimeError(f'SIZING_BACKEND={backend} conflicts with model {alias!r} (a {kind} model).')
    return kind, alias, model_id
