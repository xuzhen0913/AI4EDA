"""English / Chinese PDF reports from on-disk workflow evidence. No model call, no invented results.

The report is topology-agnostic: the circuit is described by the selected reference's own profile
by a connectivity table and a schematic that are both generated from the final netlist (no per-topology drawing code).
"""
import json
import re
import textwrap
from xml.sax.saxutils import escape
from collections import deque
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Preformatted
from analog_agents.reference import parse_bounds
from analog_agents.spice import evaluate, parameters

STATUS_ZH = {'targets_passed': '审核通过，全部指标达标', 'max_rounds_reached': '达到最大流程轮数仍未通过审核',
             'interrupted': '运行中断', 'baseline_only': '仅验证基准（未调用模型）'}
SIZING_ZH = {'targets_passed': '全部指标达标', 'dc_iteration_limit': '达到 DC 修复上限',
             'max_iterations_reached': '达到总迭代上限', 'interrupted': '运行中断', 'baseline_only': '仅验证基准'}
VERDICT_ZH = {'pass': '通过', 'fail_topology': '拓扑选择有问题', 'fail_sizing': '尺寸优化有问题'}


def eng(x, unit=''):
    """Currents and capacitances in SPICE engineering suffixes (1e-06 -> '1u'); everything else as plain numbers."""
    if x == 0 or unit not in ('A', 'F'):
        return f'{x:g}'
    for scale, suffix in ((1e9, 'G'), (1e6, 'meg'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, 'u'), (1e-9, 'n'), (1e-12, 'p'), (1e-15, 'f')):
        if abs(x) >= scale * 0.9999999:
            return f'{x / scale:.6g}{suffix}'
    return f'{x:g}'


PROFILE_ITEM = re.compile(r'^(?:- |[A-Z][A-Z ]*:|[A-Z][A-Z ]+$)')   # a bullet, a 'KEYWORD:' line or a heading such as ADVANTAGES


def reflow(profile):
    """The profile is hard-wrapped in the reference file; join each item's lines so the PDF wraps them once, at its own width."""
    items = []
    for line in profile.splitlines():
        if items and line.strip() and not PROFILE_ITEM.match(line):
            items[-1] += ' ' + line.strip()
        else:
            items.append(line.rstrip())
    return items


SUPPLY_NETS = ('vdd', '0', 'gnd')
PORTS = ('vinp', 'vinn', 'out')


def passive_table(netlist):
    """Two-terminal R/C/I/V elements of the circuit: [name, kind, node1, node2, value text]."""
    rows = []
    for line in re.sub(r'\n\+\s*', ' ', netlist).splitlines():
        f = re.split(r'\s[;$]', line, maxsplit=1)[0].split()
        if len(f) >= 4 and f[0][0].upper() in 'RCIV' and not f[0].startswith('*'):
            rows.append([f[0], f[0][0].upper(), f[1].lower(), f[2].lower(), ' '.join(f[3:])])
    return rows


