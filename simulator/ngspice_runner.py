"""Real ngspice execution, complete logs and conservative measurement validation."""
import json
import math
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'

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

def parse_log(text, returncode, target):
    values = {m[0].lower(): float(m[1]) for m in re.findall(
        rf'^\s*([^\s=]+)\s*=\s*({NUMBER})(?:\s|$)', text, re.M)}
    metrics = {key: values.get(key) for key in target['targets']}
    diagnostics = {k:v for k,v in values.items() if k.startswith(('v(', 'i(', '@m.'))}
    issues = [line for line in text.splitlines() if re.search(
        r'error|failed|singular matrix|timestep too small|\bnan\b|\binf\b',line,re.I)]
    warnings = [l for l in text.splitlines() if 'warning' in l.lower()]
    valid = returncode == 0 and not issues and all(v is not None and math.isfinite(v) for v in metrics.values())
    checks = {k: valid and all(v >= limit if op=='min' else v <= limit
        for op,limit in target['targets'][k].items()) for k,v in metrics.items()}
    return {'metrics':metrics,'dc_operating_point':diagnostics,'simulation_valid':valid,
            'warnings':warnings,'errors':issues,'return_code':returncode,'checks':checks,
            'all_targets_passed':valid and all(checks.values())}

class NgspiceRunner:
    def __init__(self, results, target):
        self.results, self.target = Path(results), target
        (self.results/'logs').mkdir(parents=True,exist_ok=True)
        self.executable, self.library = tool_paths()
        self.count = 0
        self.next_number = max([int(p.stem.split('_')[-1]) for p in
            (self.results/'logs').glob('simulation_*.log')]+[0])+1

    def run(self, netlist):
        number = self.next_number
        self.next_number += 1
        self.count += 1
        prefix = self.results/'logs'/f'simulation_{number:03d}'
        source = Path(netlist).read_text()
        if str(self.library) not in source:
            raise ValueError('Netlist must use the SKY130 library specified in tools_path.md')
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
        (self.results/'current.log').write_text(text)
        record = parse_log(text, code, self.target)
        record.update(simulation_number=number, seconds=time.perf_counter()-started,
                      log=str(prefix.with_suffix('.log')))
        save(prefix.with_suffix('.json'), record)
        save(self.results/'measurements.json', record)
        return record
