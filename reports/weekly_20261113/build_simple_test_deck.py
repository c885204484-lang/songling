from pathlib import Path
import math, shutil, json
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.oxml.xmlchemy import OxmlElement

OUT = Path(__file__).resolve().parent
ASSETS = OUT / 'assets'
ASSETS.mkdir(parents=True, exist_ok=True)
R = Presentation()
R.slide_width, R.slide_height = Inches(13.333333), Inches(7.5)
W='FFFFFF'; INK='172E3C'; MUT='637888'; TEAL='087F83'; MINT='E8F5F2'
NAVY='112F40'; GREY='F1F5F7'; LINE='DCE5EA'; ORANGE='C66A2D'; PALE='FFF1E7'
RED='BA4C51'; PINK='FBECEF'; BLUE='3479B8'; SOFTBLUE='EAF1F9'; GOLD='F1B762'
FONT='Noto Sans CJK SC'

def shape(s,x,y,w,h,fill=W,stroke=None,kind=MSO_SHAPE.RECTANGLE,sw=1):
    q=s.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill: q.fill.solid(); q.fill.fore_color.rgb=RGBColor.from_string(fill)
    else: q.fill.background()
    if stroke: q.line.color.rgb=RGBColor.from_string(stroke); q.line.width=Pt(sw)
    else: q.line.fill.background()
    q._element.spPr.append(OxmlElement('a:effectLst'))
    return q

def txt(s,x,y,w,h,t,size=20,color=INK,bold=False,align=PP_ALIGN.LEFT):
    q=s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf=q.text_frame; tf.word_wrap=True
    tf.margin_left=tf.margin_right=tf.margin_top=tf.margin_bottom=0
    for i,line in enumerate(t.split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph()
        p.alignment=align; p.space_after=Pt(7); p.line_spacing=1.12
        r=p.add_run(); r.text=line
        r.font.name=FONT; r.font.size=Pt(size); r.font.bold=bold; r.font.color.rgb=RGBColor.from_string(color)
        ea=OxmlElement('a:ea'); ea.set('typeface', FONT); r._r.get_or_add_rPr().append(ea)
    return q

def line(s,x1,y1,x2,y2,color=TEAL,width=2,dash=False,arrow=False):
    q=s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Inches(x1),Inches(y1),Inches(x2),Inches(y2))
    q.line.color.rgb=RGBColor.from_string(color); q.line.width=Pt(width)
    if dash:q.line.dash_style=MSO_LINE_DASH_STYLE.DASH
    if arrow:
        a=OxmlElement('a:tailEnd'); a.set('type','triangle'); a.set('w','med'); a.set('len','med')
        q._element.spPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ln').append(a)
    return q

def poly(s,points,color=TEAL,width=3,dash=False):
    # Freeform coordinates are integers: keep 1/1000-inch detail for curves.
    coords=[(round(x*1000),round(y*1000)) for x,y in points]
    b=s.shapes.build_freeform(*coords[0],scale=Inches(1)/1000)
    b.add_line_segments(coords[1:],close=False)
    q=b.convert_to_shape(); q.fill.background(); q.line.color.rgb=RGBColor.from_string(color);q.line.width=Pt(width)
    if dash:q.line.dash_style=MSO_LINE_DASH_STYLE.DASH
    return q

