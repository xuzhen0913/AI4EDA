"""Render the beginner guide + exact, reviewed line annotations into PDF and Markdown."""
import hashlib
import json
import re
import runpy
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    PageBreak, KeepTogether, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs/guide'
# Fail rather than silently mismatch explanations if project source changed.
runpy.run_path(str(DOCS/'make_annotations.py'), run_name='__main__')
annotations=json.loads((DOCS/'annotations.json').read_text())
for relative, data in annotations.items():
    if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=data['sha256']:
        raise ValueError('Source changed: '+relative)

pdfmetrics.registerFont(TTFont('Latin','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('Mono','/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'))
pdfmetrics.registerFont(TTFont('CJK','/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
BLUE=colors.HexColor('#164c72')
GRAY=colors.HexColor('#586b7b')
LIGHT=colors.HexColor('#eff4f8')
BODY=ParagraphStyle('Body',fontName='Latin',fontSize=10,leading=16,spaceAfter=8,wordWrap='CJK',rightIndent=10)
H1=ParagraphStyle('H1',parent=BODY,fontSize=18,leading=27,textColor=BLUE,spaceAfter=15,keepWithNext=True)
H2=ParagraphStyle('H2',parent=BODY,fontSize=12.5,leading=20,textColor=BLUE,spaceBefore=10,spaceAfter=9,keepWithNext=True)
COVER=ParagraphStyle('Cover',parent=H1)
COVERSUB=ParagraphStyle('CoverSub',parent=H2)
CODE=ParagraphStyle('Code',fontName='Mono',fontSize=8.1,leading=12,wordWrap='CJK',spaceAfter=0)
SMALL=ParagraphStyle('Small',parent=BODY,fontSize=8.5,leading=13,spaceAfter=5)
TABLE=ParagraphStyle('Table',parent=SMALL,fontSize=8.2,leading=12)
NOTE=ParagraphStyle('Explanation',parent=BODY,fontSize=9.2,leading=14,spaceAfter=6)
ACTNOTE=ParagraphStyle('ActivationExplanation',parent=NOTE,fontSize=9,leading=13.5,spaceAfter=5)


def styled(text, mono=False, spaces=False):
    primary='Mono' if mono else 'Latin'
    known=pdfmetrics.getFont(primary).face.charToGlyph
    runs=[]
    for char in text:
        font=primary if ord(char) in known else 'CJK'
        if runs and runs[-1][0]==font:
            runs[-1]=(font,runs[-1][1]+char)
        else:
            runs.append((font,char))
    return ''.join('<font name="'+font+'">'+escape(value).replace(' ', '&#160;' if spaces else ' ')+'</font>' for font,value in runs)


def para(text, style=BODY):
    return Paragraph(styled(text),style)


def code_lines(code):
    # Each original code line remains a distinct paragraph; visual wrapping is not a source newline.
    return [Paragraph(styled(line or ' ',mono=True,spaces=True),CODE) for line in code.split('\n')]


class GuideDoc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable,Paragraph) and flowable.style.name in ('H1','H2'):
            title=flowable.getPlainText()
            key='section-'+str(self.seq.nextf('section'))
            level=0 if flowable.style.name=='H1' else 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title,key,level=level,closed=level==0)
            self.notify('TOCEntry',(level,styled(title),self.page,key))


def page_footer(canvas,doc):
    canvas.setStrokeColor(colors.HexColor('#c9d7e2'))
    canvas.line(43,39,552,39)
    p=para('本地 Qwen / Multi-Agent 零基础手册 · 原始代码逐行解释',SMALL)
    p.wrap(460,16);p.drawOn(canvas,43,23)
    canvas.setFont('Latin',8)
    canvas.setFillColor(GRAY)
    canvas.drawRightString(552,25,str(doc.page))


def label(d,text,x,y,size=9,center=True):
    # Paragraph gives real font fallback for Chinese, symbols, and Latin in the diagram.
    style=ParagraphStyle('Diagram',parent=SMALL,fontSize=size,leading=size+4,alignment=1 if center else 0)
    p=para(text,style)
    p.wrap(450,50)
    from reportlab.graphics.shapes import Group
    # Draw one font run at a time; labels are deliberately short enough to fit one line.
    chars=[]
    for ch in text:
        f='Latin' if ord(ch) in pdfmetrics.getFont('Latin').face.charToGlyph else 'CJK'
        if chars and chars[-1][0]==f: chars[-1]=(f,chars[-1][1]+ch)
        else: chars.append((f,ch))
    widths=[pdfmetrics.stringWidth(t,f,size) for f,t in chars]
    if center: x-=sum(widths)/2
    for (f,t),w in zip(chars,widths):
        d.add(String(x,y,t,fontName=f,fontSize=size,fillColor=BLUE));x+=w


def workflow_diagram():
    d=Drawing(509,398)
    rows=[
      ('终端：source scripts/activate.sh','scripts/env.sh → .venv/bin/activate'),
      ('终端：bash scripts/start.sh','scripts/service.py start → vLLM api_server.py'),
      ('后台模型服务：读取 models/Qwen3-8B/','PyTorch / CUDA / GPU 0 → 127.0.0.1:8000'),
      ('终端：bash scripts/run_demo.sh','analog_agents/run.py → config/settings.json / prompts/'),
      ('顺序角色：architecture → sizing → simulation','Agent.run → LocalClient.ask → 本地 API → GPU'),
      ('Python 工具：simulation.py / MockSimulation','网表 + 合成指标 → optimization → 更新参数 → 再评估'),
      ('正常结束：outputs/时间戳/summary.json','实验进程结束；后台模型仍运行'),
      ('终端：bash scripts/stop.sh','scripts/service.py stop → 结束后台进程 → 释放显存')]
    for index,(a,b) in enumerate(rows):
        y=352-index*48
        d.add(Rect(5,y,499,39,rx=5,ry=5,fillColor=LIGHT,strokeColor=colors.HexColor('#9eb9cc')))
        label(d,a,254,y+24,9)
        label(d,b,254,y+9,8)
        if index<7:
            d.add(Line(254,y,254,y-9,strokeColor=BLUE))
            d.add(Polygon([251,y-5,254,y-9,257,y-5],fillColor=BLUE,strokeColor=BLUE))
    return d


def table(rows):
    width=[125,220,164] if len(rows[0])==3 else [509/len(rows[0])]*len(rows[0])
    cells=[[para(cell.strip(),TABLE) for cell in row] for row in rows]
    result=Table(cells,colWidths=width,repeatRows=1,hAlign='LEFT')
    result.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dceaf4')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f8fa')]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#c4d2de')),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    return result


