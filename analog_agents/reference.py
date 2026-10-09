"""Reference-circuit library: the ONLY place topology-specific information lives.

Every file in circuits/opamp/reference/ is one candidate topology and contains

    * @profile-begin ... * @profile-end     free text read by the topology and review agents
    * @analyses-begin ... * @analyses-end   optional JSON list of pre-computed estimates that suit this topology
    notes (ordinary comments), then the circuit itself.

The circuit is the design under test only. Tunable parameters are the `.param` lines annotated
`; tune MIN..MAX [UNIT] [int]`; their device terminals, models, W/L expressions and DC-check
diagnostics are read from the netlist, so nothing is declared twice. Supply, sources, load, library,
DC diagnostics and AC measurements come from the shared testbench (simulator/testbench.py).
"""
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from analog_agents.spice import PARAM, evaluate, logical_lines, mos_devices, number
from simulator.testbench import check_circuit

PROFILE = re.compile(r'^\*\s*@profile-begin\s*\n(.*?)^\*\s*@profile-end\s*$', re.M | re.S)
ANALYSES = re.compile(r'^\*\s*@analyses-begin\s*\n(.*?)^\*\s*@analyses-end\s*$', re.M | re.S)
TUNE = re.compile(r';\s*tune\s+(\S+?)\.\.(\S+)((?:\s+\S+)*)\s*$', re.I)
DEVICE_ROLES = ('input_device', 'gain_device', 'bias_device', 'mirror_reference_device', 'first_stage_load_device')


@dataclass(frozen=True)
class Reference:
    id: str
    path: Path
    text: str
    profile: str
    analyses: list
    bounds: dict      # tunable name -> {'min', 'max', 'unit', 'integer'}
    initial: dict     # every .param name -> value string
    devices: dict     # MOS name -> terminals/model/kind/W/L/diagnostic_prefix


def agent_netlist(text):
    """What the sizing agent reads: notes and circuit, without the selector's profile or the tooling block."""
    return re.sub(r'\n{3,}', '\n\n', ANALYSES.sub('', PROFILE.sub('', text))).strip('\n') + '\n'


def parse_bounds(text):
    bounds = {}
    for match in PARAM.finditer(text):
        tune = TUNE.search(match[5])
        if not tune:
            continue
        extra = tune[3].split()
        bounds[match[2]] = dict(min=number(tune[1]), max=number(tune[2]), integer='int' in extra,
                                unit=next((x for x in extra if x != 'int'), ''))
    return bounds


def parse_reference(text, name, path=None):
    profile, analyses = PROFILE.search(text), ANALYSES.search(text)
    if not profile or not profile[1].strip():
        raise ValueError(f'{name}: missing @profile block')
    for match in PARAM.finditer(text):
        if len(re.findall(r'\w+\s*=', match[0].split(';')[0])) != 1:
            raise ValueError(f'{name}: exactly one .param assignment per line: {match[0].strip()}')
    circuit = agent_netlist(text)
    check_circuit(circuit)
    initial = {m[2]: m[4] for m in PARAM.finditer(text)}
    bounds = parse_bounds(text)
    if not bounds:
        raise ValueError(f'{name}: no tunable parameter (annotate .param lines with "; tune MIN..MAX [UNIT] [int]")')
    body = '\n'.join(l for l in logical_lines(text) if not l.lower().startswith('.param'))
    for param, b in bounds.items():
        value = number(initial[param])
        if not b['min'] < b['max'] or not b['min'] <= value <= b['max']:
            raise ValueError(f'{name}: initial {param}={initial[param]} outside tune range {b["min"]}..{b["max"]}')
        if b['integer'] and not value.is_integer():
            raise ValueError(f'{name}: integer parameter {param} has non-integer initial value')
        if not re.search(r'\{[^}]*\b' + param + r'\b[^}]*\}', body):
            raise ValueError(f'{name}: tunable {param} is not used by the circuit')
    devices = mos_devices(text)
    if not devices:
        raise ValueError(f'{name}: no MOS device found')
    for device, d in devices.items():
        if not d['W'] or not d['L']:
            raise ValueError(f'{name}: {device} needs W= and L=')
        evaluate(d['W'], initial), evaluate(d['L'], initial)
    specs = json.loads(re.sub(r'^\*\s?', '', analyses[1], flags=re.M)) if analyses else []
    for spec in specs:
        named = [spec[k] for k in DEVICE_ROLES if k in spec]
        named += [d for stack in spec.get('stacks', {}).values() for item in stack for d in (item if isinstance(item, list) else [item])]
        unknown = [d for d in named if d.upper() not in devices]
        if unknown:
            raise ValueError(f'{name}: analysis {spec.get("type")} names unknown devices {unknown}')
    return Reference(name, Path(path) if path else Path(name), text,
                     re.sub(r'^\*\s?', '', profile[1], flags=re.M).strip(), specs, bounds, initial, devices)


def load_reference(path):
    path = Path(path)
    return parse_reference(path.read_text(), path.stem, path)


def load_references(directory):
    refs = [load_reference(p) for p in sorted(Path(directory).glob('*.spice'))]
    if not refs:
        raise FileNotFoundError(f'No *.spice references in {directory}')
    return {r.id: r for r in refs}


def design_target(specs, reference):
    """Specs (generic) + what the reference's netlist declares -> the target the sizing layer validates against."""
    target = copy.deepcopy(specs)
    limits = specs['device_limits']
    target['optimization'] = dict(
        max_iterations=specs['budgets']['max_iterations'], max_dc_iterations=specs['budgets']['max_dc_iterations'],
        allowed_parameters=list(reference.bounds),
        parameter_bounds={n: dict(b) for n, b in reference.bounds.items()},
        integer_parameters=[n for n, b in reference.bounds.items() if b['integer']],
        device_dimensions={n: {'W': d['W'], 'L': d['L']} for n, d in reference.devices.items()},
        device_bounds={n: dict(limits) for n in reference.devices})
    target.setdefault('dc_acceptance', {})['devices'] = copy.deepcopy(reference.devices)
    target['derived_analyses'] = copy.deepcopy(reference.analyses)
    return target

