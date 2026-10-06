"""Offline migration regressions. Model replies are fixtures, not GPU inference."""
import json
import os
import subprocess
from pathlib import Path
from jsonschema import validate
from analog_agents import run
from analog_agents.agents import SCHEMAS
from analog_agents.config import ROOT, load_config


def test_activation_from_parent_directory():
    result = subprocess.run(['bash', '-c',
        'source "$1/scripts/activate.sh"; "$PROJECT_PYTHON" -c '
        '\'import json,sys,os; from analog_agents.config import ROOT; '
        'print(json.dumps([str(ROOT),sys.executable,os.environ["OUTLINES_CACHE_DIR"]]))\'',
        'migration-test', str(ROOT)], cwd=ROOT.parent, check=True, capture_output=True, text=True)
    root, python, outlines = json.loads(result.stdout)
    assert root == str(ROOT)
    assert python == '/home/xu/.venv/bin/python'
    assert outlines == str(ROOT / '.runtime/cache/outlines')


def test_full_workflow_with_fixture_model(monkeypatch, tmp_path):
    """Exercise real orchestration, Mock tool and PDF, using explicit offline fixtures."""
    cfg = load_config()
    cfg['max_iterations'] = 1
    parameters = dict(input_w_um=20,input_l_um=1,load_w_um=40,
                      stage2_w_um=80,bias_ua=40,compensation_pf=2)
    class FixtureClient:
        def __init__(self, config): self.calls = []
        def ask(self, prompt, payload, schema, agent_name='test'):
            responses = {
                'architecture': {'topology':'two_stage_cmos_opamp',
                                 'rationale':'Offline migration fixture; not model inference.', 'assumptions':[]},
                'sizing': {'parameters':parameters, 'rationale':'Fixture starting point.'},
                'simulation': {'analyses':['op','ac'], 'rationale':'Mock tool only.'},
                'optimization': {'parameters':{**parameters,'input_w_um':50},
                                 'rationale':'Fixture update for pipeline test.', 'stop':False},
            }
            response = responses[agent_name]
            validate(response, schema)
            self.calls.append({'agent':agent_name,'status':'passed','usage':None,'seconds':0.0})
            return response
    monkeypatch.setattr(run,'load_config',lambda:cfg)
    monkeypatch.setattr(run,'LocalClient',FixtureClient)
    monkeypatch.setattr(run,'project_path',lambda relative:tmp_path/relative)
    run.main()
    experiment = next((tmp_path/'outputs').iterdir())
    result = json.loads((experiment/'summary.json').read_text())
    assert result['status']=='completed'
    assert result['evaluations']==2 and result['number_of_iterations']==1
    assert result['final']['parameters']['input_w_um']==50
    assert result['final']['simulation']['checks']['gain_db']
    assert not result['token_cost']['usage_complete']
    assert len(result['calls'])==5
    assert (experiment/'REPORT.pdf').read_bytes().startswith(b'%PDF')
    assert (experiment/'iteration-1/conceptual_not_executed.cir').exists()
