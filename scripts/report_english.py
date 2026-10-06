"""Render an English PDF from a completed run; no model or simulation calls."""
import argparse
import json
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from analog_agents.config import project_path
from analog_agents.reporting import topology


def render(run_dir):
    out=project_path(run_dir)
    s=json.loads((out/'summary.json').read_text())
    cfg=s['config'];rate=s['success_rate'];tok=s['token_cost'];tim=s['time_cost'];final=s['final']
    pdfmetrics.registerFont(TTFont('ReportLatin','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    body=ParagraphStyle('body',fontName='ReportLatin',fontSize=9,leading=13,spaceAfter=7)
    title=ParagraphStyle('title',parent=body,fontSize=17,leading=23,textColor=colors.HexColor('#204a66'),spaceAfter=12)
    sub=ParagraphStyle('sub',parent=body,fontSize=11,leading=16,spaceBefore=7)
    small=ParagraphStyle('small',parent=body,fontSize=8,leading=11)
    story=[]
    def paragraph(t,style=body):return Paragraph(escape(str(t)),style)
    def p(t,style=body):story.append(paragraph(t,style))
    def table(rows,widths):
        t=Table([[paragraph(c,small) for c in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4eef5')),('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story.extend([t,Spacer(1,9)])
    p('Analog Circuit Multi-Agent Report',title)
    p(f'Run: {out.name} | Model: {cfg["model_repo"]} | GPU: {cfg["gpu"]}')
    p('MOCK RESULTS ONLY. No real SPICE simulation or foundry PDK was used. The topology and dimensions are conceptual; the reported metrics do not validate a physical circuit.')
    p('Circuit topology',sub)
    if final:
        story.append(topology())
        p('M1/M2: NMOS differential pair. M3/M4: PMOS current-mirror active load. M5: PMOS common-source second stage. Cc: Miller compensation. ITAIL/IBIAS: ideal current sources. Dots indicate junctions; crossings without dots are not connected. The diagram corresponds to the final conceptual netlist.',small)
    else:p('No valid circuit parameters or netlist were produced in this run.')
    p('Why this topology was selected',sub)
    p('The task fixes the architecture to a two-stage CMOS op-amp; alternative topologies were not benchmarked. A differential input, active load, second gain stage and Miller capacitor provide a simple structure for demonstrating the sizing–evaluation–optimization workflow.',small)
    a=s.get('architecture') or {}
    rationale=a.get('rationale','No architecture response was recorded.')
    # Preserve the actual English model response; never silently omit untranslated text.
    if any('\u4e00'<=c<='\u9fff' for c in rationale+' '.join(a.get('assumptions',[]))):
        raise ValueError('Architecture text needs an explicit English translation before rendering.')
    p('Architecture Agent rationale (unverified model output): '+rationale,small)
    p('Any claim above that all targets are met is not supported by this run: the final MOCK gain is below the target. Use the measured checks on the next page.',small)
    for item in a.get('assumptions',[]):p('Assumption: '+item,small)
    story.append(PageBreak())
    p('Success rate and Circuit performances',title)
    p(f"Design success rate: {rate['design_success_percent']:.1f}% ({rate['successful_design_runs']}/{rate['design_runs']}). Success requires a completed workflow and all final MOCK targets to pass. This is one run, not a statistical estimate of general reliability. Real-circuit success rate: N/A.")
    api=f"{100*rate['successful_api_calls']/rate['api_calls']:.1f}%" if rate['api_calls'] else 'N/A'
    p(f"API success rate: {api} ({rate['successful_api_calls']}/{rate['api_calls']}); successful calls must complete and pass JSON validation. MOCK evaluations passing all targets: {rate['passing_mock_evaluations']}/{s['evaluations']}. Iterations are correlated, not independent design trials.")
    p(f"Workflow status: {s['status']}. Error: {s.get('error') or 'None'}.")
    if final:
        spec=cfg['specification'];metrics=final['simulation']['metrics'];checks=final['simulation']['checks']
        table([['Performance (MOCK)','Target','Final result','Pass']]+[
            [label,f'{op} {spec[target]} {unit}',f'{metrics[key]} {unit}','Yes' if checks[key] else 'No']
            for key,label,target,op,unit in [('gain_db','DC gain','gain_db_min','≥','dB'),('ugb_mhz','Unity-gain bandwidth','ugb_mhz_min','≥','MHz'),('phase_margin_deg','Phase margin','phase_margin_deg_min','≥','°'),('power_mw','Power','power_mw_max','≤','mW')]], [155,120,145,75])
        p('Final circuit parameters',sub)
        table([['Parameter','Value']]+[[k,str(v)] for k,v in final['parameters'].items()],[300,195])
        p('Units: *_um = micrometers; *_ua = microamperes; *_pf = picofarads. The common channel length is used for all five MOS devices in the template.',small)
    p('Number of simulations / Number of iterations',sub)
    counts=s['number_of_simulations']
    p(f"Real SPICE simulations: {counts['real_spice']}. MOCK evaluations: {counts['mock_attempted']} attempted, {counts['mock_completed']} completed. The op/ac/tran entries are plans and netlist statements, not separately executed simulations.")
    p(f"Parameter-update iterations: {s['number_of_iterations']}. The initial evaluation is excluded. Applying an unchanged proposal still counts as an update iteration. Configured maximum: {cfg['max_iterations']}.")
    story.append(PageBreak())
    p('Token cost / Time cost / Run history',title)
    table([['Cost item','Measured value / definition'],['Input tokens',tok['prompt_tokens']],['Output tokens',tok['completion_tokens']],['Total tokens',tok['total_tokens']],['Usage coverage',f"{'Complete' if tok['usage_complete'] else 'Incomplete; known lower bound only'}; {tok['calls_without_usage']} calls without usage"],['Monetary cost','N/A. Local inference has no cloud API bill. Hardware and electricity costs were not measured.'],['Workflow time',f"{tim['workflow_seconds']:.3f} s"],['API time (included above)',f"{tim['api_seconds']:.3f} s"],['MOCK tool time (included above)',f"{tim['simulation_seconds']:.4f} s"]],[170,325])
    p('Tokens come from vLLM response usage, including role instructions, task data, schemas and generated text. SDK automatic retries are disabled. Failed calls without usage make totals a known lower bound. PDF rendering uses no language model: additional reporting tokens = 0. Codex development-session tokens are outside this experiment.',small)
    p('Workflow time starts at run.main entry and ends after computation. It includes configuration, API calls, tool computation and intermediate JSON writes; it excludes model startup, final summary/PDF writing and shutdown. API and tool times are components of the workflow time, not additional costs.',small)
    table([['Evaluation','Gain (dB)','UGB (MHz)','PM (°)','Power (mW)','All pass']]+[[h['iteration'],*[h['simulation']['metrics'][k] for k in ('gain_db','ugb_mhz','phase_margin_deg','power_mw')],'Yes' if h['simulation']['all_targets_met_synthetically'] else 'No'] for h in s['history']],[75,85,85,75,95,80])
    table([['Agent','Input tokens','Output tokens','Seconds','Status']]+[[c['agent'],(c.get('usage') or {}).get('prompt_tokens','Unknown'),(c.get('usage') or {}).get('completion_tokens','Unknown'),c['seconds'],c['status']] for c in s['calls']],[130,100,100,80,85])
    p('Sources in this run directory: config.json, architecture.json, sizing.json, history.json, calls.json and summary.json. Each iteration-N/conceptual_not_executed.cir contains the corresponding conceptual netlist. This English edition reuses the recorded experiment; no model inference or simulation was repeated.',small)
    def footer(canvas,doc):
        canvas.setFont('ReportLatin',8);canvas.drawString(45,24,'MOCK circuit results | '+out.name+' | English edition');canvas.drawRightString(550,24,str(doc.page))
    target=out/'REPORT_EN.pdf'
    SimpleDocTemplate(str(target),pagesize=(595,842),leftMargin=45,rightMargin=45,topMargin=40,bottomMargin=45,title='Analog Circuit Multi-Agent Report — English').build(story,onFirstPage=footer,onLaterPages=footer)
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir',help='Existing run directory under the project root')
    print(render(parser.parse_args().run_dir))