def schematic(netlist, values, max_width=505, max_height=690):
    """Schematic drawn from the netlist alone (no topology knowledge): MOS symbols and two-terminal elements in rows ordered by
    channel distance from vdd (stacks read top to bottom), columns aligned along stacks, and every net wired with orthogonal
    lines in black (horizontal runs in the gaps between rows, vertical runs in per-net lanes left of each column).
    vdd and ground are drawn as supply symbols at the terminals instead of wires."""
    mos = mos_table(netlist, values)
    elements = [dict(name=r[0], kind=r[1], term={'d': r[2].lower(), 'g': r[3].lower(), 's': r[4].lower()}, label=f'{r[6]}/{r[7]}') for r in mos]
    for name, kind, n1, n2, value in passive_table(netlist):
        try:
            text = eng(evaluate(value.strip('{}'), values), kind if kind in 'CI' else '') if value.startswith('{') else value
        except (KeyError, ValueError):
            text = value
        elements.append(dict(name=name, kind=kind, term={'p': n1, 'n': n2}, label=str(text)[:18]))
    supply = lambda net: net in SUPPLY_NETS
    # an ideal voltage source to ground is a bias voltage: like a textbook, show its net as a labelled terminal, not a battery
    bias = {n for e in elements if e['kind'] == 'V' for k, n in e['term'].items() if e['term']['n' if k == 'p' else 'p'] in SUPPLY_NETS and n not in SUPPLY_NETS}
    elements = [e for e in elements if not (e['kind'] == 'V' and set(e['term'].values()) & bias)]
    # 1. rows: breadth-first distance from vdd through channels and two-terminal elements
    depth, queue = {'vdd': 0}, deque(['vdd'])
    links = [(e['term'].get('d', e['term'].get('p')), e['term'].get('s', e['term'].get('n'))) for e in elements if e['kind'] != 'V']
    while queue:
        net = queue.popleft()
        for a_, b_ in links:
            for x_, y_ in ((a_, b_), (b_, a_)):
                if x_ == net and not supply(y_) and y_ not in depth:
                    depth[y_] = depth[net] + 1
                    queue.append(y_)
    for e in elements:
        ends = [e['term'].get(k) for k in ('d', 's', 'p', 'n')]
        known = [depth[n] for n in ends if n in depth]
        e['level'] = min(known) if known else 99
    order = sorted({e['level'] for e in elements})
    for e in elements:
        e['row'] = order.index(e['level'])
    nrows = len(order)
    # 2. columns: keep a device under the device it is stacked on
    placed = {}
    for r in range(nrows):
        row = [e for e in elements if e['row'] == r]
        taken, pending = set(), []
        for e in row:
            ends = {n for k, n in e['term'].items() if k in 'dspn' and not supply(n)}
            above = [placed[o['name']] for o in elements if o['name'] in placed and o['row'] < r
                     and ends & {n for k, n in o['term'].items() if k in 'dspn'}]
            if above and above[0] not in taken:
                e['col'] = above[0]; taken.add(above[0]); placed[e['name']] = above[0]
            else:
                pending.append(e)
        for e in pending:
            c = 0
            while c in taken:
                c += 1
            e['col'] = c; taken.add(c); placed[e['name']] = c
    ncols = 1 + max(e['col'] for e in elements)
    # 3. terminals of every net: (row, col, order, element, terminal, gap)
    nets = {}
    for e in elements:
        for k, net in e['term'].items():
            gap = e['row'] + 1 if k == ('d' if e['kind'] == 'PMOS' else 's') or k == 'n' else e['row']
            nets.setdefault(net, []).append(dict(e=e, k=k, gap=gap, key=(e['row'], e['col'], gap - e['row'], 'dgspn'.index(k))))
    routed = {n: sorted(ts, key=lambda t: t['key']) for n, ts in nets.items() if not supply(n) and n not in bias and len(ts) > 1}
    singles = {n: ts for n, ts in nets.items() if not supply(n) and (len(ts) == 1 or n in bias)}
    # lanes (vertical runs) and tracks (horizontal runs)
    lanes, tracks = {}, {}
    def lane(col, net):
        return lanes.setdefault(col, {}).setdefault(net, len(lanes.get(col, {})))
    def track(gap, net):
        return tracks.setdefault(gap, {}).setdefault(net, len(tracks.get(gap, {})))
    routes = []
    for net, ts in routed.items():
        for t in ts:
            track(t['gap'], net)
            if t['k'] == 'g':
                lane(t['e']['col'], net)
        for a_, b_ in zip(ts, ts[1:]):
            if a_['gap'] != b_['gap']:
                lane(b_['e']['col'], net)
            routes.append((net, a_, b_))
    # 4. geometry
    SYM, LANE, ROW, TR, GAP0 = 96, 6, 56, 6, 22
    colx, x = [], 6
    for c in range(ncols):
        colx.append(x)
        x += 10 + LANE * len(lanes.get(c, {})) + SYM
    width = x
    gaph = [GAP0 + TR * len(tracks.get(g, {})) for g in range(nrows + 1)]
    height = sum(gaph) + ROW * nrows + 4
    D = Drawing(width, height)
    def Y(v):
        return height - v
    rowy = []                 # downward coordinate of each row's top
    acc = 0
    for r in range(nrows):
        acc += gaph[r]
        rowy.append(acc)
        acc += ROW
    gapy = [rowy[g] - gaph[g] if g < nrows else rowy[-1] + ROW for g in range(nrows + 1)]   # top edge of each gap
    palette = [colors.HexColor(h) for h in ('#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22')]
    netcolor = {n: colors.black for n in nets}
    def line(x1, y1, x2, y2, color=colors.black, w=1):
        D.add(Line(x1, Y(y1), x2, Y(y2), strokeColor=color, strokeWidth=w))
    def text(s, x_, y_, size=6, anchor='start', color=colors.black, bold=False):
        D.add(String(x_, Y(y_), s, fontName='Helvetica-Bold' if bold else 'Helvetica', fontSize=size, textAnchor=anchor, fillColor=color))
    def lane_x(col, net):
        return colx[col] + 4 + LANE * lane(col, net)
    def track_y(gap, net):
        return gapy[gap] + 18 + TR * track(gap, net)
    pos = {}                  # (element, terminal) -> (x, y of the pin, direction)
    for e in elements:
        xs = colx[e['col']] + 10 + LANE * len(lanes.get(e['col'], {}))
        yt = rowy[e['row']]
        xp = xs + 20
        if e['kind'] in ('NMOS', 'PMOS'):
            line(xs, yt + 14, xs, yt + 42); line(xs + 6, yt + 14, xs + 6, yt + 42)
            line(xs + 6, yt + 14, xp, yt + 14); line(xs + 6, yt + 42, xp, yt + 42)
            line(xp, yt, xp, yt + 14); line(xp, yt + 42, xp, yt + ROW)
            if e['kind'] == 'PMOS':
                D.add(Circle(xs - 3, Y(yt + 28), 3, strokeColor=colors.black, fillColor=colors.white, strokeWidth=1))
                gx = xs - 6
            else:
                gx = xs
            upper, lower = ('s', 'd') if e['kind'] == 'PMOS' else ('d', 's')
            pos[(e['name'], upper)] = (xp, yt, -1); pos[(e['name'], lower)] = (xp, yt + ROW, 1); pos[(e['name'], 'g')] = (gx, yt + 28, 0)
            text(e['name'], xs + 26, yt + 26, 6.5, bold=True); text(e['kind'] + ' ' + e['label'], xs + 26, yt + 35, 5.5)
        else:
            line(xp, yt, xp, yt + 14); line(xp, yt + 42, xp, yt + ROW)
            if e['kind'] == 'V':
                line(xp - 8, yt + 20, xp + 8, yt + 20, w=1.4); line(xp - 4, yt + 26, xp + 4, yt + 26, w=1.4)
                line(xp, yt + 14, xp, yt + 20); line(xp, yt + 26, xp, yt + 42)
                text('+', xp + 10, yt + 19, 6)
            elif e['kind'] == 'I':
                D.add(Circle(xp, Y(yt + 28), 14, strokeColor=colors.black, fillColor=colors.white, strokeWidth=1))
                line(xp, yt + 36, xp, yt + 20); line(xp, yt + 20, xp - 3, yt + 25); line(xp, yt + 20, xp + 3, yt + 25)
            elif e['kind'] == 'C':
                line(xp, yt + 14, xp, yt + 24); line(xp - 8, yt + 24, xp + 8, yt + 24, w=1.4)
                line(xp - 8, yt + 32, xp + 8, yt + 32, w=1.4); line(xp, yt + 32, xp, yt + 42)
            else:
                D.add(Rect(xp - 4, Y(yt + 42), 8, 28, strokeColor=colors.black, fillColor=colors.white, strokeWidth=1))
            pos[(e['name'], 'p')] = (xp, yt, -1); pos[(e['name'], 'n')] = (xp, yt + ROW, 1)
            text(e['name'], xp + 16, yt + 26, 6.5, bold=True); text(e['label'], xp + 16, yt + 35, 5.5)
    # supply symbols and single-terminal nets
    for net, ts in nets.items():
        for t in ts:
            px, py, d = pos[(t['e']['name'], t['k'])]
            if supply(net):
                if t['k'] == 'g':
                    line(px, py, px - 8, py); text('gnd' if net != 'vdd' else 'vdd', px - 10, py + 2, 5.5, 'end')
                elif net == 'vdd':
                    line(px, py, px, py - 8); line(px - 5, py - 8, px + 5, py - 8, w=1.6); text('vdd', px + 7, py - 6, 5.5)
                else:
                    line(px, py, px, py + 6); line(px - 6, py + 6, px + 6, py + 6, w=1.4); line(px - 4, py + 9, px + 4, py + 9, w=1.2); line(px - 2, py + 12, px + 2, py + 12, w=1)
            elif net in singles:
                if t['k'] == 'g':
                    line(px, py, px - 12, py, netcolor[net]); text(net, px - 14, py + 2, 6.5, 'end', colors.black, net in PORTS or net in bias)
                else:
                    line(px, py, px, py + 8 * d, netcolor[net]); text(net, px + 3, py + 8 * d + (0 if d < 0 else 6), 6.5, 'start', colors.black, net in PORTS or net in bias)
    # wires
    def exit_point(t):
        px, py, d = pos[(t['e']['name'], t['k'])]
        c = netcolor[t['net']]
        ty = track_y(t['gap'], t['net'])
        if t['k'] == 'g':
            lx = lane_x(t['e']['col'], t['net'])
            line(px, py, lx, py, c); line(lx, py, lx, ty, c)
            return lx, ty
        line(px, py, px, ty, c)
        return px, ty
    for net, ts in routed.items():
        for t in ts:
            t['net'] = net
        ends = [exit_point(t) for t in ts]
        c = netcolor[net]
        for _, a_, b_ in (r for r in routes if r[0] == net):
            ax, ay = ends[ts.index(a_)]; bx, by = ends[ts.index(b_)]
            if a_['gap'] == b_['gap']:
                line(ax, ay, bx, by, c)
            else:
                lx = lane_x(b_['e']['col'], net)
                line(ax, ay, lx, ay, c); line(lx, ay, lx, by, c); line(lx, by, bx, by, c)
        if len(ts) > 2:
            for ex, ey in ends:
                D.add(Circle(ex, Y(ey), 1.6, strokeColor=c, fillColor=c))
        fx, fy = ends[0]
        text(net, fx + 2, fy - 1.5, 6.5 if net in PORTS else 5.5, 'start', colors.black, net in PORTS)
    scale = min(1.0, max_width / width, max_height / height)
    if scale < 1:
        D.scale(scale, scale)
        D.width, D.height = width * scale, height * scale
    return D


