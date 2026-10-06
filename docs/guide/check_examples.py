"""Check documented edits in memory. Never changes runtime code or calls a model."""
import ast
import json
import re
import textwrap
from pathlib import Path
from analog_agents.config import load_config
from analog_agents.simulation import MockSimulation

ROOT=Path(__file__).resolve().parents[2]
text=(ROOT/'docs/guide/chapters.md').read_text()
results=[]
def section(number):
    found=re.search(r'^## '+re.escape(number)+r' .*?\n(.*?)(?=^## |^# |\Z)',text,re.S|re.M)
    assert found,number
    return found.group(1)
def blocks(number,lang='python'):
    return re.findall(r'```'+lang+r'\n(.*?)\n```',section(number),re.S)
def source(file):return (ROOT/file).read_text()
def change(src,old,new):
    assert src.count(old)==1,(old,src.count(old))
    return src.replace(old,new,1)
def checked(name,files):
    for file,code in files.items():ast.parse(code,filename=file)
    results.append({'example':name,'status':'passed','scope':'Exact edit locations matched current source; resulting Python parsed. No API or GPU execution.'})
run=source('analog_agents/run.py');agents=source('analog_agents/agents.py');client=source('analog_agents/client.py');sim=source('analog_agents/simulation.py')
old,new=blocks('8.1')
assert old in run
code=change(run,'            if step == cfg["max_iterations"]:',new+'\n            if step == cfg["max_iterations"]:')
checked('8.1 达标立即停止',{'run.py':code})
old,new=blocks('8.2');checked('8.2 传入历史',{'run.py':change(run,old,new)})
json_settings=json.loads('{'+blocks('8.3','json')[0].rstrip().rstrip(',')+'}')
new_method,new_signature,new_arg=blocks('8.3')
old_method='    def run(self, context):\n        return self.client.ask(self.prompt, context, SCHEMAS[self.name])'
a3=change(agents,old_method,new_method)
c3=change(client,'    def ask(self, prompt, payload, schema):',new_signature)
c3=change(c3,'            temperature=self.config["temperature"], max_tokens=self.config["max_tokens"],',new_arg)
checked('8.3 按角色温度',{'agents.py':a3,'client.py':c3})
# Exercise changed Agent.run without reading new files or opening a connection.
ns={'__name__':'analog_agents.example_agents','__package__':'analog_agents'}
exec(compile(a3,'agents.py','exec'),ns)
class Capture:
    config={'temperature':0.2,**json_settings}
    def ask(self,*args,**kwargs):return kwargs
agent=object.__new__(ns['Agent']);agent.name='sizing';agent.client=Capture();agent.prompt='test'
assert agent.run({})['temperature']==0.1
results[-1]['scope']+=' CPU stub confirmed sizing temperature=0.1.'
review_schema,creation,review=blocks('8.4')
opt='    "optimization": obj({"parameters": PARAMETERS, "rationale": TEXT, "stop": {"type": "boolean"}})'
a4=change(agents,opt,opt+',\n'+review_schema)
old_creation='    agents = {name: Agent(name, LocalClient(cfg)) for name in ("architecture", "sizing", "simulation", "optimization")}'
r4=change(run,old_creation,creation)
r4=change(r4,'            step_dir.mkdir()','            step_dir.mkdir()\n'+review)
checked('8.4 新增 Review Agent',{'agents.py':a4,'run.py':r4})
rule=blocks('8.5')[0]
old_advice='            advice = agents["optimization"].run({**context, **record})'
checked('8.5 确定性 Mock 优化',{'run.py':change(run,old_advice,rule)})
cfg=load_config();params=dict(input_w_um=20,input_l_um=1,load_w_um=40,stage2_w_um=80,bias_ua=40,compensation_pf=2)
ns={'cfg':cfg,'params':params,'result':{'all_targets_met_synthetically':False}}
exec(textwrap.dedent(rule),ns)
assert ns['next_params'] is not params and params['input_w_um']==20
out=ROOT/'.runtime/tmp/guide-example-check';out.mkdir(parents=True,exist_ok=True)
result=MockSimulation().run(ns['advice']['parameters'],cfg['specification'],['op'],out)
assert result['checks']['gain_db'] and result['synthetic']
results[-1]['scope']+=' CPU Mock tool verified gain target for documented starting parameters; no physical simulator.'
old,new=blocks('8.6');checked('8.6 参数上限',{'agents.py':change(agents,old,new)})
old,new=blocks('8.7');s7=change(sim,old,new);checked('8.7 显式读取参数',{'simulation.py':s7})
ns={'__name__':'analog_agents.example_sim','__package__':'analog_agents'}
exec(compile(s7,'simulation.py','exec'),ns)
from analog_agents.simulation import netlist
assert ns['netlist'](params,cfg['specification'],['op','ac'])==netlist(params,cfg['specification'],['op','ac'])
results[-1]['scope']+=' CPU test confirmed original and modified netlists are identical for sample parameters.'
factory,call=blocks('8.8');s8=sim+'\n'+factory+'\n'
r8=change(run,'from .simulation import MockSimulation','from .simulation import make_simulator')
r8=change(r8,'            result = MockSimulation().run(params, cfg["specification"], plan["analyses"], step_dir)',call)
checked('8.8 仿真工厂接口',{'run.py':r8,'simulation.py':s8})
old,new=blocks('9.4');checked('9.4 非 Qwen 模板参数',{'client.py':change(client,old,new)})
for sec in ['8.9','9.2','9.3']:
    code=re.search(r"python - <<'PY'\n(.*?)\nPY",section(sec),re.S).group(1)
    ast.parse(code)
    results.append({'example':sec+' 命令中的 Python 代码','status':'passed','scope':'Syntax parsed only. Model metadata/network/download code not executed.'})
report={'runtime_files_modified':False,'gpu_used':False,'network_used':False,'checks':results}
(ROOT/'docs/guide/example_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(f'{len(results)} documented example checks passed; no production edits or GPU calls.')
