import pytest
from analog_agents.models import resolve


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv('SIZING_MODEL', raising=False)
    monkeypatch.delenv('SIZING_BACKEND', raising=False)


@pytest.mark.parametrize('name,kind,model_id',[
    ('qwen','qwen',None),('fable','claude','claude-fable-5-1'),('sonnet','claude','claude-sonnet-5-5'),
    ('opus','claude','claude-opus-5-5'),('astra','codex','gpt-6-astra'),('sol','codex','gpt-6-sol'),
    ('luna','codex','gpt-6-luna'),('Sol','codex','gpt-6-sol')])
def test_aliases(monkeypatch,name,kind,model_id):
    monkeypatch.setenv('SIZING_MODEL',name)
    assert resolve()[0::2]==(kind,model_id)


def test_legacy_backend_defaults(monkeypatch):
    for backend,alias in (('qwen','qwen'),('claude','sonnet'),('codex','astra')):
        monkeypatch.setenv('SIZING_BACKEND',backend)
        assert resolve()[1]==alias


def test_errors(monkeypatch):
    with pytest.raises(RuntimeError,match='No model selected'):resolve()
    monkeypatch.setenv('SIZING_MODEL','nope')
    with pytest.raises(RuntimeError,match='Unknown model'):resolve()
    monkeypatch.setenv('SIZING_MODEL','sol');monkeypatch.setenv('SIZING_BACKEND','claude')
    with pytest.raises(RuntimeError,match='conflicts'):resolve()
    monkeypatch.setenv('SIZING_BACKEND','codex')
    assert resolve()[1]=='sol'
