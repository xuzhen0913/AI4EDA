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
    """Net-labeled MOS diagram parsed from actual netlist; identical labels are wired together."""
    logical=re.sub(r'\n\+\s*',' ',netlist)
    devices=[]
    for line in logical.splitlines():
        fields=line.split()
        if fields and fields[0].upper().startswith('XM'):
            devices.append(fields)
    d=Drawing(500,460)
    def label(x,y,text,size=8): d.add(String(x,y,text,fontName='Helvetica',fontSize=size))
    def wire(x,y,X,Y): d.add(Line(x,y,X,Y,strokeWidth=1))
    roles={'XM1':'Differential pair','XM2':'Differential pair','XM3':'Mirror reference',
        'XM4':'Mirror load','XM5':'Tail source','XM6':'Second gain stage',
        'XM7':'Stage 2 load','XMBIAS_N':'NMOS bias','XMBIAS_P':'PMOS bias'}
    for i,f in enumerate(devices):
        x=60+(i%3)*165;y=395-(i//3)*125
        name,drain,gate,source,body,model=f[:6]
        wire(x,y-17,x,y+17);wire(x-7,y-17,x-7,y+17)
        wire(x,y+13,x+12,y+13);wire(x+12,y+13,x+12,y+35)
        wire(x,y-13,x+12,y-13);wire(x+12,y-13,x+12,y-35)
        wire(x-40,y,x-7,y)
        if 'pfet' in model:d.add(Circle(x-11,y,3,fillColor=colors.white))
        label(x-48,y+5,'G: '+gate.upper());label(x+16,y+29,'D: '+drain.upper())
        label(x+16,y-32,'S: '+source.upper());label(x+18,y,'B: '+body.upper())
        label(x-44,y+49,name.replace('XM','M')+' '+('PMOS' if 'pfet' in model else 'NMOS'))
        label(x-44,y-49,roles.get(name.upper(),name),7)
    # Capacitors retain the actual two net labels and parameter expression.
    capacitors=[l.split() for l in logical.splitlines() if re.match(r'^C\w+\s',l,re.I)]
    for i,f in enumerate(capacitors):
        x=60+i*230; y=48
        wire(x-25,y,x-3,y);wire(x+3,y,x+25,y)
        wire(x-3,y-9,x-3,y+9);wire(x+3,y-9,x+3,y+9)
        label(x-42,y-19,f[1].upper());label(x+20,y-19,f[2].upper())
        label(x-42,y+16,f[0]+' '+f[3])
    label(8,9,'Net labels denote electrical connections. D/G/S/B = drain/gate/source/body. 0 = ground.',8)
    return d


def generate(results):
    summary=json.loads((results/'summary.json').read_text())
    target=json.loads((results/'target.json').read_text())
    history=json.loads((results/'history.json').read_text())
    measurement=json.loads((results/'measurements.json').read_text())
    netlist=(results/'candidate.spice').read_text()
    reference=(results/'reference.spice').read_text()
    # Explicitly read and check the full log used for the reported final measurement.
    log=(results/'current.log').read_text()
    if not log or measurement['simulation_number']!=summary['final_simulation_number']:
        raise ValueError('Missing or inconsistent final simulation evidence')
    styles=getSampleStyleSheet(); story=[]
    def p(s,style='BodyText'):story.append(Paragraph(escape(str(s)),styles[style]))
    def table(rows,widths=None):
        t=Table([[Paragraph(escape(str(c)),styles['BodyText']) for c in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf5')),('GRID',(0,0),(-1,-1),0.3,colors.grey),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.append(t)
    p('SKY130 Two-Stage Op-Amp Sizing','Title')
    p('Status: '+summary['status'],'Heading2')
    p('Sizing backend: '+summary.get('design_backend','local_qwen')+'; model: '+summary.get('model','qwen3-8b-local'))
    p('Workflow completed: '+str(summary.get('workflow_completed',False))+'. Completion of the software workflow is distinct from meeting every circuit target.')
    p(summary.get('error') or 'Experiment termination recorded below.')
    if summary['iteration_count']==0:
        p('No optimized design is claimed: Qwen has not completed a sizing decision. Final values below are the unchanged reference baseline.')
    p('Fixed user-supplied topology: differential input and mirror load provide the first stage; M6/M7 provide the second stage, with Miller compensation. This topology was prescribed, not selected by a topology agent. All performance numbers come from real SKY130/ngspice simulations.')
    p('Circuit performance','Heading2')
    table([['Metric','Target','Final result','Pass/Fail']]+[[k,str(bounds),measurement['metrics'].get(k), 'PASS' if measurement['checks'][k] else 'FAIL'] for k,bounds in target['targets'].items()],[110,110,110,75])
    p('Conditions: '+json.dumps(target['conditions'])+'; corner: '+target['corner'])
    p('Numerical simulation validity: '+str(measurement['simulation_valid'])+'. DC bias acceptability is separately reviewed by Qwen; numerical success alone does not establish a sound design.')
    table([['Experiment statistic','Recorded value'],['Optimization iterations',summary['iteration_count']],['ngspice simulations (this run)',summary['simulation_count']],['Total optimization time',f"{summary['total_optimization_time_seconds']:.3f} s ({summary['total_optimization_time_seconds']/60:.2f} min)"],['Prompt tokens',summary['tokens']['prompt_tokens']],['Completion tokens',summary['tokens']['completion_tokens']],['Total tokens',summary['tokens']['total_tokens']],['Token usage complete',summary['token_usage_complete']],['Success rate (one experiment)', '1/1 (100%)' if summary['status']=='targets_passed' else '0/1 (0%); not a statistical benchmark']],[235,170])
    p('Local Qwen inference only. Monetary/electricity costs are not measured. Time starts before baseline simulation and ends on termination or interruption; excludes server startup and PDF rendering. Failed requests without usage are reported as incomplete token accounting.')
    story.append(PageBreak());p('Circuit topology','Heading1');story.append(topology(netlist))
    p('Passive components and sources (actual netlist)','Heading2')
    lines=[l for l in netlist.splitlines() if re.match(r'^(?:V\w+|I\w+|C\w+)\s',l,re.I)]
    story.append(Preformatted('\n'.join(lines),styles['Code']))
    p('Final parameters','Heading2')
    initial=parameters(reference);final=parameters(netlist)
    table([['Parameter','Initial','Final']]+[[k,initial[k],final[k]] for k in target['optimization']['allowed_parameters']],[170,120,115])
    story.append(PageBreak());p('Optimization history','Heading1')
    if not history:p('No Qwen optimization iteration completed. This report contains baseline evidence only.')
    for h in history:
        p(f"Iteration {h['iteration']}; input simulation {h['simulation_number']}",'Heading2')
        p(json.dumps(h['qwen_analysis']))
        p('Changes: '+json.dumps(h['parameter_changes']))
        p('Measurements before decision: '+json.dumps(h['measurements']))
        if h.get('result_measurements'):p('Measurements after change: '+json.dumps(h['result_measurements']))
        if h.get('validation_error'):p('Rejected: '+h['validation_error'])
    p('Final DC operating point','Heading2')
    table([['Quantity','Value']]+list(measurement['dc_operating_point'].items()),[290,115])
    story.append(PageBreak());p('Complete final candidate netlist','Heading1')
    for line in netlist.splitlines():
        story.append(Preformatted('\n'.join(textwrap.wrap(line,95,replace_whitespace=False,drop_whitespace=False) or ['']),styles['Code']))
    p('Evidence: target.json, reference.spice, candidate.spice, measurements.json, history.json, calls.json, summary.json, current.log and numbered logs in this results directory.')
    dest=results/'final_report.pdf'
    SimpleDocTemplate(str(dest),title='SKY130 Qwen sizing experiment',rightMargin=42,leftMargin=42).build(story)
    return dest
