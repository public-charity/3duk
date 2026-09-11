"""Typeset the review report; figures use landscape A3 pages for legibility."""
import html
import re
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4,A3,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Spacer,PageBreak,NextPageTemplate,Table,TableStyle,Image,KeepTogether

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
DEST=ROOT/'output/pdf/manston_museum_approval_plan.pdf'
DEST.parent.mkdir(parents=True,exist_ok=True)
for name,file in [('Arial','arial.ttf'),('Arial-Bold','arialbd.ttf'),('Arial-Italic','ariali.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'C:/Windows/Fonts/'+file))
pdfmetrics.registerFontFamily('Arial',normal='Arial',bold='Arial-Bold',italic='Arial-Italic',boldItalic='Arial-Bold')
styles={
 'body':ParagraphStyle('body',fontName='Arial',fontSize=10.3,leading=14.6,spaceAfter=9,textColor=colors.HexColor('#202020')),
 'title':ParagraphStyle('title',fontName='Arial-Bold',fontSize=24,leading=28,spaceAfter=18),
 'h2':ParagraphStyle('h2',fontName='Arial-Bold',fontSize=16,leading=20,spaceAfter=14,keepWithNext=True),
 'cell':ParagraphStyle('cell',fontName='Arial',fontSize=8.4,leading=11),
 'small':ParagraphStyle('small',fontName='Arial',fontSize=8,leading=10.5,spaceAfter=4),
}
text=(HERE/'MANSTON_MUSEUM_PLAN.md').read_text(encoding='utf-8')
definitions={m[1]:m[2] for m in re.finditer(r'^\[\^(\d+)\]: (.+)$',text,re.M)}

def inline(s):
    s=html.escape(s,quote=False)
    s=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',lambda m:f'<link href="{html.escape(m[2],quote=True)}" color="#234f70">{m[1]}</link>',s)
    s=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',s)
    s=re.sub(r'(?:\[\^\d+\])+',lambda m:'<super>'+','.join(f'<link href="#ref{n}">{n}</link>' for n in re.findall(r'\d+',m[0]))+'</super>',s)
    return s

def p(s,style='body'): return Paragraph(inline(s),styles[style])

def page_no(canvas,doc):
    canvas.setFont('Arial',8);canvas.setFillColor(colors.HexColor('#777777'))
    canvas.drawRightString(canvas._pagesize[0]-40,24,str(doc.page))

W,H=A4; LW,LH=landscape(A3)
doc=BaseDocTemplate(str(DEST),pagesize=A4,leftMargin=43,rightMargin=43,topMargin=40,bottomMargin=40,title='Manston museum and explorer plan',author='')
doc.addPageTemplates([
PageTemplate(id='portrait',pagesize=A4,frames=[Frame(43,40,W-86,H-80,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=page_no),
PageTemplate(id='map',pagesize=(LW,LH),frames=[Frame(24,35,LW-48,LH-60,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=page_no)])
story=[]
sections=text.split('<!-- PAGEBREAK -->')
for si,section in enumerate(sections):
    if si:story.append(PageBreak())
    lines=section.strip().splitlines();i=0;figures=[]
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('!['):
            figures.append(re.search(r'\(([^)]+)\)',line)[1]);i+=1;continue
        if line.startswith('# '):story.append(p(line[2:],'title'));i+=1;continue
        if line.startswith('## '):story.append(p(line[3:],'h2'));i+=1;continue
        if line.startswith('[^'):
            m=re.match(r'\[\^(\d+)\]: (.+)',line)
            story.append(Paragraph(f'<a name="ref{m[1]}"/>{m[1]}. '+inline(m[2]),styles['small']));i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                row=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+',c) for c in row): rows.append(row)
                i+=1
            nc=len(rows[0]);ratios={2:[.34,.66],3:[.23,.32,.45],4:[.17,.25,.20,.38]}.get(nc,[1/nc]*nc)
            cells=[[p(('**'+v+'**') if ri==0 else v,'cell') for v in row] for ri,row in enumerate(rows)]
            table=Table(cells,colWidths=[(W-86)*x for x in ratios],repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#777777')),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#dddddd')),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            story.extend([table,Spacer(1,11)]);continue
        para=[line];i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','![','[^')):para.append(lines[i].strip());i+=1
        story.append(p(' '.join(para)))
    # Short numbered footnotes accompany each section, full citations remain in Sources.
    if si<len(sections)-1:
        used=sorted(set(re.findall(r'\[\^(\d+)\]',section)),key=int)
        if used:
            bits=[]
            for n in used:
                d=definitions[n];m=re.search(r'\[([^\]]+)\]\((https?://[^)]+)\)',d)
                if m:bits.append(f'{n}. [{m[1]}]({m[2]})')
            story.append(Spacer(1,5));story.append(p('Sources: '+'; '.join(bits),'small'))
    for figure in figures:
        story.extend([NextPageTemplate('map'),PageBreak()])
        from PIL import Image as PILImage
        with PILImage.open(HERE/figure) as im:iw,ih=im.size
        scale=min((LW-48)/iw,(LH-60)/ih)
        story.append(Image(str(HERE/figure),width=iw*scale,height=ih*scale))
        story.append(NextPageTemplate('portrait'))
doc.build(story)
print(DEST)
