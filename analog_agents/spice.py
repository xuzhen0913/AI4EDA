"""SPICE-text helpers shared by every module: scalars, `.param` lines, MOS instances, nodes."""
import math
import re

SCALES = {'': 1, 't': 1e12, 'g': 1e9, 'meg': 1e6, 'k': 1e3, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15}
SCALAR = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
PARAM = re.compile(r'^(\.param\s+)(\w+)(\s*=\s*)(\S+)(.*)$', re.M | re.I)
MOS_MODEL = re.compile(r'(pfet|pmos|nfet|nmos)', re.I)


def number(value):
    """SPICE scalar with optional engineering suffix -> float."""
    match = re.fullmatch('(' + SCALAR + r')(meg|[tgkmunpf])?', str(value), re.I)
    if not match:
        raise ValueError(f'Invalid SPICE scalar: {value!r}')
    result = float(match[1]) * SCALES[(match[2] or '').lower()]
    if not math.isfinite(result):
        raise ValueError('Nonfinite value')
    return result


def parameters(text):
    """name -> value string for every `.param` line; duplicates are an error."""
    pairs = [(m[2], m[4]) for m in PARAM.finditer(text)]
    if len(dict(pairs)) != len(pairs):
        raise ValueError('Duplicate parameter definitions')
    return dict(pairs)


def evaluate(expression, params):
    """Restricted product/quotient of named parameters and numbers; never eval()."""
    token = r'(?:[A-Za-z_]\w*|' + SCALAR + r'(?:meg|[tgkmunpf])?)'
    if not re.fullmatch(r'\s*' + token + r'(?:\s*[*/]\s*' + token + r')*\s*', expression, re.I):
        raise ValueError(f'Unsupported expression: {expression!r}')
    value = 1.0
    for op, name in re.findall(r'([*/]?)\s*(' + token + ')', expression, re.I):
        factor = number(params[name]) if re.match(r'[A-Za-z_]', name) and name in params else number(name)
        value = value / factor if op == '/' else value * factor
    return value


def logical_lines(text):
    """Statements without comments, continuation lines joined."""
    joined = re.sub(r'\n\+\s*', ' ', text)
    lines = []
    for line in joined.splitlines():
        line = re.split(r'\s[;$]', line, maxsplit=1)[0].strip()
        if line and not line.startswith('*'):
            lines.append(line)
    return lines


def mos_devices(text):
    """name -> terminals, model, polarity, W/L expressions and ngspice diagnostic prefix."""
    devices = {}
    for line in logical_lines(text):
        f = line.split()
        if len(f) < 6 or f[0][0].upper() not in 'MX' or not MOS_MODEL.search(f[5]):
            continue
        kind = 'pfet' if MOS_MODEL.search(f[5])[1].lower() in ('pfet', 'pmos') else 'nfet'
        dims = {k.upper(): v.strip('{}') for k, v in re.findall(r'\b([WL])=(\{[^}]*\}|\S+)', line, re.I)}
        prefix = f'@m.{f[0].lower()}.m{f[5].lower()}' if f[0][0].upper() == 'X' else f'@{f[0].lower()}'
        devices[f[0].upper()] = dict(kind=kind, drain=f[1].lower(), gate=f[2].lower(), source=f[3].lower(),
                                     body=f[4].lower(), model=f[5], W=dims.get('W'), L=dims.get('L'),
                                     diagnostic_prefix=prefix)
    return devices


def circuit_nodes(text):
    """Every non-ground node of the circuit, lower-cased, in first-use order."""
    nodes = []
    for line in logical_lines(text):
        f = line.split()
        if f[0][0].upper() in 'RCLVID' and len(f) >= 3:
            nodes += f[1:3]
        elif f[0][0].upper() in 'MX' and len(f) >= 6 and MOS_MODEL.search(f[5]):
            nodes += f[1:5]
    return list(dict.fromkeys(n.lower() for n in nodes if n != '0'))