story=[]
text=(DOCS/'chapters.md').read_text()
lines=text.splitlines()
# Cover is separate from body contents to keep the table of contents stable.
story.append(para('本地 Qwen 与 Multi-Agent',COVER))
story.append(para('从零开始：运行、追踪、逐行读代码与修改',COVERSUB))
story.append(Spacer(1,28))
story.append(para('项目：/home/xu'))
story.append(para('版本：详细教学版 · 2026-10-02（日本时间）'))
story.append(para(f'覆盖 {len(annotations)} 个文件、{sum(len(v["lines"]) for v in annotations.values())} 行原始代码/配置/提示词，每行有解释。'))
story.append(para('先读第 1 章即可运行；第 5 章按真实文件追踪全过程；第 8—9 章给出代码替换与模型更新示例；附录按文件逐行查阅。'))
story.append(para('GPU 模型推理已经验证；电路结果是 Mock 合成数据，不是 SPICE。此次编写手册没有替换模型或执行 GPU 实验。'))
story.append(Spacer(1,22))
story.append(para('可编辑来源：docs/guide/chapters.md 与 docs/guide/make_annotations.py。完整可复制文字与代码：docs/USER_GUIDE.md。'))
story.append(PageBreak())
story.append(para('目录',COVER))
toc=TableOfContents()
toc.levelStyles=[ParagraphStyle('TOC0',parent=SMALL,fontSize=10,leading=17,leftIndent=0,firstLineIndent=0,spaceBefore=5),
                 ParagraphStyle('TOC1',parent=SMALL,fontSize=8.6,leading=14,leftIndent=14,firstLineIndent=0)]
story.append(toc)
story.append(PageBreak())
i=0
while i<len(lines):
    line=lines[i]
    if not line.strip(): i+=1;continue
    if line.startswith('```'):
        i+=1;block=[]
        while i<len(lines) and not lines[i].startswith('```'):
            block.append(lines[i]);i+=1
        story.append(KeepTogether(code_lines('\n'.join(block))))
        story.append(Spacer(1,10));i+=1;continue
    if line.startswith('|'):
        rows=[]
        while i<len(lines) and lines[i].startswith('|'):
            values=lines[i].strip('|').split('|')
            if not all(re.fullmatch(r'\s*:?-+:?\s*',v) for v in values):rows.append(values)
            i+=1
        story.append(table(rows));story.append(Spacer(1,10));continue
    if line.startswith('# '):
        if i>0:story.append(PageBreak())
        story.append(para(line[2:],H1))
        if line.startswith('# 5.'):
            story.append(workflow_diagram())
            story.append(para('箭头表示主要控制/数据交接；后台模型服务持续运行，客户端每次请求通过 API 往返。',SMALL))
    elif line.startswith('## '):
        story.append(para(line[3:],H2))
    else:
        story.append(para(line))
    i+=1