def dot(s,x,y,r=.055,c=TEAL):return shape(s,x-r,y-r,2*r,2*r,c,kind=MSO_SHAPE.OVAL)
def pill(s,x,y,w,t,c=TEAL,bg=MINT):
    shape(s,x,y,w,.36,bg,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    txt(s,x+.1,y+.065,w-.2,.24,t,10.5,c,True)

def base(n,kicker,title,sub='',foot='松灵无人车  ·  周工作汇报  ·  2026.11.09—11.13'):
    s=R.slides.add_slide(R.slide_layouts[6]);s.background.fill.solid();s.background.fill.fore_color.rgb=RGBColor.from_string(W)
    shape(s,.58,.42,.42,.055,TEAL)
    txt(s,1.13,.29,10.8,.35,kicker,10.5,TEAL,True)
    txt(s,.65,.91,12.0,.69,title,29,INK,True)
    if sub:txt(s,.68,1.72,12,.43,sub,14,MUT)
    line(s,.65,6.98,12.68,6.98,LINE,.7)
    txt(s,.68,7.11,11.4,.21,foot,8.2,MUT)
    txt(s,12.1,7.06,.55,.29,f'{n:02}',12,TEAL,True,PP_ALIGN.RIGHT)
    return s

def note(s,t):s.notes_slide.notes_text_frame.text=t
def banner(s,t,y=6.06,bg=MINT,c=TEAL,size=21):
    shape(s,.65,y,12.03,.65,bg)
    txt(s,.93,y+.15,11.5,.43,t,size,c,True)

def car(s,x,y,w=.58,h=.95,c=TEAL,turn=0):
    s=s.shapes.add_group_shape()
    shape(s,x-.07,y+.14,.10,h*.25,INK,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    shape(s,x+w-.03,y+.14,.10,h*.25,INK,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    shape(s,x-.07,y+h*.66,.10,h*.22,INK,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    shape(s,x+w-.03,y+h*.66,.10,h*.22,INK,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    shape(s,x,y,w,h,c,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    shape(s,x+.1,y+.15,w-.2,h*.20,'B8DFE0',kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    line(s,x+w/2,y+h*.7,x+w/2,y+h*.43,W,1.6,arrow=True)
    s.rotation=turn

def item(s,x,y,num,heading,body,w=5.1,c=TEAL):
    dot(s,x+.17,y+.18,.17,c)
    txt(s,x+.04,y+.045,.27,.25,str(num),12,W,True,PP_ALIGN.CENTER)
    txt(s,x+.55,y-.02,w-.55,.44,heading,21,INK,True)
    txt(s,x+.55,y+.53,w-.55,.75,body,16,MUT)

s=base(1,'松灵无人车  /  测试汇报','上周测试汇报','2026 年 11 月 9 日—11 月 13 日')
shape(s,.65,2.45,7.65,4.15,NAVY)
txt(s,1.06,3.03,6.9,1.8,'测试小车能否按路线走\n排查中途停车问题',32,W,True)
txt(s,1.09,5.43,6.8,.55,'直线测试  ·  8 字测试  ·  问题复测',19,'BFDADC')
for y,k,t,c,bg in [(2.51,'01','直线和 8 字测试',TEAL,MINT),(3.88,'02','检查掉线问题',BLUE,SOFTBLUE),(5.25,'03','修复后再测试',ORANGE,PALE)]:
    shape(s,8.62,y,4.06,1.14,bg)
    txt(s,8.88,y+.16,.7,.4,k,22,c,True)
    txt(s,9.65,y+.31,2.8,.6,t,19,INK,True)

s=base(2,'测试概览','上周主要做了三项测试')
for i,(date,title,result,c,bg) in enumerate([
    ('11.10','直线测试','快到终点时出现绕圈。',TEAL,MINT),
    ('11.11','8 字测试','途中提示有障碍，小车停下。',BLUE,SOFTBLUE),
    ('11.13','修复后复测','路线能生成，转角模拟测试通过。',ORANGE,PALE)]):
    y=2.37+i*1.12
    shape(s,.65,y,12.03,.94,bg)
    pill(s,.93,y+.25,1.0,date,c,bg)
    txt(s,2.25,y+.24,3.03,.5,title,24,INK,True)
    txt(s,5.37,y+.27,6.94,.49,result,21,MUT)
banner(s,'发现问题后进行了修复，整条路线还需要再跑一次。',size=22)

s=base(3,'11.10  /  直线测试','快到终点时，路线出现绕圈')
shape(s,.65,2.43,6.08,3.31,GREY)
txt(s,.95,2.69,5.5,.4,'路线示意',18,MUT,True)
poly(s,[(1.2,4.1),(3.2,4.1),(3.8,3.45),(4.7,3.45),(5.2,4.05),(4.72,4.71),(3.85,4.71),(3.4,4.1),(6.1,4.1)],ORANGE,3,True)
poly(s,[(1.2,4.1),(6.1,4.1)],TEAL,4)
dot(s,1.2,4.1,.1);dot(s,6.1,4.1,.12)
txt(s,.97,5.03,2.7,.32,'橙色：出现绕圈',15,ORANGE)
txt(s,3.91,5.03,2.5,.32,'绿色：希望直达',15,TEAL)
item(s,7.07,2.66,1,'测了什么','让小车沿直线走到终点。',5.45)
item(s,7.07,4.13,2,'发现什么','快到终点时，\n系统反复改路线，出现绕圈。',5.45,ORANGE)
banner(s,'修复后，能生成直达路线；还要再用实车确认。',size=22)

s=base(4,'11.11  /  8 字测试','绕 8 字时，小车中途停了下来')
shape(s,.65,2.43,5.87,3.31,GREY)
txt(s,.95,2.69,5.3,.4,'8 字路线示意',18,MUT,True)
pts=[(3.58+2.12*math.sin(t),4.24+.72*math.sin(2*t)) for t in [i*2*math.pi/180 for i in range(181)]]
poly(s,pts,TEAL,4)
for t in [.7,2.3,3.9,5.3]:dot(s,3.58+2.12*math.sin(t),4.24+.72*math.sin(2*t),.085,TEAL)
txt(s,.98,5.20,5.13,.3,'示意图，不是实际行驶记录。',13,MUT)
item(s,6.87,2.66,1,'测了什么','让小车按 8 字路线连续转弯。',5.55)
item(s,6.87,4.13,2,'发现什么','前方看起来没有障碍，\n系统却提示有障碍并停车。',5.55,ORANGE)
banner(s,'这次没有跑完全程，之后继续排查停车原因。',size=22)

s=base(5,'掉线与恢复测试','测试中还发现了设备掉线问题')
for x,title,body,result,c,bg in [
    (.65,'检查连接','设备掉线后，\n小车收不到正常反馈。','插紧线缆后观察约 1 分钟，\n暂未掉线，后续仍需检查。',ORANGE,PALE),
    (6.80,'检查继续任务','停车后，\n尝试接着完成剩下的路线。','已加入“继续任务”选项，\n还需要用实车测试。',TEAL,MINT)]:
    shape(s,x,2.43,5.87,3.28,bg)
    txt(s,x+.30,2.75,5.2,.5,title,25,c,True)
    txt(s,x+.31,3.53,5.18,.95,body,22,INK)
    txt(s,x+.31,4.82,5.18,.75,result,18,MUT)
banner(s,'先把设备连接检查好，再继续跑车。',size=23)

s=base(6,'11.13  /  无雷达测试','不接雷达，也能生成路线')
for i,(h,b,c,bg) in enumerate([
    ('之前的问题','页面一直显示\n“规划中”。',ORANGE,PALE),
    ('做了调整','改成不接雷达\n也能规划路线。',TEAL,MINT),
    ('重新测试','已经能够正常\n生成路线。',BLUE,SOFTBLUE)]):
    x=.65+i*4.1
    shape(s,x,2.45,3.83,2.91,bg)
    txt(s,x+.27,2.85,3.28,.53,h,25,c,True)
    txt(s,x+.27,3.89,3.28,1.10,b,23,INK)
banner(s,'这次只检查了路线规划，车辆没有实际行驶。',y=5.69,size=22)
txt(s,.79,6.48,11.8,.30,'无雷达时，无法发现临时出现的行人和障碍物。',14,ORANGE)

s=base(7,'11.13  /  转角复测','同一转角再次停车，修复后做了模拟测试')
for i,(num,h,b,c,bg) in enumerate([
    ('1','再次出现问题','不接雷达，\n到同一位置仍报碰撞。',ORANGE,PALE),
    ('2','找到原因','系统把转角的\n可通行空间算得太窄。',BLUE,SOFTBLUE),
    ('3','修复后测试','电脑模拟中，\n能通过转角并到终点。',TEAL,MINT)]):
    x=.65+i*4.1
    shape(s,x,2.45,3.83,3.08,bg)
    txt(s,x+.27,2.72,.7,.55,num,30,c,True)
    txt(s,x+.27,3.50,3.28,.51,h,23,INK,True)
    txt(s,x+.27,4.33,3.28,.98,b,21,MUT)
banner(s,'模拟测试已通过，实车还要再跑一次。',size=23)

s=base(8,'下一步工作','下周计划','先检查连接，再把路线完整跑一遍。')
for i,(num,title,body,c,bg) in enumerate([
    ('01','检查设备连接','检查线缆和供电，确认行驶中不掉线。',TEAL,MINT),
    ('02','重跑直线和 8 字','重点看终点前是否绕圈、转角是否误停车。',BLUE,SOFTBLUE),
    ('03','测试中断后继续','停车后继续剩余路线，确认能否到达终点。',ORANGE,PALE)]):
    y=2.45+i*1.18
    shape(s,.65,y,12.03,1.0,bg)
    txt(s,.95,y+.23,.78,.49,num,25,c,True)
    txt(s,2.03,y+.25,3.18,.48,title,23,INK,True)
    txt(s,5.43,y+.28,6.91,.48,body,19,MUT)

# Retain the evidence in speaker notes, while keeping slide text simple.
old=Presentation(OUT/'松灵无人车_本周测试汇报_20261113_测试重点版.pptx')
for i,slide in enumerate(R.slides):
    if i<7:note(slide,old.slides[i].notes_slide.notes_text_frame.text)
    else:note(slide,'下周计划：检查线缆与供电在行驶条件下是否稳定；重新完成直线与8字实车测试，观察终点绕圈和转角误停；在中断后继续剩余路线并确认到达终点。计划不是已完成成果。')
name='松灵无人车_上周测试汇报_20261113_简洁版'
R.save(OUT/(name+'.pptx'))
lines=['# 上周测试汇报（简洁版）','','周期：2026年11月9日—13日，共8页。最后一页为下周计划。','']
for i,slide in enumerate(R.slides,1):
    lines.extend([f'## 第{i}页','',*[sh.text for sh in slide.shapes if sh.has_text_frame],''])
(OUT/'简洁版_汇报内容.md').write_text('\n'.join(lines),encoding='utf-8')
print(OUT/(name+'.pptx'))

