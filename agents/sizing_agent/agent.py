"""Only the local Qwen model makes sizing decisions. Python enforces constraints."""
import math
import re
from pathlib import Path
from analog_agents.client import LocalClient


def obj(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)

TEXT = {'type':'string'}
SCHEMA = obj({'analysis':obj({'simulation_valid':{'type':'boolean'},
    'dc_op_valid':{'type':'boolean'},'main_problem':TEXT,'reasoning':TEXT}),
    'changes':{'type':'array','maxItems':3,'items':obj({
        'parameter':TEXT,'old_value':TEXT,'new_value':TEXT,'reason':TEXT})}})
PARAM = re.compile(r'^(\.param\s+)(\w+)(\s*=\s*)(\S+)(.*)$',re.M|re.I)

def number(value):
    match = re.fullmatch(r'([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(meg|[tgkmunpf])?',str(value),re.I)
    if not match: raise ValueError(f'Invalid SPICE scalar: {value!r}')
    scales={'':1,'t':1e12,'g':1e9,'meg':1e6,'k':1e3,'m':1e-3,'u':1e-6,'n':1e-9,'p':1e-12,'f':1e-15}
    result=float(match[1])*scales[(match[2] or '').lower()]
    if not math.isfinite(result): raise ValueError('Nonfinite value')
    return result

def parameters(text):
    pairs=[(m[2],m[4]) for m in PARAM.finditer(text)]
    if len(dict(pairs))!=len(pairs): raise ValueError('Duplicate parameter definitions')
    return dict(pairs)

def validate_candidate(reference, candidate, target):
    allowed=target['optimization']['allowed_parameters']
    def fixed(text):
        return PARAM.sub(lambda m:m[1]+m[2]+m[3]+'<SIZE>'+m[5] if m[2] in allowed else m[0],text)
    if fixed(reference)!=fixed(candidate): raise ValueError('Topology or fixed conditions changed')
    params=parameters(candidate)
    conditions=target['conditions']
    for key, condition in [('VDD','vdd_v'),('VCM','input_common_mode_v'),('CLOAD','load_capacitance_f')]:
        if not math.isclose(number(params[key]),conditions[condition],rel_tol=1e-9,abs_tol=0):
            raise ValueError('Reference/target condition mismatch: '+condition)
    temp=re.search(r'^\.temp\s+(\S+)',candidate,re.M|re.I)
    if not temp or number(temp[1])!=conditions['temperature_c']:
        raise ValueError('Reference/target temperature mismatch')
    corner=re.search(r'^\.lib\s+"[^"]+"\s+(\S+)',candidate,re.M|re.I)
    if not corner or corner[1].lower()!=target['corner'].lower():
        raise ValueError('Reference/target corner mismatch')
    for name in allowed:
        value=number(params[name]); bounds=target['optimization']['parameter_bounds'][name]
        low=next(v for k,v in bounds.items() if k.startswith('min'))
        high=next(v for k,v in bounds.items() if k.startswith('max'))
        if value<=0 or not low<=value<=high: raise ValueError(f'{name} out of bounds')
    logical=re.sub(r'\n\+\s*',' ',candidate)
    for constraint in target['optimization'].get('matching_constraints',[]):
        for device in constraint['devices']:
            line=re.search(r'^'+re.escape(device)+r'\s+.*$',logical,re.M|re.I)
            if not line or any('{'+p+'}' not in line[0] for p in constraint['shared_parameters']):
                raise ValueError('Matching constraint broken')
    for name in target['optimization'].get('integer_parameters', []):
        if not number(params[name]).is_integer():
            raise ValueError(f'{name} must be a positive integer')
    for device, dimensions in target['optimization'].get('device_dimensions', {}).items():
        line=re.search(r'^'+re.escape(device)+r'\s+.*$',logical,re.M|re.I)
        if not line: raise ValueError('Missing device: '+device)
        actual={k.upper():v for k,v in re.findall(r'([WL])=\{([^}]+)\}',line[0],re.I)}
        if actual!=dimensions: raise ValueError('Hard matching expression changed: '+device)
        bounds=target['optimization']['device_bounds'][device]
        for dimension, expression in dimensions.items():
            # Restricted product of named scalar parameters; never evaluate model text as code.
            value=math.prod(number(params[k]) for k in expression.split('*'))
            if not bounds['min_'+dimension.lower()+'_um']<=value<=bounds['max_'+dimension.lower()+'_um']:
                raise ValueError('Effective device dimension out of bounds: '+device+' '+dimension)
    for mirror in target['optimization'].get('mirror_constraints', []):
        line=re.search(r'^'+mirror['reference']+r'\s+.*$',logical,re.M|re.I)[0].split()
        other=re.search(r'^'+mirror['output']+r'\s+.*$',logical,re.M|re.I)[0].split()
        if line[1]!=line[2] or line[2:5]!=other[2:5]:
            raise ValueError('Invalid diode-connected mirror: '+mirror['reference'])
    return params

def apply_changes(reference, candidate, target, changes):
    before=validate_candidate(reference,candidate,target)
    updates={}
    for change in changes:
        key=change['parameter']
        if key not in target['optimization']['allowed_parameters'] or key in updates:
            raise ValueError('Disallowed or duplicate parameter')
        if not math.isclose(number(change['old_value']),number(before[key]),rel_tol=1e-9,abs_tol=0):
            raise ValueError('Qwen old_value does not match current parameter')
        number(change['new_value'])
        updates[key]=change['new_value']
    result=PARAM.sub(lambda m:m[1]+m[2]+m[3]+updates.get(m[2],m[4])+m[5],candidate)
    validate_candidate(reference,result,target)
    return result

class SizingAgent:
    def __init__(self, config):
        self.client=LocalClient(config)
        self.prompt=Path(__file__).with_name('prompt.md').read_text()

    def run(self, target, reference, candidate, full_log, measurements, history):
        return self.client.ask(self.prompt,dict(target=target,reference_spice=reference,
            candidate_spice=candidate,full_ngspice_log=full_log,measurements=measurements,
            current_parameters=parameters(candidate),
            last_rejection=history[-1].get('validation_error') if history else None,
            history=history),SCHEMA,agent_name='sizing')