md=[text,'\n# 附录 A：当前源文件逐行解释\n']
story.append(PageBreak());story.append(para('附录 A：当前源文件逐行解释',H1))
story.append(para('每行代码均来自本次文件快照。以下解释覆盖 26 个文件共 586 行；空行也保留行号。长行的 PDF 自动折行不改变源文件行号。'))
order=['scripts/activate.sh','scripts/env.sh','scripts/start.sh','scripts/service.py','config/settings.json',
       'scripts/test_qwen.sh','scripts/test_qwen.py','scripts/run_demo.sh',
       'analog_agents/__init__.py','analog_agents/config.py','analog_agents/run.py','analog_agents/agents.py',
       'analog_agents/client.py','prompts/architecture.md','prompts/sizing.md','prompts/simulation.md','prompts/optimization.md',
       'analog_agents/simulation.py','scripts/stop.sh','scripts/download_model.py','scripts/install.sh',
       'scripts/test_agents.py','tests/test_workflow.py','pytest.ini','scripts/audit_paths.py','.venv/bin/activate']
manifest={}
for number,path in enumerate(order,1):
    entry=annotations[path]
    if number>1 and len(entry['lines'])>6:
        story.append(PageBreak())
    else:
        story.append(Spacer(1,14))
    title=f'A{number:02d}. {path}'
    story.append(para(title,H2));story.append(para(entry['purpose']))
    md += ['\n## '+title+'\n',entry['purpose']+'\n']
    lang='bash' if path.endswith('.sh') or path=='.venv/bin/activate' else 'json' if path.endswith('.json') else 'python' if path.endswith('.py') else 'text'
    for row in entry['lines']:
        labeltext=f'L{row["line"]:03d}'
        heading=Paragraph(styled(labeltext+'  '+(row['code'] if row['code'] else '[空行]'),mono=True,spaces=True),CODE)
        explanation=para(row['explanation'],ACTNOTE if path=='.venv/bin/activate' else NOTE)
        story.append(KeepTogether([heading,explanation]))
        md += [f'### {labeltext}\n',f'```{lang}\n{row["code"]}\n```\n',row['explanation']+'\n']
    manifest[path]={'sha256':entry['sha256'],'explained_lines':len(entry['lines'])}
story.append(PageBreak());story.append(para('附录 B：校验与文档维护',H1))
end='''这份文档由当前源码与人工编写的逐行解释共同生成。程序会检查所有源代码行都有解释，并与 reviewed_source_hashes.json 中已审核的源码指纹比较。代码变化后会停止生成，避免把旧解释错误套到新代码上。docs/guide/source_manifest.json 保存交付文件的哈希。

若以后修改业务代码，需要先逐行更新 docs/guide/make_annotations.py 对应解释与行号，再用 sha256sum 对应文件 取得新哈希，更新 docs/guide/reviewed_source_hashes.json 的同名条目。不要只更新哈希而不检查解释。普通读者直接阅读当前 PDF 即可，不必执行这一维护操作。

重新生成命令：

```bash
cd /home/xu
source scripts/activate.sh
python scripts/build_guide.py
```

文档源章节在 docs/guide/chapters.md；逐行说明在 docs/guide/make_annotations.py，生成的结构化解释在 annotations.json；排版程序在 scripts/build_guide.py。旧版 PDF 保存在 docs/USER_GUIDE_v1.pdf。

修改示例的检查记录在 docs/guide/example_checks.json：只进行了语法和隔离的局部逻辑验证，没有替换正式代码、下载新模型或启动 GPU。已部署系统的历史运行证据见 logs/verification.json；两者不是同一类验证。

参考：Qwen3-4B 官方模型卡 https://huggingface.co/Qwen/Qwen3-4B ；vLLM 0.8.5 API 说明 https://docs.vllm.ai/en/v0.8.5/serving/openai_compatible_server.html 。具体文件顺序与项目行为以附录中的本地代码为准。
'''
# Render small closing section without duplicating a full markdown parser.
for part in end.split('\n\n'):
    if part.startswith('```'):
        story.extend(code_lines('\n'.join(part.splitlines()[1:-1])))
    elif part.strip():story.append(para(part))
md+=['\n# 附录 B：校验与文档维护\n',end]
(ROOT/'docs/USER_GUIDE.md').write_text('\n'.join(md))
(DOCS/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
doc=GuideDoc(str(ROOT/'USER_GUIDE.pdf'),pagesize=(595,842),leftMargin=43,rightMargin=43,topMargin=45,bottomMargin=52,
    title='本地 Qwen 与 Multi-Agent：零基础完整使用手册',author='Project documentation',allowSplitting=1)
frame=Frame(43,52,509,745,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
doc.addPageTemplates(PageTemplate(id='normal',frames=[frame],onPage=page_footer))
doc.multiBuild(story)
print(ROOT/'USER_GUIDE.pdf')
