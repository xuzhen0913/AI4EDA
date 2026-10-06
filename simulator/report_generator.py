"""English PDF from on-disk experiment evidence. No model call or invented results."""
import json
import re
import textwrap
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Preformatted
from reportlab.graphics.shapes import Drawing, Line, String, Circle
from agents.sizing_agent.agent import parameters


def topology(netlist):
    """Connected schematic for the fixed reference, guarded by actual netlist connectivity."""
    logical=re.sub(r'\n\+\s*',' ',netlist)
    devices={f[0].upper():f for line in logical.splitlines() if (f:=line.split()) and f[0].upper().startswith('XM')}
    expected={'XM1':('n1','vinp','ntail','0'),'XM2':('n2','vinn','ntail','0'),
        'XM3':('n1','n1','vdd','vdd'),'XM4':('n2','n1','vdd','vdd'),
        'XM5':('ntail','vbias_n','0','0'),'XM6':('out','n2','0','0'),
        'XM7':('out','vbias_p','vdd','vdd'),
        'XMBIAS_N':('vbias_n','vbias_n','0','0'),
        'XMBIAS_P':('vbias_p','vbias_p','vdd','vdd')}
    if set(devices)!=set(expected):raise ValueError('Schematic device list differs from netlist')
    for key,nodes in expected.items():
        if tuple(x.lower() for x in devices[key][1:5])!=nodes:
            raise ValueError('Schematic connectivity differs from netlist: '+key)
        kind='pfet' if key in ('XM3','XM4','XM7','XMBIAS_P') else 'nfet'
        if kind not in devices[key][5]:raise ValueError('Unexpected transistor model: '+key)
    elements={f[0].upper():f for line in logical.splitlines() if (f:=line.split()) and f[0][0].upper() in 'CIV'}
    for key,nodes in {'CCOMP':('n2','out'),'CLOAD_OUT':('out','0'),
                      'IBIAS_N':('vdd','vbias_n'),'IBIAS_P':('vbias_p','0'),
                      'VSUPPLY':('vdd','0'),'VINP':('vinp','0'),'VINN':('vinn','0')}.items():
        if tuple(elements[key][1:3])!=nodes:raise ValueError('Unexpected connection: '+key)
    values=parameters(netlist)
    d=Drawing(500,445)
    ink=colors.HexColor('#173f58')
    def label(x,y,text,size=8):d.add(String(x,y,text,fontName='Helvetica',fontSize=size,fillColor=ink))
    def wire(*points):
        for (x,y),(X,Y) in zip(points,points[1:]):d.add(Line(x,y,X,Y,strokeColor=ink,strokeWidth=1.1))
    def dot(x,y):d.add(Circle(x,y,2,strokeColor=ink,fillColor=ink))
    def mos(x,y,name,pmos=False):
        # D/S vertical pins; PMOS source is the upper pin, NMOS source the lower.
        wire((x,y+20),(x,y+11),(x+6,y+11),(x+6,y-11),(x,y-11),(x,y-20))
        wire((x-7,y-14),(x-7,y+14));wire((x-25,y),(x-7,y))
        if pmos:d.add(Circle(x-11,y,3,strokeColor=ink,fillColor=colors.white))
        label(x+10,y+2,name,8)
    def current(x,y,name):
        d.add(Circle(x,y,13,strokeColor=ink,fillColor=colors.white))
        wire((x,y+8),(x,y-7));wire((x-3,y-3),(x,y-7),(x+3,y-3))
        label(x+17,y+3,name,7);label(x+17,y-8,values['IBIAS']+'A',7)
    # Common supply and ground rails physically connect every branch.
    wire((30,415),(480,415));label(31,428,'VDD = '+values['VDD']+' V',10)
    wire((30,60),(480,60));label(31,43,'0 / GND',9)
    wire((255,60),(255,52));wire((246,52),(264,52));wire((249,49),(261,49));wire((252,46),(258,46))
    # NMOS bias reference, diode connection and tail gate bias.
    mos(45,120,'MBIAS_N');current(45,330,'IBIAS_N')
    wire((45,415),(45,343));wire((45,317),(45,140));wire((45,100),(45,60))
    wire((45,190),(15,190),(15,120),(20,120));dot(45,190)
    wire((45,170),(100,170),(100,120),(175,120));dot(45,170)
    label(48,180,'VBIAS_N',7)
    # First stage: PMOS current mirror above the NMOS differential pair.
    mos(150,350,'M3',True);mos(250,350,'M4',True)
    mos(150,240,'M1');mos(250,240,'M2')
    for x in (150,250):
        wire((x,415),(x,370));wire((x,330),(x,260))
        wire((x,220),(x,195))
        dot(x,415)
    wire((150,300),(110,300),(110,380),(225,380),(225,350));dot(150,300)
    wire((110,350),(125,350));dot(110,350)
    label(154,311,'N1',8)
    wire((80,240),(125,240));label(80,250,'VINP (+)',8)
    wire((210,240),(225,240));label(204,250,'VINN (-)',8)
    wire((150,195),(250,195));wire((200,195),(200,140));dot(200,195)
    label(205,181,'NTAIL',7);mos(200,120,'M5');wire((200,100),(200,60))
    # Second-stage PMOS bias reference and current source.
    mos(340,350,'MBIAS_P',True);wire((340,415),(340,370));dot(340,415)
    wire((340,330),(340,133));current(340,120,'IBIAS_P');wire((340,107),(340,60))
    wire((340,270),(305,270),(305,350),(315,350));dot(340,270)
    wire((340,320),(405,320),(405,350));dot(340,320)
    label(349,327,'VBIAS_P',7)
    # M6/M7 output branch; N2 drives the second-stage gate.
    mos(430,350,'M7',True);mos(430,180,'M6')
    wire((430,415),(430,370));dot(430,415)
    wire((430,330),(430,200));wire((430,160),(430,60))
    wire((250,280),(390,280),(390,180),(405,180));dot(250,280)
    label(254,288,'N2',8)
    # Miller capacitor: N2 to OUT, not to a bias node at wire crossings.
    wire((250,305),(282,305));wire((288,305),(430,305));dot(250,305);dot(430,305)
    wire((282,296),(282,314));wire((288,296),(288,314));label(259,320,'CC = '+values['CC']+'F',7)
    wire((430,240),(480,240));dot(430,240);label(442,253,'OUT',10)
    wire((475,240),(475,155));wire((465,155),(485,155));wire((465,149),(485,149));wire((475,149),(475,60));dot(475,240)
    label(443,131,'CL = '+values['CLOAD']+'F',7)
    # White breaks at crossings distinguish crossing wires from junction dots.
    for x,y in [(150,380),(305,305),(305,280),(340,305),(340,280)]:
        d.add(Line(x,y-3,x,y+3,strokeColor=colors.white,strokeWidth=3))
        wire((x-3,y),(x+3,y))
    for x in (45,200,340,430,475):dot(x,60)
    dot(45,415)
    label(12,24,'Filled dots = junctions; crossings with gaps are NOT connected.',8)
    label(12,10,'Bodies: all NMOS -> GND; all PMOS -> VDD. Inputs are referenced to GND.',8)
    return d


