"""Deterministic reporting agent: renders measured records, never invents results."""
import json
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Line, Circle, String, Rect


def summarize(cfg, context, history, calls, status, error, updates, attempts, sim_seconds, elapsed):
    final = history[-1] if history else None
    design_ok = bool(final and final['simulation']['all_targets_met_synthetically'])
    usages = [c['usage'] for c in calls if c.get('usage') is not None]
    tokens = {k: sum(u[k] for u in usages) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    return {
        'status': status, 'error': error, 'llm_backend': 'local_qwen', 'simulation_backend': 'mock',
        'real_circuit_validated': False, 'config': cfg, 'architecture': context.get('architecture'),
        'evaluations': len(history), 'final': final, 'history': history, 'calls': calls,
        'success_rate': {
            'definition': 'Single-run final design meets every MOCK target and workflow completes; not a statistical benchmark.',
            'successful_design_runs': int(status == 'completed' and design_ok), 'design_runs': 1,
            'design_success_percent': 100.0 if status == 'completed' and design_ok else 0.0,
            'successful_api_calls': sum(c['status'] == 'passed' for c in calls), 'api_calls': len(calls),
            'passing_mock_evaluations': sum(h['simulation']['all_targets_met_synthetically'] for h in history)},
        'number_of_simulations': {'real_spice': 0, 'mock_attempted': attempts, 'mock_completed': len(history)},
        'number_of_iterations': updates,
        'token_cost': {**tokens, 'usage_complete': len(usages) == len(calls),
                       'calls_with_usage': len(usages), 'calls_without_usage': len(calls)-len(usages),
                       'currency_cost': None, 'currency_note': 'Local inference; no cloud API billing. Hardware/electricity cost not measured.'},
        'time_cost': {'workflow_seconds': round(elapsed,4),
                      'api_seconds': round(sum(c['seconds'] for c in calls),4),
                      'simulation_seconds': round(sim_seconds,4),
                      'scope': 'From run.main entry through computation; excludes model startup, PDF rendering and shutdown.'},
        'report_generator': 'Deterministic Python ReportingAgent; no LLM calls',
    }


def topology():
    """MOS-level conceptual topology corresponding to simulation.netlist, bodies labelled."""
    d=Drawing(505,310)
    ink=colors.HexColor('#204a66')
    def wire(x,y,X,Y): d.add(Line(x,y,X,Y,strokeColor=ink,strokeWidth=1.2))
    def txt(x,y,t,size=8): d.add(String(x,y,t,fontName='ReportLatin',fontSize=size,fillColor=ink))
    def dot(x,y): d.add(Circle(x,y,2,fillColor=ink,strokeColor=ink))
    def mos(x,y,name,kind):
        wire(x,y-20,x,y-12);wire(x,y+12,x,y+20)
        wire(x,y-12,x+7,y-12);wire(x,y+12,x+7,y+12);wire(x+7,y-12,x+7,y+12)
        wire(x-7,y-15,x-7,y+15);wire(x-28,y,x-7,y)
        if kind=='PMOS':d.add(Circle(x-11,y,3,fillColor=colors.white,strokeColor=ink))
        txt(x+13,y+4,name,9);txt(x+13,y-8,kind,7)
    def cap(x,y):
        wire(x-14,y,x-3,y);wire(x+3,y,x+14,y);wire(x-3,y-9,x-3,y+9);wire(x+3,y-9,x+3,y+9)
    def current(x,y,name):
        d.add(Circle(x,y,12,strokeColor=ink,fillColor=colors.white));wire(x,y+7,x,y-7)
        wire(x,y-7,x-3,y-3);wire(x,y-7,x+3,y-3);txt(x+17,y-3,name)
    wire(45,285,475,285);txt(48,294,'VDD');wire(45,20,475,20);txt(48,7,'0 / GND')
    for x in (110,235,385):mos(x,235,'M3' if x==110 else 'M4' if x==235 else 'M5','PMOS');wire(x,255,x,285);dot(x,285)
    for x,n in ((110,'M1'),(235,'M2')):mos(x,135,n,'NMOS');wire(x,155,x,215)
    txt(111,184,'n1');txt(237,184,'n2');dot(110,180);dot(235,180)
    wire(110,180,65,180);wire(65,180,65,260);wire(65,260,207,260)
    wire(82,235,82,260);dot(82,260);wire(207,260,207,235)
    # Crossing the M3 source wire at y260 has no junction dot: different nets.
    txt(46,266,'mirror gate = n1',7)
    wire(55,135,82,135);txt(47,146,'IN+');wire(180,135,207,135);txt(170,146,'IN-')
    wire(110,115,110,94);wire(235,115,235,94);wire(110,94,235,94);dot(173,94);txt(120,81,'tail')
    wire(173,94,173,68);current(173,56,'ITAIL');wire(173,44,173,20)
    wire(235,180,312,180);dot(275,180);wire(312,180,312,235);wire(312,235,357,235)
    wire(385,215,385,115);wire(385,115,470,115);dot(385,115);txt(410,125,'OUT')
    wire(385,115,385,68);current(385,56,'IBIAS');wire(385,44,385,20)
    wire(275,180,275,90);wire(275,90,316,90);cap(330,90);wire(344,90,385,90);dot(385,90);txt(320,104,'Cc')
    wire(465,115,465,82);wire(454,82,476,82);wire(454,76,476,76);wire(465,76,465,20);dot(465,115);txt(477,78,'CL')
    txt(18,42,'NMOS bodies: 0',7);txt(18,31,'PMOS bodies: VDD',7)
    return d


class ReportingAgent:
    def run(self, summary, output_dir):
        out=Path(output_dir)
        pdfmetrics.registerFont(TTFont('ReportLatin','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('ReportCJK','/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
        known=pdfmetrics.getFont('ReportLatin').face.charToGlyph
        def markup(text):
            runs=[]
            for ch in str(text):
                font='ReportLatin' if ord(ch) in known else 'ReportCJK'
                if runs and runs[-1][0]==font:runs[-1]=(font,runs[-1][1]+ch)
                else:runs.append((font,ch))
            return ''.join(f'<font name="{f}">{escape(t)}</font>' for f,t in runs)
        body=ParagraphStyle('body',fontName='ReportLatin',fontSize=9.5,leading=15,spaceAfter=8,wordWrap='CJK',rightIndent=8)
        title=ParagraphStyle('title',parent=body,fontSize=18,leading=25,textColor=colors.HexColor('#204a66'),spaceAfter=14)
        sub=ParagraphStyle('sub',parent=body,fontSize=12,leading=18,spaceBefore=8)
        small=ParagraphStyle('small',parent=body,fontSize=8,leading=12)
        story=[]
        def p(t,style=body):story.append(Paragraph(markup(t),style))
        def table(rows,widths):
            t=Table([[Paragraph(markup(c),small) for c in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4eef5')),('GRID',(0,0),(-1,-1),0.3,colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            story.extend([t,Spacer(1,10)])
        cfg=summary['config'];rate=summary['success_rate'];tok=summary['token_cost'];tim=summary['time_cost']
        p('模拟电路 Multi-Agent 实验报告',title)
        p(f'实验编号：{out.name}  |  模型：{cfg["model_repo"]}  |  GPU：{cfg["gpu"]}')
        p('MOCK / 未进行真实电路仿真。拓扑与尺寸仅为概念方案；没有工艺 PDK，不能据此认定真实电路性能。')
        p('电路拓扑结构图',sub)
        if summary['final']:
            story.append(topology())
            p('图对应最终一轮概念网表：M1/M2 为 NMOS 差分对，M3/M4 为 PMOS 电流镜负载，M5 为 PMOS 共源第二级，Cc 为 Miller 补偿。ITAIL 与 IBIAS 为理想电流源。实心圆表示连接，交叉无圆点表示不连接。',small)
        else:p('本次运行尚未生成有效尺寸/网表，不能给出本次已生成的电路图。')
        p('选择该拓扑的原因',sub)
        p('概念设计动机：差分输入级便于处理两路输入之差，电流镜作为有源负载，第二级提供进一步放大，Miller 电容用于补偿。结构适合演示尺寸—评估—优化流程；这不证明当前尺寸已满足指标。',small)
        p('当前任务预先限定为两级 CMOS 运放，系统未开展不同拓扑之间的实验比较。以下是 Architecture Agent 的理由，属于模型建议，不是经真实仿真验证的结论。')
        architecture=summary.get('architecture') or {}
        p(architecture.get('rationale','架构角色未返回结果。'))
        for a in architecture.get('assumptions',[]):p('假设：'+a,small)
        story.append(PageBreak())
        p('Success rate 与 Circuit performances',title)
        p(f"设计成功率（本次单次运行）：{rate['design_success_percent']:.1f}% ({rate['successful_design_runs']}/{rate['design_runs']})。定义：流程完成且最终一次 MOCK 评估的全部目标达成。单次运行不能估计系统总体成功率；真实电路成功率为 N/A。")
        api=f"{100*rate['successful_api_calls']/rate['api_calls']:.1f}%" if rate['api_calls'] else 'N/A'
        p(f"API 调用成功率：{api} ({rate['successful_api_calls']}/{rate['api_calls']})，成功要求响应完成且 JSON 校验通过。各轮 MOCK 评估全目标通过次数：{rate['passing_mock_evaluations']}/{summary['evaluations']}。各轮相互关联，不是独立实验样本。")
        p(f"流程状态：{summary['status']}；错误：{summary.get('error') or '无'}")
        final=summary['final']
        if final:
            spec=cfg['specification'];metrics=final['simulation']['metrics'];checks=final['simulation']['checks']
            table([['指标（均为 MOCK）','目标','最终结果','达标']]+[
                [label,f'{op} {spec[target]} {unit}',f'{metrics[key]} {unit}','是' if checks[key] else '否']
                for key,label,target,op,unit in [('gain_db','直流增益','gain_db_min','≥','dB'),('ugb_mhz','单位增益带宽','ugb_mhz_min','≥','MHz'),('phase_margin_deg','相位裕度','phase_margin_deg_min','≥','°'),('power_mw','功耗','power_mw_max','≤','mW')]], [150,120,145,80])
            p('最终参数（对应图与最终一轮网表）',sub)
            table([['字段','数值']]+[[k,str(v)] for k,v in final['parameters'].items()],[300,195])
        p('Number of simulations / Number of iterations',sub)
        counts=summary['number_of_simulations']
        p(f"真实 SPICE 仿真次数：{counts['real_spice']}。MOCK 评估：尝试 {counts['mock_attempted']} 次，完成 {counts['mock_completed']} 次。op/ac/tran 仅为计划与网表语句，不分别计为真实仿真。")
        p(f"参数更新迭代次数：{summary['number_of_iterations']}。初始评估不计入更新次数；即使模型返回相同参数，应用一次建议也计一轮。最大允许更新次数：{cfg['max_iterations']}。")
        story.append(PageBreak())
        p('Token cost / Time cost / 迭代记录',title)
        table([['成本项目','实测值与口径'],['输入 token',tok['prompt_tokens']],['输出 token',tok['completion_tokens']],['合计 token',tok['total_tokens']],['用量完整性',f"{'完整' if tok['usage_complete'] else '不完整，仅为已知下限'}；{tok['calls_without_usage']} 次调用未获得 usage"],['货币费用','N/A：本地推理无云端 API 账单；未测量硬件/电费，不以 0 表示总成本'],['流程耗时',f"{tim['workflow_seconds']:.3f} 秒"],['其中模型 API 等待',f"{tim['api_seconds']:.3f} 秒"],['其中 Mock 工具',f"{tim['simulation_seconds']:.4f} 秒"]],[160,335])
        p('Token 数取自 vLLM 响应 usage，包含角色指令、任务资料、Schema 与模型输出。关闭 SDK 自动重试以明确记录每次请求；失败响应若无 usage，则总量只代表已知下限。报告生成不调用任何语言模型，额外报告 token 为 0；本次开发会话的 Codex token 不在实验计量范围。',small)
        p('Time cost 从 run.main 开始计到计算结束，包含配置、模型请求、工具计算及过程 JSON 写入；不含模型服务冷启动、最终报告写盘/PDF 排版与停止服务。API 与工具耗时是流程时间的组成部分，不应再次相加。',small)
        table([['轮次','增益 dB','带宽 MHz','相位裕度 °','功耗 mW','全达标']]+[[h['iteration'],*[h['simulation']['metrics'][k] for k in ('gain_db','ugb_mhz','phase_margin_deg','power_mw')],'是' if h['simulation']['all_targets_met_synthetically'] else '否'] for h in summary['history']],[50,90,95,100,90,70])
        table([['角色','输入 token','输出 token','秒','状态']]+[[c['agent'],(c.get('usage') or {}).get('prompt_tokens','未知'),(c.get('usage') or {}).get('completion_tokens','未知'),c['seconds'],c['status']] for c in summary['calls']],[130,100,100,85,80])
        p('溯源：同目录 config.json、architecture.json、sizing.json、history.json、calls.json、summary.json；iteration-N/conceptual_not_executed.cir 为各轮网表。PDF 指标由记录确定性排版，不由语言模型编写或猜测。',small)
        def footer(canvas,doc):
            canvas.setFont('ReportLatin',8);canvas.drawString(45,24,'MOCK circuit results | Local Qwen | '+out.name);canvas.drawRightString(550,24,str(doc.page))
        target=out/'REPORT.pdf'
        SimpleDocTemplate(str(target),pagesize=(595,842),leftMargin=45,rightMargin=45,topMargin=40,bottomMargin=45,title='Analog Multi-Agent Experiment Report').build(story,onFirstPage=footer,onLaterPages=footer)
        return target