def mos_table(netlist, values):
    """Connectivity rows for every MOS in the netlist, with W/L evaluated from final parameters."""
    logical = re.sub(r'\n\+\s*', ' ', netlist)
    rows = []
    for line in logical.splitlines():
        f = line.split()
        # transistor instances: M... or wrapped X... instances whose model name says fet
        if len(f) < 6 or f[0][0].upper() not in 'MX' or 'fet' not in f[5].lower():
            continue
        dims = {k.upper(): v for k, v in re.findall(r'([WL])=\{([^}]+)\}', line, re.I)}
        try:
            w, l = (f'{evaluate(dims[k], values):.4g}' for k in ('W', 'L'))
        except (KeyError, ValueError):
            w = l = '?'
        rows.append([f[0], 'PMOS' if 'pfet' in f[5].lower() else 'NMOS', f[1], f[2], f[3], f[4], w, l])
    return rows


def generate(results, language='en'):
    def tr(en, zh):
        return zh if language == 'zh' else en

    def read(path):
        return json.loads(path.read_text())

    summary, specs = read(results/'summary.json'), read(results/'specs.json')
    rounds = []
    for entry in summary['rounds']:
        rdir = results/f"round_{entry['round']:02d}"
        sizing = read(rdir/'summary.json')
        rounds.append(dict(entry=entry, sizing=sizing, history=read(rdir/'history.json'),
                           measurement=read(rdir/'logs'/f"simulation_{sizing['final_simulation_number']:03d}.json"),
                           net=(rdir/'candidate.spice').read_text(),
                           selection=read(rdir/'topology_selection.json') if (rdir/'topology_selection.json').exists() else None,
                           review=read(rdir/'review.json') if (rdir/'review.json').exists() else None))
    if not rounds:
        raise ValueError('No completed round to report')
    last = rounds[-1]
    m = last['measurement']

    pdfmetrics.registerFont(TTFont('ReportLatin', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('ReportCJK', '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
    latin = pdfmetrics.getFont('ReportLatin').face.charToGlyph

    def markup(value):
        runs = []
        for char in str(value):
            font = 'ReportLatin' if ord(char) in latin else 'ReportCJK'
            if runs and runs[-1][0] == font:
                runs[-1] = (font, runs[-1][1]+char)
            else:
                runs.append((font, char))
        return ''.join(f'<font name="{font}">{escape(chars)}</font>' for font, chars in runs)

    body = ParagraphStyle('body', fontName='ReportLatin', fontSize=9, leading=14, spaceAfter=7, wordWrap='CJK')
    title = ParagraphStyle('title', parent=body, fontSize=18, leading=26, spaceAfter=12)
    heading = ParagraphStyle('heading', parent=body, fontSize=12, leading=18, spaceBefore=9)
    small = ParagraphStyle('small', parent=body, fontSize=7.5, leading=11)
    code = ParagraphStyle('code', fontName='Courier', fontSize=7, leading=9)
    story = []

    def p(value, style=body):
        story.append(Paragraph(markup(value), style))

    def table(rows, widths):
        t = Table([[Paragraph(markup(v), small) for v in row] for row in rows], colWidths=widths, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e4edf5')),
                               ('GRID', (0, 0), (-1, -1), .3, colors.grey), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        story.append(t)

    def verbatim(text, width=115, hanging=4):
        """Monospaced text; a long line continues indented under itself instead of restarting at column 0."""
        for line in text.splitlines():
            indent = re.match(r'\s*', line)[0]
            wrapped = textwrap.wrap(line, width, subsequent_indent=indent+' '*hanging, replace_whitespace=False) or ['']
            story.append(Preformatted('\n'.join(wrapped), code))

    missing = tr('Not simulated / unavailable', '未仿真／无有效结果')

    def fmt(v):
        return missing if v is None else f'{v:.7g}' if isinstance(v, float) else str(v)

    def verdict(v):
        return VERDICT_ZH.get(v, v) if language == 'zh' else v

    # ------------------------------------------------------------------ 1. outcome
    p(tr('SKY130 Op-Amp: Three-Agent Design Report', 'SKY130 运放：三 Agent 协同设计报告'), title)
    p(tr('Outcome: ', '最终结果：')+tr(summary['status'], STATUS_ZH.get(summary['status'], summary['status'])), heading)
    p(tr('Final topology: ', '最终拓扑：')+str(summary['final_reference'])+tr('; rounds used: ', '；使用轮数：')
      + f"{summary['rounds_run']}/{summary['max_rounds']}"+tr('; final reviewer verdict: ', '；最终审核结论：')
      + (verdict(summary['final_verdict']) if summary.get('final_verdict') else '-'))
    if summary.get('model') is None:
        p(tr('No model was called: this is a baseline-only simulation of one untouched reference.',
             '未调用模型：这是对一个未修改 reference 的仅基准仿真。'))
    else:
        p(tr('Model: ', '模型：')+str(summary['model'])+tr('; backend: ', '；后端：')+str(summary.get('design_backend'))
          + tr('. All three agents (topology, sizing, review) use this one model; the agents are topology-independent and only the selected reference carries circuit-specific information.',
               '。三个 Agent（拓扑选择、尺寸优化、性能审核）使用同一个模型；Agent 与具体拓扑无关，只有被选中的 reference 含具体电路信息。'))
    if summary.get('error'):
        p(summary['error'])
    p(tr('DC must pass for every transistor, with the closed loop holding OUT at VCM, before AC measurements are allowed. Missing AC values below are not zeros or passing results.',
         '只有全部晶体管通过 DC 检查、且闭环把 OUT 稳在 VCM，才允许进行 AC 测量。下列未测量的 AC 指标不是零，也不代表达标。'))
    table([[tr('Metric', '指标'), tr('Target', '目标'), tr('Final value (SI units)', '最终值（国际单位制）'), tr('Result', '判定')]]
          + [[k, str(v), fmt(m['metrics'].get(k)), missing if m['checks'].get(k) is None else tr('PASS', '达标') if m['checks'][k] else tr('FAIL', '未达标')]
             for k, v in specs['targets'].items()], [110, 100, 155, 115])
    if not m['simulation_valid']:
        p(tr('WARNING: the final simulation is marked INVALID, so the PASS/FAIL marks above are not evidence: ', '警告：最终仿真被标记为无效，上表的达标/未达标不能作为依据：')
          + '; '.join(m['errors'] or ['no AC result']))
    p(tr('Conditions: ', '仿真条件：')+json.dumps(specs['conditions'])+'; '+specs['corner'])
    if specs.get('ac_validation'):
        if m.get('bias') == 'closed_loop':
            fb = ((m.get('ac_polarity') or {}).get('feedback_input') or '?').upper()
            p(tr(f'Bias and AC: the DC operating point is found with unity negative feedback closed from OUT to {fb} (an inductor, short at DC), '
                 f'so OUT rests at VCM as in real use; the other input is held at VCM. AC is measured on the OPEN loop (the inductor is open at AC): '
                 f'1 V AC is injected at {fb} through a DC-blocking capacitor and the loop gain is T=-V(out)/V(injected), positive at low frequency '
                 'for negative feedback. Gain=20log10|T| at the lowest frequency; UGB = first falling 0 dB crossing; PM=180+continuous phase(T) there '
                 '(small-signal estimate).',
                 f'偏置与 AC：直流工作点在 OUT 经电感（直流短路）接回 {fb} 的单位负反馈下求得，OUT 因此像实际使用时一样停在 VCM，另一输入保持在 VCM；'
                 f'AC 在开环下测量（电感对交流开路）：在 {fb} 处经隔直电容注入 1 V AC，环路增益 T=-V(out)/V(注入)，负反馈时低频为正。'
                 '增益为最低频率处的 20log10|T|，UGB 为第一次向下穿越 0 dB 处，相位裕度为该处 180°+T 的连续相位（小信号估算）。'))
        else:  # evidence recorded by the first testbench: open-loop bias, L=-A, assumed an inverting circuit
            p(tr('AC convention: A=V(out)/(V(vinp)-V(vinn)); L=-A; gain=20log10|A| at 1 Hz; PM=180+continuous phase(L) at the first falling unity-gain crossing. Unity-feedback small-signal estimate; feedback applied to VINP.',
                 'AC 定义：A=V(out)/(V(vinp)-V(vinn))，L=-A；增益为 1 Hz 的 20log10|A|，相位裕度为第一次向下穿越单位增益处的 180°+L 的连续相位。这是反馈接 VINP 的单位反馈估算。'))

    # ------------------------------------------------------------------ 2. workflow
    p(tr('Workflow and rounds', '流程与各轮结果'), heading)
    p(tr('Workflow: the topology agent reads the specs and the profile of every reference and selects one; the sizing agent sizes it (DC repair at most %d decisions, %d decisions in total, per sizing run); the review agent judges the result against the specs and, on failure, blames the topology or the sizing and sends advice to that agent. At most %d rounds; a sizing run may use more decisions overall than one round.'
         % (specs['budgets']['max_dc_iterations'], specs['budgets']['max_iterations'], specs['budgets']['max_rounds']),
         '流程：拓扑选择 Agent 阅读规格和各 reference 的 profile 并选定一个；尺寸优化 Agent 对其优化（每次 sizing 的 DC 修复最多 %d 次、总决策最多 %d 次）；性能审核 Agent 依据规格判定，不达标时判断问题在拓扑还是在尺寸，并把修改意见返回给相应 Agent。整体最多 %d 轮；整体各轮的 sizing 决策总数可以超过单轮上限。'
         % (specs['budgets']['max_dc_iterations'], specs['budgets']['max_iterations'], specs['budgets']['max_rounds'])))
    rows = [[tr('Round', '轮'), tr('Topology', '拓扑'), tr('Topology agent ran', '拓扑 Agent 运行'), tr('Sizing result', '尺寸优化结果'),
             tr('Decisions (DC/total)', '决策数 (DC/总)'), tr('Sims', '仿真'), tr('Failed specs', '未达标指标'), tr('Review verdict', '审核结论')]]
    for r in rounds:
        e = r['entry']
        rows.append([e['round'], e['reference'], tr('yes', '是') if e['topology_agent_ran'] else tr('no (kept)', '否（沿用）'),
                     tr(e['sizing_status'], SIZING_ZH.get(e['sizing_status'], e['sizing_status'])),
                     f"{e['dc_decisions']}/{e['decisions']}", e['simulations'],
                     ', '.join(e.get('failed_specs', [])) or '-', verdict(e['verdict']) if e.get('verdict') else '-'])
    table(rows, [40, 114, 46, 70, 52, 34, 70, 54])

    s = summary
    stats = [[tr('Statistic', '统计项'), tr('Value', '记录值')],
             [tr('All sizing decisions', '尺寸优化总决策数'), sum(r['entry']['decisions'] for r in rounds)],
             [tr('ngspice simulations', '仿真调用次数'), s['simulation_count']],
             [tr('Model calls (topology / sizing / review)', '模型调用次数（拓扑/尺寸/审核）'),
              ' / '.join(str(s['calls_by_agent'].get(k, 0)) for k in ('topology', 'sizing', 'review'))],
             [tr('Prompt tokens', '输入 token'), s['tokens']['prompt_tokens']], [tr('Completion tokens', '输出 token'), s['tokens']['completion_tokens']],
             [tr('Total tokens', '总 token'), s['tokens']['total_tokens']]]
    for k, v in s.get('tokens_by_agent', {}).items():
        stats.append([tr(f'  tokens, {k} agent', f'  {k} Agent 的 token'), v['total_tokens']])
    stats += [[tr('Usage complete', '统计完整'), s['token_usage_complete']],
              [tr('Total time', '总耗时'), f"{s['total_time_seconds']:.3f} s ({s['total_time_seconds']/60:.2f} min)"]]
    table(stats, [240, 240])
    p(tr('One run is not a statistical benchmark. Each DC-only or full ngspice invocation counts once. Total time excludes model startup and PDF generation. No monetary cost was measured.',
         '一次运行不是统计基准。一次纯 DC 或完整 ngspice 调用各计一次仿真。总耗时不含模型启动和 PDF 生成；未测量货币成本。'), small)

    # ------------------------------------------------------------------ 3. the workflow, round by round, in the order it ran
    def dc_section(r):
        mm, e = r['measurement'], r['entry']
        dc = mm.get('dc_acceptance')
        p(tr('Final simulation of this round: ', '本轮最终仿真：')+f"#{e.get('final_simulation_number')}; "
          + tr('metrics ', '指标 ')+json.dumps(mm['metrics'], ensure_ascii=False)+tr('; valid: ', '；有效：')+str(mm['simulation_valid']))
        if dc:
            p(tr('DC gate (every transistor and the closed loop): ', 'DC 检查（全部晶体管和闭环）：')+str(mm['dc_passed']))
            loop = dc.get('loop') or {}
            if loop.get('output_error_v') is not None:
                p(tr('Closed loop: V(out) - VCM = ', '闭环：V(out) - VCM = ')+f"{loop['output_error_v']:.4g} V"
                  + tr(f" (limit {loop['maximum_output_error_v']} V): ", f"（限值 {loop['maximum_output_error_v']} V）：")
                  + (tr('regulated', '已稳在 VCM') if loop['passed'] else tr('NOT regulating', '未稳在 VCM')))
            table([[tr('Device', '器件'), '|Id| (A)', tr('Overdrive (V)', '过驱动 (V)'), tr('Sat. margin (V)', '饱和裕量 (V)'), tr('Pass', '通过')]]
                  + [[name, fmt(v.get('id_a')), fmt(v.get('overdrive_v')), fmt(v.get('saturation_margin_v')), v['passed']] for name, v in dc['devices'].items()],
                  [95, 100, 100, 110, 75])
            p(tr('Failed devices: ', '未通过器件：')+(', '.join(dc['failed_devices']) or '-'))
        values, bounds, initial = parameters(r['net']), parse_bounds(r['net']), r['sizing']['initial_parameters']
        table([[tr('Parameter', '参数'), tr('Tune range', '可调范围'), tr('Reference initial', 'Reference 初始'), tr('Final', '最终')]]
              + [[k, f"{eng(b['min'], b['unit'])}..{eng(b['max'], b['unit'])} {b['unit']}".strip(), initial[k], values[k]] for k, b in bounds.items()], [120, 140, 110, 110])
        p(tr('Sizes in um, currents in A, capacitances in F, voltages in V as declared by the reference. Integer ratio parameters: ',
             '尺寸单位 um，电流 A，电容 F，电压 V，以 reference 的声明为准。整数倍率参数：')
          + (', '.join(k for k, b in bounds.items() if b['integer']) or '-'))

    drawn = {}
    for r in rounds:
        e = r['entry']
        story.append(PageBreak())
        p(tr(f"Round {e['round']}", f"第 {e['round']} 轮"), title)
        # step 1: topology agent
        p(tr('Step 1 - Topology selection', '步骤 1 - 拓扑选择'), heading)
        sel = r['selection']
        if sel:
            p(tr(f"Selected {sel['selected_reference']}", f"选定 {sel['selected_reference']}"))
            p(tr('Agent reasoning (original text): ', '模型分析（保留原文）：')+sel['reasoning'])
            if sel.get('excluded'):
                p(tr('Excluded after earlier failures: ', '此前失败而被排除：')+', '.join(sel['excluded']))
            table([[tr('Candidate', '候选'), tr('Suitability', '适配度'), tr('Reason (original text)', '理由（原文）')]]
                  + [[x['reference'], x['suitability'], x['reason']] for x in sel['ranking']], [130, 55, 295])
            p(tr('Expected risks: ', '预期风险：')+sel['expected_risks'], small)
        elif e.get('topology_agent_ran') is False and len(rounds) > 1 and e['round'] > 1:
            p(tr('The topology agent did not run: the reviewer blamed the sizing, so ', '拓扑 Agent 未运行：审核认为问题在尺寸，沿用 ')+e['reference']+tr(' is kept.', '。'))
        else:
            p(tr('No topology agent ran (baseline-only validation of a named reference).', '未运行拓扑 Agent（仅对指定 reference 做基准验证）。'))
        # the selected circuit
        p(tr('Circuit used in this round: ', '本轮使用的电路：')+e['reference'], heading)
        if e['reference'] in drawn:
            p(tr(f"Same circuit as in round {drawn[e['reference']]}; its profile and schematic are given there.", f"与第 {drawn[e['reference']]} 轮相同，profile 与电路图见该轮。"))
        else:
            drawn[e['reference']] = e['round']
            profile = re.search(r'^\*\s*@profile-begin\s*\n(.*?)^\*\s*@profile-end', r['net'], re.M | re.S)
            if profile:
                p(tr('Reference profile (as supplied to the topology agent)', 'Reference 的 profile（提供给拓扑 Agent 的原文）'), heading)
                verbatim('\n'.join(reflow(re.sub(r'^\*\s?', '', profile[1], flags=re.M))), hanging=2)
            rows0 = mos_table(r['net'], parameters(r['net']))
            story.append(PageBreak())
            p(tr('Schematic (drawn automatically from the netlist: textbook style: vdd and ground as symbols, bias voltages and ports as labelled terminals, dots at junctions, stacks read top to bottom; W/L in um at the end of this round)',
                 '电路图（由网表自动绘制：仿教科书画法：vdd 与地用符号表示，偏置电压和端口用带名字的端点，连线交汇处画圆点，堆叠自上而下；W/L 单位 um，取本轮结束时的值）'), heading)
            story.append(schematic(r['net'], parameters(r['net'])))
            p(tr('Connectivity table', '连线关系表'), heading)
            table([[tr('Device', '器件'), tr('Type', '类型'), 'D', 'G', 'S', 'B', 'W', 'L']] + rows0, [70, 45, 70, 70, 70, 50, 52, 50])
            p(tr('Sources and passive components', '电源、偏置源和无源器件'), heading)
            verbatim('\n'.join(l for l in r['net'].splitlines() if re.match(r'^(?:V\w+|I\w+|C\w+|R\w+)\s', l)))
        # step 2: sizing agent
        p(tr('Step 2 - Sizing', '步骤 2 - 尺寸优化'), heading)
        p(tr('Sizing run status: ', '尺寸优化状态：')+tr(e['sizing_status'], SIZING_ZH.get(e['sizing_status'], e['sizing_status']))
          + (tr(' (continued with reviewer advice)', '（已带审核修改意见）') if e.get('sizing_feedback_used') else ''))
        if not r['history']:
            p(tr('No sizing decision completed.', '没有完成尺寸决策。'))
        for row in r['history']:
            p(tr('Iteration ', '第 ')+str(row['iteration'])+' / '+row.get('phase', 'sizing'), heading)
            p(tr('Model reasoning (original text): ', '模型分析（保留原文）：')+json.dumps(row['analysis'], ensure_ascii=False))
            table([[tr('Parameter', '参数'), tr('Before', '修改前'), tr('After', '修改后'), tr('Model reason', '模型理由原文')]]
                  + [[v['parameter'], v['old_value'], v['new_value'], v['reason']] for v in row['changes']], [100, 65, 65, 250])
            result = row.get('result') or {}
            p(tr('Result metrics: ', '更新后指标：')+json.dumps(result.get('metrics'), ensure_ascii=False))
            p(tr('DC passed after update: ', '更新后 DC 通过：')+str(result.get('dc_passed')))
            if row.get('validation_error'):
                p(row['validation_error'])
        p(tr('Result of the sizing run', '本轮尺寸优化的结果'), heading)
        dc_section(r)
        # step 3: review agent
        review = r['review']
        if review:
            p(tr('Step 3 - Review', '步骤 3 - 性能审核'), heading)
            p(tr('Review agent verdict: ', '审核 Agent 结论：')+verdict(review['verdict']))
            if review.get('verdict_overridden'):
                p(review['verdict_overridden'])
            p(tr('Diagnosis (original text): ', '诊断（原文）：')+review['diagnosis'])
            if review['revision_advice']:
                p(tr('Revision advice returned to the ', '返回给')+(tr('topology agent', '拓扑 Agent') if review['verdict'] == 'fail_topology' else tr('sizing agent', '尺寸优化 Agent'))
                  + tr(' (original text): ', '的修改意见（原文）：')+review['revision_advice'])

    story.append(PageBreak())
    p(tr('Full final DC diagnostics', '完整最终 DC 诊断值'), title)
    table([[tr('Quantity', '物理量／标识符'), tr('Value', '实测值')]] + [[k, fmt(v)] for k, v in m['dc_operating_point'].items()], [355, 125])
    story.append(PageBreak())
    p(tr('Complete final candidate netlist', '完整最终候选网表'), title)
    verbatim(last['net'])
    p(tr('Sources: summary.json, specs.json and, per round, topology_selection.json, history.json, sizing_calls.json, candidate.spice, review.json and the numbered simulation files under logs/ (each holds the complete deck, log and parsed record).',
         '来源：summary.json、specs.json，以及每轮的 topology_selection.json、history.json、sizing_calls.json、candidate.spice、review.json 和 logs/ 下编号的仿真文件（含完整仿真网表、日志和解析记录）。'), small)

    dest = results/('final_report_zh.pdf' if language == 'zh' else 'final_report.pdf')

    def footer(canvas, doc):
        canvas.setFont('ReportLatin', 8)
        canvas.drawRightString(550, 23, str(doc.page))
    SimpleDocTemplate(str(dest), pagesize=(595, 842), leftMargin=45, rightMargin=45, topMargin=40, bottomMargin=40,
                      title=tr('SKY130 op-amp three-agent design', 'SKY130 运放三 Agent 协同设计报告')).build(story, onFirstPage=footer, onLaterPages=footer)
    return dest