def generate(results, language='en'):
    """Render English/Chinese evidence, including DC-only early termination."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import ParagraphStyle
    def tr(en,zh):return zh if language=='zh' else en
    def read(name):return json.loads((results/name).read_text())
    s=read('summary.json');target=read('target.json');history=read('history.json');m=read('measurements.json')
    net=(results/'candidate.spice').read_text();reference=(results/'reference.spice').read_text()
    if not (results/'current.log').read_text() or m['simulation_number']!=s['final_simulation_number']:
        raise ValueError('Missing or inconsistent final evidence')
    pdfmetrics.registerFont(TTFont('ReportLatin','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('ReportCJK','/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
    latin=pdfmetrics.getFont('ReportLatin').face.charToGlyph
    def markup(value):
        runs=[]
        for char in str(value):
            font='ReportLatin' if ord(char) in latin else 'ReportCJK'
            if runs and runs[-1][0]==font:runs[-1]=(font,runs[-1][1]+char)
            else:runs.append((font,char))
        return ''.join(f'<font name="{font}">{escape(chars)}</font>' for font,chars in runs)
    body=ParagraphStyle('body',fontName='ReportLatin',fontSize=9,leading=14,spaceAfter=7,wordWrap='CJK')
    title=ParagraphStyle('title',parent=body,fontSize=18,leading=26,spaceAfter=12)
    heading=ParagraphStyle('heading',parent=body,fontSize=12,leading=18,spaceBefore=9)
    small=ParagraphStyle('small',parent=body,fontSize=7.5,leading=11)
    code=ParagraphStyle('code',fontName='Courier',fontSize=7,leading=9)
    story=[]
    def p(value,style=body):story.append(Paragraph(markup(value),style))
    def table(rows,widths):
        t=Table([[Paragraph(markup(v),small) for v in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf5')),('GRID',(0,0),(-1,-1),.3,colors.grey),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.append(t)
    missing=tr('Not simulated / unavailable','未仿真／无有效结果')
    def fmt(v):return missing if v is None else f'{v:.7g}' if isinstance(v,float) else str(v)
    p(tr('SKY130 DC-First Op-Amp Sizing','SKY130 两级运放：DC 优先尺寸优化报告'),title)
    statuses={'targets_passed':'全部目标达标','dc_iteration_limit':'达到 DC 修复上限','max_iterations_reached':'达到总迭代上限','interrupted':'运行中断','baseline_only':'仅验证基准'}
    p(tr('Termination: ','结束原因：')+tr(s['status'],statuses.get(s['status'],s['status'])),heading)
    p(tr('Model: ','模型：')+s.get('model','qwen3-8b-local')+tr('; backend: ','；后端：')+s.get('design_backend','local_qwen'))
    if s.get('error'):p(s['error'])
    p(tr('DC must pass for every transistor before AC measurements are allowed. Missing AC values below are not zeros or passing results.','只有全部晶体管通过 DC 检查才允许进行 AC 测量。下列未测量的 AC 指标不是零，也不代表达标。'))
    table([[tr('Metric','指标'),tr('Target','目标'),tr('Final value (SI units)','最终值（国际单位制）'),tr('Result','判定')]]+[[k,str(v),fmt(m['metrics'].get(k)),missing if m['checks'].get(k) is None else tr('PASS','达标') if m['checks'][k] else tr('FAIL','未达标')] for k,v in target['targets'].items()],[110,100,155,115])
    p(tr('Conditions: ','仿真条件：')+json.dumps(target['conditions'])+'; '+target['corner'])
    stats=[['Status / 状态',s['status']],['Workflow completed / 流程完成',s.get('workflow_completed',False)],['Design success rate / 设计成功率','1/1 (100%)' if s['status']=='targets_passed' else '0/1 (0%)'],['All iterations / 总迭代',s['iteration_count']],['DC repair iterations / DC 修复次数',s.get('dc_iteration_count','N/A')],['Performance iterations / 性能优化次数',s.get('performance_iteration_count','N/A')],['ngspice simulations / 仿真调用次数',s['simulation_count']],['Prompt tokens / 输入 token',s['tokens']['prompt_tokens']],['Completion tokens / 输出 token',s['tokens']['completion_tokens']],['Total tokens / 总 token',s['tokens']['total_tokens']],['Usage complete / 统计完整',s['token_usage_complete']],['Time / 总耗时',f"{s['total_optimization_time_seconds']:.3f} s ({s['total_optimization_time_seconds']/60:.2f} min)"]]
    table([[tr('Statistic','统计项'),tr('Value','记录值')]]+[[name.split(' / ')[1 if language=='zh' else 0],value] for name,value in stats],[240,240])
    p(tr('One run is not a statistical benchmark. Each DC-only or full ngspice invocation counts once. Total time excludes model startup and PDF generation. No monetary cost was measured.','成功率只描述本次实验，并非统计基准。一次纯 DC 或完整 ngspice 调用各计一次仿真。总耗时不含模型启动和 PDF 生成；未测量货币成本。'),small)
    story.append(PageBreak());p(tr('Connected circuit topology','整体连线电路拓扑'),title)
    p(tr('The fixed user-provided topology is retained: differential pair, mirror load, tail source, second gain stage and Miller compensation. Matching is enforced by shared parameters and integer mirror ratios, not independent device edits.','保留用户指定的差分对、电流镜负载、尾电流源、第二级与米勒补偿结构。匹配由共享参数和电流镜整数倍率强制实现，不能独立修改匹配管尺寸。'))
    drawing=topology(net)
    if language=='zh':
        captions={'Filled dots = junctions; crossings with gaps are NOT connected.':'实心圆点为连接点；带断口的交叉线不连接。','Bodies: all NMOS -> GND; all PMOS -> VDD. Inputs are referenced to GND.':'所有ＮＭＯＳ体端接地，ＰＭＯＳ体端接电源；输入源以地为参考。'}
        for element in drawing.contents:
            if isinstance(element,String) and element.text in captions:element.text=captions[element.text];element.fontName='ReportCJK'
    story.append(drawing)
    p(tr('Sources and passive components','电源、偏置源和无源器件'),heading)
    story.append(Preformatted('\n'.join(l for l in net.splitlines() if re.match(r'^(?:V\w+|I\w+|C\w+)\s',l)),code))
    story.append(PageBreak());p(tr('DC acceptance and final sizing','DC 检查与最终尺寸'),title)
    dc=m.get('dc_acceptance')
    if dc:
        p(tr('All-device DC gate: ','全部晶体管 DC 检查：')+str(m['dc_passed']))
        p(tr('Criterion: forward drain orientation, nonzero conduction, VGS/VSG above threshold, and VDS/VSD at least model VDSAT. This is the configured strong-inversion saturation acceptance policy.','判据：漏源方向正确、导通电流达到下限、VGS/VSG 达到阈值、VDS/VSD 不小于模型给出的 VDSAT。这是本项目配置的强反型饱和验收规则。'))
        table([[tr('Device','器件'),'|Id| (A)',tr('Overdrive (V)','过驱动 (V)'),tr('Sat. margin (V)','饱和裕量 (V)'),tr('Pass','通过')]]+[[name,fmt(v.get('id_a')),fmt(v.get('overdrive_v')),fmt(v.get('saturation_margin_v')),v['passed']] for name,v in dc['devices'].items()],[95,100,100,110,75])
        p(tr('Failed devices: ','未通过器件：')+', '.join(dc['failed_devices']))
    initial=parameters(reference);final=parameters(net)
    table([[tr('Parameter','参数'),tr('Initial','初始'),tr('Final','最终')]]+[[k,initial[k],final[k]] for k in target['optimization']['allowed_parameters']],[240,120,120])
    p(tr('W/L: micrometers; IBIAS: amperes; CC: farads. M3/M4 have identical W/L. N_TAIL and N_STAGE2_LOAD are dimensionless positive integers.','W/L 单位为微米，IBIAS 为安培，CC 为法拉。M3/M4 的 W/L 完全一致；N_TAIL、N_STAGE2_LOAD 是无量纲正整数。'))
    story.append(PageBreak());p(tr('Iteration history','迭代历史'),title)
    if not history:p(tr('No sizing decision completed.','没有完成尺寸决策。'))
    for row in history:
        p(tr('Iteration ','第 ')+str(row['iteration'])+' / '+row.get('phase','sizing'),heading)
        p(tr('Model reasoning (original text): ','模型分析（保留原文）：')+json.dumps(row['qwen_analysis'],ensure_ascii=False))
        table([[tr('Parameter','参数'),tr('Before','修改前'),tr('After','修改后'),tr('Model reason','模型理由原文')]]+[[v['parameter'],v['old_value'],v['new_value'],v['reason']] for v in row['parameter_changes']],[100,65,65,250])
        p(tr('Result metrics: ','更新后指标：')+json.dumps(row.get('result_measurements'),ensure_ascii=False))
        p(tr('DC passed after update: ','更新后 DC 通过：')+str(row.get('result_dc_passed')))
        if row.get('validation_error'):p(row['validation_error'])
    p(tr('Full final DC diagnostics','完整最终 DC 诊断值'),heading)
    table([[tr('Quantity','物理量／标识符'),tr('Value','实测值')]]+[[k,fmt(v)] for k,v in m['dc_operating_point'].items()],[355,125])
    story.append(PageBreak());p(tr('Complete final candidate netlist','完整最终候选网表'),title)
    for line in net.splitlines():story.append(Preformatted('\n'.join(textwrap.wrap(line,100,replace_whitespace=False,drop_whitespace=False) or ['']),code))
    p(tr('Sources: summary.json, target.json, history.json, calls.json, measurements.json, candidate.spice, reference.spice, current.log and numbered simulation logs.','来源：summary.json、target.json、history.json、calls.json、measurements.json、candidate.spice、reference.spice、current.log 与编号仿真日志。'))
    dest=results/('final_report_zh.pdf' if language=='zh' else 'final_report.pdf')
    def footer(canvas,doc):canvas.setFont('ReportLatin',8);canvas.drawRightString(550,23,str(doc.page))
    SimpleDocTemplate(str(dest),pagesize=(595,842),leftMargin=45,rightMargin=45,topMargin=40,bottomMargin=40,title=tr('SKY130 DC-first sizing','SKY130 DC 优先尺寸优化报告')).build(story,onFirstPage=footer,onLaterPages=footer)
    return dest
