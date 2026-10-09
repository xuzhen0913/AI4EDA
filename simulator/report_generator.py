"""English / Chinese PDF reports from on-disk workflow evidence. No model call, no invented results.

The report is topology-agnostic: the circuit is described by the selected reference's own profile
and by a connectivity table parsed from the final netlist, never by a hand-drawn schematic.
"""
import json
import re
import textwrap
from xml.sax.saxutils import escape
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

    def verbatim(text, width=100):
        for line in text.splitlines():
            story.append(Preformatted('\n'.join(textwrap.wrap(line, width, replace_whitespace=False, drop_whitespace=False) or ['']), code))

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
    p(tr('Model: ', '模型：')+str(summary.get('model'))+tr('; backend: ', '；后端：')+str(summary.get('design_backend'))
      + tr('. All three agents (topology, sizing, review) use this one model; the agents are topology-independent and only the selected reference carries circuit-specific information.',
           '。三个 Agent（拓扑选择、尺寸优化、性能审核）使用同一个模型；Agent 与具体拓扑无关，只有被选中的 reference 含具体电路信息。'))
    if summary.get('error'):
        p(summary['error'])
    p(tr('DC must pass for every transistor before AC measurements are allowed. Missing AC values below are not zeros or passing results.',
         '只有全部晶体管通过 DC 检查才允许进行 AC 测量。下列未测量的 AC 指标不是零，也不代表达标。'))
    table([[tr('Metric', '指标'), tr('Target', '目标'), tr('Final value (SI units)', '最终值（国际单位制）'), tr('Result', '判定')]]
          + [[k, str(v), fmt(m['metrics'].get(k)), missing if m['checks'].get(k) is None else tr('PASS', '达标') if m['checks'][k] else tr('FAIL', '未达标')]
             for k, v in specs['targets'].items()], [110, 100, 155, 115])
    p(tr('Conditions: ', '仿真条件：')+json.dumps(specs['conditions'])+'; '+specs['corner'])
    if specs.get('ac_validation'):
        p(tr('AC convention: A=V(out)/(V(vinp)-V(vinn)); L=-A; gain=20log10|A| at 1 Hz; PM=180+continuous phase(L) at the first falling unity-gain crossing. Unity-feedback small-signal estimate; feedback applied to VINP.',
             'AC 定义：A=V(out)/(V(vinp)-V(vinn))，L=-A；增益为 1 Hz 的 20log10|A|，相位裕度为第一次向下穿越单位增益处的 180°+L 的连续相位。这是反馈接 VINP 的单位反馈小信号估算。'))

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
    table(rows, [36, 118, 46, 70, 52, 34, 70, 54])

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

    # ------------------------------------------------------------------ 3. topology selection
    story.append(PageBreak())
    p(tr('Topology selection', '拓扑选择'), title)
    for r in rounds:
        if not r['selection']:
            continue
        sel = r['selection']
        p(tr(f"Round {r['entry']['round']}: selected {sel['selected_reference']}", f"第 {r['entry']['round']} 轮：选定 {sel['selected_reference']}"), heading)
        p(tr('Agent reasoning (original text): ', '模型分析（保留原文）：')+sel['reasoning'])
        if sel.get('excluded'):
            p(tr('Excluded after earlier failures: ', '此前失败而被排除：')+', '.join(sel['excluded']))
        table([[tr('Candidate', '候选'), tr('Suitability', '适配度'), tr('Reason (original text)', '理由（原文）')]]
              + [[x['reference'], x['suitability'], x['reason']] for x in sel['ranking']], [130, 55, 295])
        p(tr('Expected risks: ', '预期风险：')+sel['expected_risks'], small)
    if not any(r['selection'] for r in rounds):
        p(tr('No topology agent ran (baseline-only validation of a named reference).', '未运行拓扑 Agent（仅对指定 reference 做基准验证）。'))

    # ------------------------------------------------------------------ 4. final design
    final_values = parameters(last['net'])
    story.append(PageBreak())
    p(tr('Final circuit: ', '最终电路：')+last['entry']['reference'], title)
    profile = re.search(r'^\*\s*@profile-begin\s*\n(.*?)^\*\s*@profile-end', last['net'], re.M | re.S)
    if profile:
        p(tr('Reference profile (as supplied to the topology agent)', 'Reference 的 profile（提供给拓扑 Agent 的原文）'), heading)
        verbatim(re.sub(r'^\*\s?', '', profile[1], flags=re.M), 105)
    p(tr('Connectivity (parsed from the final netlist; widths/lengths in um)', '连线关系（由最终网表解析；宽长单位 um）'), heading)
    table([[tr('Device', '器件'), tr('Type', '类型'), 'D', 'G', 'S', 'B', 'W', 'L']] + mos_table(last['net'], final_values),
          [70, 45, 70, 70, 70, 50, 52, 50])
    p(tr('Sources and passive components', '电源、偏置源和无源器件'), heading)
    verbatim('\n'.join(l for l in last['net'].splitlines() if re.match(r'^(?:V\w+|I\w+|C\w+|R\w+)\s', l)))

    story.append(PageBreak())
    p(tr('DC acceptance and final sizing', 'DC 检查与最终尺寸'), title)
    dc = m.get('dc_acceptance')
    if dc:
        p(tr('All-device DC gate: ', '全部晶体管 DC 检查：')+str(m['dc_passed']))
        p(tr('Criterion: forward drain orientation, nonzero conduction, VGS/VSG above threshold, and VDS/VSD at least model VDSAT (strong-inversion saturation policy configured in the specs).',
             '判据：漏源方向正确、导通电流达到下限、VGS/VSG 达到阈值、VDS/VSD 不小于模型给出的 VDSAT（规格文件中配置的强反型饱和验收规则）。'))
        table([[tr('Device', '器件'), '|Id| (A)', tr('Overdrive (V)', '过驱动 (V)'), tr('Sat. margin (V)', '饱和裕量 (V)'), tr('Pass', '通过')]]
              + [[name, fmt(v.get('id_a')), fmt(v.get('overdrive_v')), fmt(v.get('saturation_margin_v')), v['passed']] for name, v in dc['devices'].items()],
              [95, 100, 100, 110, 75])
        p(tr('Failed devices: ', '未通过器件：')+(', '.join(dc['failed_devices']) or '-'))
    bounds, initial = parse_bounds(last['net']), last['sizing']['initial_parameters']
    table([[tr('Parameter', '参数'), tr('Tune range', '可调范围'), tr('Reference initial', 'Reference 初始'), tr('Final', '最终')]]
          + [[k, f"{eng(b['min'], b['unit'])}..{eng(b['max'], b['unit'])} {b['unit']}".strip(), initial[k], final_values[k]] for k, b in bounds.items()], [120, 140, 110, 110])
    p(tr('Sizes in um, currents in A, capacitances in F, voltages in V as declared by the reference. Integer ratio parameters: ',
         '尺寸单位 um，电流 A，电容 F，电压 V，以 reference 的声明为准。整数倍率参数：')
      + (', '.join(k for k, b in bounds.items() if b['integer']) or '-'))

    # ------------------------------------------------------------------ 5. rounds in detail
    for r in rounds:
        e = r['entry']
        story.append(PageBreak())
        p(tr(f"Round {e['round']} detail: {e['reference']}", f"第 {e['round']} 轮详情：{e['reference']}"), title)
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
        review = r['review']
        if review:
            p(tr('Review agent verdict: ', '审核 Agent 结论：')+verdict(review['verdict']), heading)
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
