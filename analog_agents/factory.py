"""One model selection (SIZING_MODEL / --model) shared by all three agents.

Each agent gets its own client so its calls, tokens and raw replies are recorded separately.
"""
from collections import namedtuple
from analog_agents.client import LocalClient, ClaudeCliClient, CodexCliClient
from analog_agents.config import load_config
from analog_agents.models import resolve

Backend = namedtuple('Backend', 'kind alias model_id')


def backend():
    return Backend(*resolve())


def new_client(selection=None, config=None):
    selection = selection or backend()
    config = config or load_config()
    return {'claude': lambda: ClaudeCliClient(config, selection.model_id),
            'codex': lambda: CodexCliClient(config, selection.model_id),
            'qwen': lambda: LocalClient(config)}[selection.kind]()
