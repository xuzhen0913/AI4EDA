"""Render the recorded five-iteration experiment in Chinese without rerunning it."""
import json
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Preformatted
from reportlab.graphics.shapes import String
from simulator.report_generator import topology
from agents.sizing_agent.agent import parameters


def generate(results):
    def read(name):return json.loads((results/name).read_text())
    s=read('summary.json');t=read('target.json');h=read('history.json');m=read('measurements.json');calls=read('calls.json')
    net=(results/'candidate.spice').read_text();ref=(results/'reference.spice').read_text()
    assert m['simulation_number']==s['final_simulation_number']
    assert (results/'current.log').read_text()
    for row in h:
        assert (results/'logs'/f"simulation_{row['simulation_number']:03d}.log").read_text()
    pdfmetrics.registerFont(TTFont('Zh','/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
    pdfmetrics.registerFont(TTFont('Latin','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    latin=pdfmetrics.getFont('Latin').face.charToGlyph
    def markup(value):
        runs=[]
        for char in str(value):
            font='Latin' if ord(char) in latin else 'Zh'
            if runs and runs[-1][0]==font:runs[-1]=(font,runs[-1][1]+char)
            else:runs.append((font,char))
        return ''.join(f'<font name="{font}">{escape(chars)}</font>' for font,chars in runs)
    body=ParagraphStyle('body',fontName='Latin',fontSize=9.5,leading=15,wordWrap='CJK',spaceAfter=7)
    title=ParagraphStyle('title',parent=body,fontSize=19,leading=27,spaceAfter=14)
    head=ParagraphStyle('head',parent=body,fontSize=13,leading=20,spaceBefore=10,spaceAfter=9)
    small=ParagraphStyle('small',parent=body,fontSize=8,leading=12)
    code=ParagraphStyle('code',fontName='Courier',fontSize=7,leading=9)
    story=[]
    def p(text,style=body):story.append(Paragraph(markup(text),style))
    def table(rows,widths):
        table=Table([[Paragraph(markup(v),small) for v in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf5')),('GRID',(0,0),(-1,-1),.3,colors.grey),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.append(table)
    metric=[('dc_gain_db','直流／低频增益','dB',1),('ugb_hz','单位增益带宽','MHz',1e-6),('phase_margin_deg','相位裕度','°',1),('power_w','功耗','mW',1e3)]
    p('SKY130 两级运算放大器\n尺寸优化实验报告（中文版）',title)
    p('实验结论：流程已跑通，电路未达到全部目标。',head)
    status={'max_iterations_reached':'达到最大迭代次数','targets_passed':'目标全部达成','interrupted':'运行中断','baseline_only':'仅基准仿真'}
    p('结束原因：'+status.get(s['status'],s['status'])+'。模型：'+s['model']+'；实际后端：本地 Qwen。未使用 Astra 代跑。')
    p('本报告复用已记录的真实 SKY130/ngspice 仿真结果，仅将说明整理为中文；未重新调用模型或运行仿真。网表标识符和原始 SPICE 内容保持不变。')
    p('电路性能',head)
    rows=[['指标','目标','初始值','最终值','结果']]
    for key,name,unit,scale in metric:
        bounds=t['targets'][key];constraint='，'.join(('≥' if op=='min' else '≤')+f'{v*scale:g} {unit}' for op,v in bounds.items())
        rows.append([name,constraint,f"{h[0]['measurements'][key]*scale:.5g}",f"{m['metrics'][key]*scale:.6g} {' '+unit}",'达标' if m['checks'][key] else '未达标'])
    table(rows,[105,95,80,130,70])
    c=t['conditions'];p(f"仿真条件：VDD={c['vdd_v']} V；温度={c['temperature_c']} °C；输入共模={c['input_common_mode_v']} V；负载电容={c['load_capacitance_f']*1e12:g} pF；工艺角={t['corner']}。")
    p('成功率、次数与成本',head)
    table([['项目','记录结果'],['软件流程完成','是' if s['workflow_completed'] else '否'],['电路设计成功率','1/1（100%）' if s['status']=='targets_passed' else '0/1（0%）：最终设计未满足全部目标'],['模型调用成功率',f"{sum(x['status']=='passed' for x in calls)}/{len(calls)}"],['优化迭代次数',s['iteration_count']],['真实 ngspice 仿真次数',f"{s['simulation_count']}（基准一次，加五次参数更新后的仿真）"],['输入 token',s['tokens']['prompt_tokens']],['输出 token',s['tokens']['completion_tokens']],['总 token',s['tokens']['total_tokens']],['token 统计来源','本地服务返回的 usage；统计完整' if s['token_usage_complete'] else '统计不完整'],['总优化时间',f"{s['total_optimization_time_seconds']:.3f} 秒（约 {s['total_optimization_time_seconds']/60:.2f} 分钟）"],['货币与电费成本','未测量，不虚构金额']],[160,320])
    p('成功率仅描述本次单个实验，不代表统计基准。时间从基准仿真开始前计时，到迭代结束停止；不包含模型启动及报告排版。中文版生成未增加推理 token。',small)
    story.append(PageBreak());p('电路拓扑与采用原因',title)
    p('采用用户指定的固定两级拓扑：M1/M2 为差分输入对，M3/M4 为电流镜有源负载；M5 提供尾电流，M6/M7 构成第二级，CCOMP 提供米勒补偿。本实验只调整尺寸和允许的偏置参数，没有进行拓扑搜索或比较。')
    drawing=topology(net)
    translations={'Differential pair':'差分输入对','Mirror reference':'电流镜参考管','Mirror load':'电流镜负载','Tail source':'尾电流源','Second gain stage':'第二级增益管','Stage 2 load':'第二级负载','NMOS bias':'偏置参考管','PMOS bias':'偏置参考管','Net labels denote electrical connections. D/G/S/B = drain/gate/source/body. 0 = ground.':'同名网络标签表示电气连接，零号节点表示地。'}
    for item in drawing.contents:
        if isinstance(item,String) and item.text in translations:
            item.text=translations[item.text];item.fontName='Zh'
    story.append(drawing)
    p('图中 D/G/S/B 分别表示漏极、栅极、源极和体端；VINP/VINN 为差分输入，VDD 为电源，OUT 为输出。CCOMP 连接 N2 与 OUT，CLOAD_OUT 连接 OUT 与地。图由最终网表连接关系生成。',small)
    p('电源、偏置源和电容的实际连接',head)
    story.append(Preformatted('\n'.join(l for l in net.splitlines() if __import__('re').match(r'^(?:V\w+|I\w+|C\w+)\s',l)),code))
    story.append(PageBreak());p('迭代过程与参数变化',title)
    table([['状态','增益 dB','UGB MHz','相位裕度 °','功耗 mW']]+[[label]+[f'{v[k]*scale:.6g}' for k,_,_,scale in metric] for label,v in [('基准',h[0]['measurements'])]+[(f"第 {row['iteration']} 轮后",row['result_measurements']) for row in h]],[80,95,95,105,105])
    p('以下为 Qwen 记录的决策摘要译文，代表模型当时的判断，不是已经验证正确的电路设计结论。模型每轮都认为仿真和直流工作点有效，并把增益不足归因于第一级跨导及第二级输出电阻不足。其调整方向连续重复，后续实测增益反而下降。')
    reasons={'W_IN':'模型认为增大差分输入对的宽长比能提高跨导，从而提高第一级增益。','W_STAGE2_LOAD':'模型认为增大 PMOS 负载宽长比能提高输出电阻，从而提高第二级增益；此说法并非普遍成立。','IBIAS':'模型认为增大偏置电流能提高第一级跨导，从而提高增益。'}
    for row in h:
        p(f"第 {row['iteration']} 轮：读取仿真 {row['simulation_number']}，更新后仿真 {row['result_simulation_number']}",head)
        p(f"模型读取的增益为 {row['measurements']['dc_gain_db']} dB，低于目标 {t['targets']['dc_gain_db']['min']} dB。模型报告未见错误或警告，并判断工作点有效。")
        table([['参数','修改前','修改后','模型理由（摘要）']]+[[x['parameter'],x['old_value'],x['new_value'],reasons.get(x['parameter'],x['reason'])] for x in row['parameter_changes']],[100,60,60,260])
        p(f"本轮 token：{row['qwen_token_usage']['total_tokens']}；迭代耗时：{row['iteration_time']:.3f} 秒。",small)
    story.append(PageBreak());p('最终参数与直流工作点',title)
    initial=parameters(ref);final=parameters(net)
    table([['参数','初始值','最终值']]+[[k,initial[k],final[k]] for k in t['optimization']['allowed_parameters']],[220,130,130])
    p('W/L 数值单位为微米；IBIAS 中 u 表示微安，CC 中 p 表示皮法。匹配对仍共享相同参数，供电、输入共模、电容负载和工艺角未被修改。')
    op=m['dc_operating_point']
    table([['直流量','最终实测值']]+[[k,f'{v:.9g}'] for k,v in op.items() if not k.startswith('@')],[280,200])
    p('结果解读',head)
    p(f"最终输出静态电压为 {op['v(out)']:.6f} V，接近 {c['vdd_v']} V 的高电源轨。基准输出约为 0.078059 V，接近低电源轨。数值仿真完成不意味着偏置正确；本次模型未有效解决偏置和增益问题。第 5 次更新后的最终结果已经仿真，但由于达到迭代上限，没有第 6 次模型复核。")
    p('完整器件工作点',head)
    table([['器件内部量（原始标识符）','实测值']]+[[k,f'{v:.9g}'] for k,v in op.items() if k.startswith('@')],[355,125])
    story.append(PageBreak());p('附录：完整最终网表',title)
    p('以下保留原始 SPICE 语法与注释，便于复现。最终参数未达到全部设计目标。')
    for line in net.splitlines():story.append(Preformatted('\n'.join(textwrap.wrap(line,100,replace_whitespace=False,drop_whitespace=False) or ['']),code))
    p('数据来源：同目录的 summary.json、target.json、history.json、calls.json、measurements.json、reference.spice、candidate.spice、current.log，以及 logs 中编号为 005 至 010 的完整仿真记录。')
    def footer(canvas,doc):
        canvas.setFont('Latin',8);canvas.drawRightString(550,25,str(doc.page))
    dest=results/'final_report_zh.pdf'
    SimpleDocTemplate(str(dest),pagesize=(595,842),leftMargin=45,rightMargin=45,topMargin=40,bottomMargin=40,title='SKY130 两级运放尺寸优化实验报告（中文版）').build(story,onFirstPage=footer,onLaterPages=footer)
    return dest

if __name__=='__main__':
    print(generate(Path(__file__).resolve().parents[1]/'circuits/two_stage_opamp/results'))
