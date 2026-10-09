"""Real ngspice execution, complete logs and conservative measurement validation."""
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from analog_agents.spice import SCALAR as NUMBER
from simulator.testbench import LOOP_POLARITY, deck

ROOT = Path(__file__).resolve().parents[1]

def save(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    temporary.replace(path)

def tool_paths():
    text = (ROOT/'tools_path.md').read_text()
    paths = re.findall(r'`(/[^`\n]+)`', text)
    executable = next(Path(p) for p in paths if p.endswith('/bin/ngspice'))
    library = next(Path(p) for p in paths if p.endswith('/sky130.lib.spice'))
    if not executable.is_file() or not library.is_file():
        raise FileNotFoundError('ngspice or SKY130 library in tools_path.md is missing')
    return executable, library

def dc_check(diagnostics, target):
    policy=target['dc_acceptance']; devices={}
    def voltage(node): return 0.0 if node=='0' else diagnostics.get('v('+node+')')
    for name, spec in policy['devices'].items():
        prefix=spec['diagnostic_prefix'].lower()
        op={key:diagnostics.get(prefix+'['+key+']') for key in ('id','vgs','vds','vth','vdsat')}
        nodes=[voltage(spec[k]) for k in ('drain','gate','source')]
        if any(v is None or not math.isfinite(v) for v in list(op.values())+nodes):
            devices[name]={'passed':False,'reason':'Missing or nonfinite DC diagnostics'}
            continue
        drain,gate,source=nodes
        sign=1 if spec['kind']=='nfet' else -1
        vds=sign*(drain-source);vgs=sign*(gate-source)
        overdrive=vgs-abs(op['vth']);margin=vds-abs(op['vdsat'])
        checks={'conducting':abs(op['id'])>=policy['minimum_drain_current_a'],
            'overdrive':overdrive>=policy['minimum_overdrive_v'],
            'saturation':margin>=policy['minimum_saturation_margin_v'],
            'forward_bias':vds>0}
        devices[name]={'passed':all(checks.values()),'checks':checks,'id_a':abs(op['id']),
            'vgs_or_vsg_v':vgs,'vds_or_vsd_v':vds,'vth_magnitude_v':abs(op['vth']),
            'vdsat_magnitude_v':abs(op['vdsat']),'overdrive_v':overdrive,'saturation_margin_v':margin}
    return {'passed':bool(devices) and all(v['passed'] for v in devices.values()),
            'failed_devices':[k for k,v in devices.items() if not v['passed']], 'devices':devices,
            'criterion':'Forward orientation, |Id| >= minimum, VGS/VSG-|Vth| >= minimum, VDS/VSD-|VDSAT| >= minimum'}


def parse_log(text, returncode, target, mode='full'):
    values = {m[0].lower(): float(m[1]) for m in re.findall(
        rf'^\s*([^\s=]+)\s*=\s*({NUMBER})(?:\s|$)', text, re.M)}
    metrics = {key: values.get(key) for key in target['targets']}
    diagnostics = {k:v for k,v in values.items() if k.startswith(('v(', 'i(', '@'))}
    issues = [line for line in text.splitlines() if re.search(
        r'error|failed|singular matrix|timestep too small|\bnan\b|\binf\b',line,re.I)]
    warnings = [l for l in text.splitlines() if 'warning' in l.lower()]
    required = metrics.values() if mode=='full' else [values.get('power_w')]+list(diagnostics.values())
    valid = returncode == 0 and not issues and bool(diagnostics) and all(v is not None and math.isfinite(v) for v in required)
    # Sign normalization is valid only when the expected low-frequency loop polarity holds.
    ac_policy=target.get('ac_validation',{})
    polarity=values.get(LOOP_POLARITY)
    polarity_ok=None
    if mode=='full' and ac_policy.get('require_positive_loop_real_lf'):
        polarity_ok=polarity is not None and math.isfinite(polarity) and polarity>0
        if not polarity_ok:
            issues.append('Invalid or missing normalized low-frequency loop polarity')
            valid=False
    dc=dc_check(diagnostics,target)
    # AC measurement/polarity errors must not relabel a passing DC operating point.
    dc_text=text.split('END_DC_OPERATING_POINT',1)[0]
    dc_errors=bool(re.search(r'error|failed|singular matrix|timestep too small|\bnan\b|\binf\b',dc_text,re.I))
    power=values.get('power_w')
    dc_numerical_valid=(returncode==0 and not dc_errors and bool(diagnostics)
        and power is not None and math.isfinite(power)
        and all(math.isfinite(v) for v in diagnostics.values()))
    dc['passed']=dc_numerical_valid and dc['passed']
    checks = {k: (None if v is None else all(v >= limit if op=='min' else v <= limit
        for op,limit in target['targets'][k].items())) for k,v in metrics.items()}
    return {'analysis_mode':mode,'metrics':metrics,'dc_operating_point':diagnostics,'simulation_valid':valid,
            'dc_acceptance':dc,'dc_passed':dc['passed'],'dc_numerical_valid':dc_numerical_valid,
            'ac_polarity':{'loop_real_lf':polarity,'passed':polarity_ok},
            'warnings':warnings,'errors':issues,'return_code':returncode,'checks':checks,
            'all_targets_passed':mode=='full' and valid and dc['passed'] and all(checks.values())}


class NgspiceRunner:
    """Runs the shared testbench around a candidate circuit; every simulation is archived under results/logs."""

    def __init__(self, results, target):
        self.results, self.target = Path(results), target
        (self.results/'logs').mkdir(parents=True,exist_ok=True)
        self.executable, self.library = tool_paths()
        self.count = 0
        self.dc_approved_hash = None
        self.next_number = max([int(p.stem.split('_')[-1]) for p in
            (self.results/'logs').glob('simulation_*.log')]+[0])+1

    def run(self, netlist, mode='dc'):
        original=Path(netlist).read_text()
        digest=hashlib.sha256(original.encode()).hexdigest()
        if mode=='full' and self.dc_approved_hash!=digest:
            raise ValueError('Full simulation requires a passing DC check for this exact candidate')
        source=deck(original,self.target,self.library,mode)
        number = self.next_number
        self.next_number += 1
        self.count += 1
        prefix = self.results/'logs'/f'simulation_{number:03d}'
        prefix.with_suffix('.spice').write_text(source)
        command = [str(self.executable), '-b', str(prefix.with_suffix('.spice').resolve())]
        started = time.perf_counter()
        code = None
        with prefix.with_suffix('.log').open('w') as log:
            log.write('COMMAND: '+json.dumps(command)+'\n');log.flush()
            try:
                result = subprocess.run(command, cwd=prefix.parent, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=180)
                code = result.returncode
            except subprocess.TimeoutExpired:
                log.write('\nERROR: ngspice timeout\n')
            log.write(f'\nRETURN_CODE: {code}\n')
        text = prefix.with_suffix('.log').read_text()
        record = parse_log(text, code, self.target, mode)
        if mode=='dc':self.dc_approved_hash=digest if record['dc_passed'] else None
        record.update(candidate_sha256=digest, simulation_number=number, seconds=time.perf_counter()-started,
                      log=str(prefix.with_suffix('.log')))
        save(prefix.with_suffix('.json'), record)
        return record
