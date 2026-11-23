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

def base(n,kicker,title,sub='',foot='松灵无人车  ·  周工作汇报  ·  2026.11.02—11.06'):
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

# 01 — Cover
s=base(1,'WEEKLY PROGRESS  /  松灵无人车','本周工作进度汇报','2026 年 11 月 2 日—11 月 6 日')
shape(s,.65,2.45,7.65,4.15,NAVY)
txt(s,1.06,2.88,6.8,1.8,'简化操作界面\n排查 S 弯测试问题',34,W,True)
txt(s,1.09,5.25,6.8,.8,'同步整理两项专利稿\n动态安全距离  /  重规划同步切换',18,'BFDADC')
for y,k,t,c,bg in [(2.51,'01','UI 简化',TEAL,MINT),(3.88,'02','S 弯测试与原因排查',ORANGE,PALE),(5.25,'03','两份专利稿撰写',BLUE,SOFTBLUE)]:
    shape(s,8.62,y,4.06,1.14,bg)
    txt(s,8.88,y+.16,.7,.4,k,22,c,True)
    txt(s,9.68,y+.31,2.7,.6,t,18,INK,True)
note(s,'本周汇报包含用户指定的三项工作：简化UI；S弯测试未成功，排查后发现地图没有配准；动态安全距离与方向四两项专利稿撰写。周报周期按当前日期2026-11-06所在工作周设置。专利仅介绍问题和方法，不展开权利要求及公式。')

# 02 — Progress
s=base(2,'本周概览','三项工作：界面、测试、专利','本周明确了下一轮实车测试的前置工作：先把地图与现场对齐。')
data=[('01','简化 UI','完成界面精简','地图和常用操作更集中\n设置与详情按需展开',TEAL,MINT),('02','S 弯测试','测试未成功','排查发现地图未配准\n现场对齐后再复测',ORANGE,PALE),('03','专利稿撰写','形成两份稿件','动态安全距离专利稿\n方向四：重规划同步切换',BLUE,SOFTBLUE)]
for i,(num,title,status,body,c,bg) in enumerate(data):
    x=.65+4.1*i
    shape(s,x,2.48,3.83,3.82,GREY)
    txt(s,x+.27,2.74,.8,.5,num,28,c,True)
    txt(s,x+.27,3.46,3.3,.52,title,26,INK,True)
    pill(s,x+.27,4.22,2.32,status,c,bg)
    txt(s,x+.27,5.04,3.3,1.06,body,17,MUT)
note(s,'UI精简依据当前simple.html/simple.css/simple.js及OFFLINE_NAVIGATION.md简易UI章节。S弯失败与地图未配准的结论采用用户提供的信息，未补造测试次数、误差或具体实车轨迹。两份稿件在outputs/动态安全距离专利稿与outputs/方向四专利稿中均已有Word和PDF。形成稿件不表示已提交申请或实车验证完成。')

# 03 — UI schematic
s=base(3,'01  /  简化 UI','让地图和常用操作更突出','精简主界面，把设置、坐标和详细信息收进次级入口。')
shape(s,.65,2.38,8.1,4.28,'14222D',kind=MSO_SHAPE.ROUNDED_RECTANGLE)
txt(s,.89,2.53,5.5,.3,'S   园区导航  ·  西电杭研院',12,W,True)
pill(s,7.18,2.52,1.27,'布局示意','8ADACD','29443F')
src=Path('/home/nvidia/.local/share/songling/offline_maps/xidian_hangzhou_lvxuelu177/20261105-164755-8aa9eb80/basemap.png')
if src.exists():
    shutil.copyfile(src,ASSETS/'campus_basemap.png')
    p=s.shapes.add_picture(str(ASSETS/'campus_basemap.png'), Inches(.84), Inches(2.99),width=Inches(5.15),height=Inches(3.17))
    # Crop rather than stretch the square basemap to the map viewport.
    p.crop_top=p.crop_bottom=(1-3.17/5.15)/2
for j,t in enumerate(['平移','终点','航点','掩码编辑']):
    shape(s,1.00+j*1.14,3.12,1.02,.32,'263B48')
    txt(s,1.05+j*1.14,3.18,.92,.2,t,8,W,align=PP_ALIGN.CENTER)
shape(s,6.16,3.0,2.37,3.17,'1E303D')
for y,t,bg,c in [(3.15,'快捷目的地','304450',W),(3.65,'规划路径','304450',W),(4.13,'开始导航','63D4B9',NAVY),(4.63,'地图与设置','304450',W),(5.44,'停止','9D3F49',W)]:
    shape(s,6.35,y,1.98,.37,bg,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    txt(s,6.4,y+.075,1.88,.25,t,10,c,True,PP_ALIGN.CENTER)
txt(s,1.0,6.3,7.25,.22,'CAN 状态     ·     遥控档位     ·     定位状态     ·     运动状态',10,'BFD3DF')
for y,num,title,body in [(2.53,'1','地图放在主区域','查看位置、终点和航点'),(3.78,'2','常用按钮集中','规划、开始、停止更直接'),(5.03,'3','详细设置按需打开','保留地图配准与状态查询')]:
    dot(s,9.18,y+.18,.16,TEAL);txt(s,9.05,y+.045,.26,.27,num,12,W,True,PP_ALIGN.CENTER)
    txt(s,9.55,y,3.1,.42,title,20,INK,True);txt(s,9.55,y+.56,3.12,.63,body,15,MUT)
note(s,'左侧为依据当前简易UI重绘的布局示意，背景使用项目已保存的园区底图；不是运行截图，不承载实时车辆状态或实际轨迹。当前UI将地图、终点航点、规划、开始导航、停止集中，地图与设置保留ROS连接、地图配准、导入导出保存，底部显示CAN、遥控、定位、运动状态。来源src/songling_navigation/web/offline_nav/simple.html与OFFLINE_NAVIGATION.md。')

# 04 — S-curve test
s=base(4,'02  /  S 弯测试','S 弯测试未成功，排查发现地图未配准','测试目标：让小车按连续弯道路线行驶。')
shape(s,.65,2.48,5.43,3.98,GREY)
txt(s,.96,2.72,4.85,.4,'测试路线示意',17,MUT,True)
pts=[(1.22+4.18*t,4.38+.69*math.sin(2*math.pi*t)) for t in [i/80 for i in range(81)]]
poly(s,[(x,y-.42) for x,y in pts],LINE,22)
poly(s,[(x,y+.42) for x,y in pts],LINE,22)
poly(s,pts,TEAL,3)
for k,i in enumerate([0,20,40,60,80]):
    x,y=pts[i];dot(s,x,y,.085,TEAL);txt(s,x-.17,y+.17,.45,.25,str(k+1),10,TEAL,True)
txt(s,.99,5.77,4.8,.4,'连续航点  →  转弯  →  到达终点',16,MUT)
pill(s,6.6,2.55,2.1,'本周结果：未成功',ORANGE,PALE)
for i,(h,b,c) in enumerate([('开展 S 弯测试','尝试按设定弯道路线行驶',INK),('针对失败开展排查','关注路径、地图与车辆位置的对应',INK),('发现地图没有配准','底图与实车定位未正确对齐',ORANGE)]):
    y=3.22+1.08*i
    dot(s,6.82,y+.2,.09,c)
    if i<2:line(s,6.82,y+.35,6.82,y+.92,LINE,2)
    txt(s,7.16,y,5.14,.45,h,22,c,True);txt(s,7.18,y+.52,5.12,.4,b,16,MUT)
note(s,'测试失败以及排查后发现地图未配准，均依据用户本次说明。左图仅是S形航点测试的概念示意，不是采集轨迹。未推断测试次数、偏移数值或所有原因已排除。当前代码也提示S弯航点需按切线设置朝向并满足转弯空间，本页不将其表述为本周已完成的独立测试结论。现场配准及配准后复测待开展。')

# 05 — Registration
s=base(5,'02  /  原因说明','地图配准：让“图上的路”对上“现场的路”','位置对不上时，规划用的路线和实际道路就无法准确对应。')
for x,title,aligned in [(.65,'当前问题：没有对齐',False),(6.8,'配准目标：统一到同一位置',True)]:
    shape(s,x,2.49,5.87,3.25,GREY)
    txt(s,x+.25,2.73,5.38,.4,title,20,TEAL if aligned else ORANGE,True)
    y=4.39
    shape(s,x+.52,y-.39,4.82,.78,'D1DDE3')
    line(s,x+.55,y, x+5.3,y,W,2,dash=True)
    offset=0 if aligned else -.78
    shape(s,x+.5,y-.4+offset,4.85,.79,None,TEAL if aligned else ORANGE,sw=2)
    car(s,x+2.6,4.06,.46,.70,TEAL)
    if not aligned:line(s,x+4.54,3.63,x+4.54,4.4,ORANGE,2,arrow=True)
    txt(s,x+.48,5.17,4.93,.29,'灰色：现场道路    彩框：地图道路',12,MUT)
shape(s,.65,6.0,12.03,.69,MINT)
txt(s,.93,6.18,11.5,.4,'下一步：采集对应点 → 对齐地图 → 独立检查 → 重新测试 S 弯',20,TEAL,True)
note(s,'图为配准前与配准目标示意，不表示本周已完成现场配准。灰色道路为现场，彩色轮廓为地图，车辆定位固定，从而说明地图与定位的相对错位。RTK固定解不代表卫星底图已经与现场配准。项目配准流程为固定定位map原点与朝向，采集至少3个分散不共线对应点及至少1个独立检查点，拟合、检查后另存并重新应用地图。来源OFFLINE_NAVIGATION.md网页地图配准章节。本周仅写已定位问题，配准与复测列入下一步。')

# 06 — Patent A, problem
s=base(6,'03  /  专利稿一：动态安全距离','要解决的问题：窄路有空间，却被固定距离挡住','专利稿：无人车窄通道动态安全距离控制方法及系统')
shape(s,.65,2.47,7.05,3.92,GREY)
txt(s,.95,2.7,6.4,.4,'用稿件里的示例说明',16,MUT,True)
# Cross-section drawn to one scale; default center distances overlap.
left,right=1.70,6.43; top=3.48; bottom=5.32; scale=(right-left)/.9
shape(s,left,top,right-left,bottom-top,W)
shape(s,left-.16,top,.16,bottom-top,INK);shape(s,right,top,.16,bottom-top,INK)
cw=.64*scale; cx=(left+right-cw)/2
shape(s,cx,3.9,cw,1.03,TEAL,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
txt(s,cx,4.20,cw,.4,'车宽 0.64 米',20,W,True,PP_ALIGN.CENTER)
line(s,left,3.28,right,3.28,INK,1.4)
line(s,left,3.2,left,3.36,INK,1.4);line(s,right,3.2,right,3.36,INK,1.4)
txt(s,2.50,3.02,3.0,.3,'通道宽 0.90 米',15,INK,True,PP_ALIGN.CENTER)
line(s,left,5.64,left+.65*scale,5.64,RED,2,arrow=True)
line(s,right,5.99,right-.65*scale,5.99,RED,2,arrow=True)
txt(s,1.68,5.24,4.98,.3,'默认要求：车中心距每侧边界 0.65 米',12,RED,True)
txt(s,8.11,2.73,4.38,.56,'固定距离过于保守',25,INK,True)
txt(s,8.13,3.58,4.2,1.13,'左右各要留 0.65 米，\n0.90 米窄路无法满足。',21,MUT)
txt(s,8.13,4.96,4.22,1.05,'希望根据车身和误差，\n判断能否合理减少余量。',20,TEAL,True)
txt(s,.92,6.57,11.7,.25,'数字用于解释稿件中的几何关系，不代表实车已通过该通道。',10,MUT)
note(s,'依据动态安全距离专利稿背景与算例：通道净宽0.90m、默认中心距离0.65m、车宽0.64m。0.65m是车参考点到边界的距离，不是车身外侧净距，因此不能将图中红色距离解释为车身两边各加0.65m。几何上车身能容纳不等于可以实车安全通行，还需误差、姿态、连续运动和停车校验。此页数字为稿件说明算例，不是实测通行结果。')

# 07 — Patent A, method
s=base(7,'03  /  专利稿一：采用的方法','分清“必须留的距离”和“可以调整的余量”','只调整额外余量，同时确认整条路能走、途中也能停。')
for i,(num,h,b,c,bg) in enumerate([('1','算出不能缩的底线','车身占用 + 定位误差\n+ 控制误差 + 基本间隙',TEAL,MINT),('2','再调整额外的余量','路窄时按条件减少\n车身尺寸始终不变',BLUE,SOFTBLUE),('3','检查能否完整通过','入口能对正、全程能走\n并保留停车方案',TEAL,MINT)]):
    x=.65+4.1*i
    shape(s,x,2.51,3.83,2.86,bg)
    txt(s,x+.25,2.75,.7,.6,num,32,c,True)
    txt(s,x+.25,3.58,3.33,.5,h,21,INK,True)
    txt(s,x+.25,4.37,3.32,.83,b,17,MUT)
    if i<2:line(s,x+3.88,3.92,x+4.06,3.92,TEAL,2,arrow=True)
shape(s,.65,5.74,5.87,.81,MINT);txt(s,.93,5.96,5.35,.4,'满足条件：低速对正后通行',20,TEAL,True)
shape(s,6.8,5.74,5.87,.81,PALE);txt(s,7.08,5.96,5.35,.4,'不满足条件：停车，不进入窄路',20,ORANGE,True)
note(s,'通俗对应稿件方法：1.计算左右不可压缩距离下限，包括真实轮廓、姿态和有效误差；2.将默认距离超出硬下限的部分作为可分配余量，按保留系数有条件释放；3.使用连续扫掠、前向可达及后向可续行筛选，检查从当前状态到出口的完整链及停车分支。不能把减小目标速度直接当成当前状态已降速，也不能只看局部宽度。已有参数与有限状态图算例核验，不是车辆仿真、误差标定或实车通行试验。')

# 08 — Patent B, problem
s=base(8,'03  /  专利稿二：方向四','要解决的问题：车换了路线，保护还盯着旧路线','专利稿：无人车重规划路径与安全保护参考的同步切换方法及系统')
shape(s,.65,2.47,7.05,3.98,GREY)
txt(s,.96,2.71,6.43,.4,'正常绕障，也可能被误判为偏离',18,INK,True)
line(s,1.26,4.59,7.02,4.59,MUT,2.5,dash=True)
new=[(1.26,4.59),(2.0,4.59),(2.60,4.17),(3.04,3.66),(4.85,3.66),(5.51,4.22),(6.02,4.59),(7.02,4.59)]
poly(s,new,TEAL,4)
shape(s,3.45,4.16,.83,.83,ORANGE,kind=MSO_SHAPE.ROUNDED_RECTANGLE)
txt(s,3.49,4.44,.76,.32,'障碍',12,W,True,PP_ALIGN.CENTER)
car(s,4.36,3.3,.41,.68,TEAL,turn=90)
line(s,4.56,3.98,4.56,4.59,RED,1.7,arrow=True)
txt(s,4.75,4.12,2,.36,'按旧路看：偏离',12,RED,True)
line(s,1.12,5.75,1.65,5.75,TEAL,3);txt(s,1.77,5.58,2.15,.4,'新路线：绕障',14,TEAL,True)
line(s,4.12,5.75,4.65,5.75,MUT,2,dash=True);txt(s,4.77,5.58,2.35,.4,'旧路线',14,MUT)
for y,c,h,b in [(2.75,TEAL,'控制器：已经换路','沿新路线正常绕开障碍'),(4.13,RED,'保护模块：仍看旧路','把正常绕行判断为偏离')]:
    txt(s,8.1,y,4.4,.49,h,23,c,True);txt(s,8.13,y+.67,4.3,.52,b,18,MUT)
pill(s,8.12,5.59,3.76,'结果：出现不必要的停车',RED,PINK)
note(s,'依据方向四专利稿背景：控制器跟随重规划路径，保护仍参考旧路径时，正常绕障可能被误判为偏离并停车。图仅为几何示意。另一方面，直接接受从当前偏离位置产生的新路径，可能把先前的真实故障覆盖，因此方法既要解决误停，也要保留原故障。本稿是对已有软件基础的进一步整理，完整代次协议、并发异常和实车性能仍待对照验证。')

# 09 — Patent B, method
s=base(9,'03  /  专利稿二：采用的方法','先检查旧路线，再一起切到新路线','导航与保护使用同一条有效路线，旧指令也不能混进来。')
for i,(num,h,b,c,bg) in enumerate([('1','先检查','换路前先看是否\n已经偏离旧路线',TEAL,MINT),('2','同步换路','暂时阻断运动输出\n导航与保护一起更新',BLUE,SOFTBLUE),('3','确认后继续','确认新路、新指令\n检查通过再恢复行驶',TEAL,MINT)]):
    x=.65+4.1*i
    shape(s,x,2.5,3.83,2.72,bg)
    txt(s,x+.25,2.74,.75,.6,num,32,c,True)
    txt(s,x+.25,3.53,3.3,.49,h,24,INK,True)
    txt(s,x+.25,4.22,3.3,.84,b,18,MUT)
    if i<2:line(s,x+3.88,3.85,x+4.06,3.85,TEAL,2,arrow=True)
shape(s,.65,5.62,12.03,.95,NAVY)
txt(s,.96,5.90,11.4,.46,'已有故障继续保留    ·    旧路线指令作废    ·    切换失败就保持停止',20,W,True)
note(s,'通俗对应稿件步骤：旧参考检查与故障锁定优先；对新路径做任务、地图、目标和衔接等一致性验收；关闭输出，建立新路径代次，同步控制器与保护参考，使旧指令失效；等待控制器确认及明确来自新路径的有效新指令，复核当前状态和预测轨迹后恢复输出。发送零速度不等于已经停车，需实测速度确认。已有故障不会因新路径产生而解除，超时或失败保持输出抑制。这里是专利方法介绍，不声称完整方案本周已实车验收。')

# 10 — Next steps
s=base(10,'下一步工作','先完成地图配准，再复测 S 弯','专利稿继续结合测试场景完善，让问题、方法和验证一一对应。')
rows=[('01','现场配准地图','采集地图与现场对应点，用独立检查点核对结果。',TEAL,MINT),('02','重新测试 S 弯','地图对齐后复测，记录轨迹、失败原因和停车情况。',ORANGE,PALE),('03','完善两份专利稿','补充易懂的示意图、算例和后续验证内容。',BLUE,SOFTBLUE)]
for i,(num,h,b,c,bg) in enumerate(rows):
    y=2.48+i*1.25
    shape(s,.65,y,12.03,1.07,bg)
    txt(s,.96,y+.22,.72,.55,num,27,c,True)
    txt(s,1.97,y+.26,3.35,.48,h,23,INK,True)
    txt(s,5.47,y+.31,6.85,.5,b,16,MUT)
note(s,'本页是建议的下一步工作安排，不代表已经执行。现场配准与独立检查完成后，再开展S弯复测。专利一已有参数几何与有限状态图算例核验，实车验证尚待开展；方向四稿已有软件基础及场景算例，完整协议、并发与实车性能尚待验证。两稿均按已形成文稿描述，不表述为已申请、已授权或已完成实车验收。')

R.core_properties.title='松灵无人车｜本周工作进度汇报｜2026.11.02—11.06'
R.core_properties.subject='UI简化、S弯测试与地图配准排查、动态安全距离及方向四专利稿'
R.core_properties.author='松灵无人车项目组'
R.core_properties.keywords='周报,UI,S弯,地图配准,动态安全距离,方向四'
assert len(R.slides)==10
issues=[]
for i,slide in enumerate(R.slides,1):
    for q in slide.shapes:
        if q.left < -1000 or q.top < -1000 or q.left+q.width>R.slide_width+1000 or q.top+q.height>R.slide_height+1000:
            issues.append((i,q.shape_id,'out of slide'))
assert not issues, issues
name='松灵无人车_本周进度汇报_20261106'
R.save(OUT/(name+'.pptx'))
summary='''# 本周工作进度汇报

周期：2026 年 11 月 2 日—11 月 6 日。共 10 页，16:9，主要文字和示意图可编辑，每页附讲解备注。

1. 封面：UI 简化、S 弯测试、两项专利稿。
2. 本周概览：UI 已精简；S 弯未成功，发现地图未配准；形成两份专利稿。
3. UI 简化：依据当前简易 UI 绘制布局示意，突出地图、常用操作、状态栏。
4. S 弯测试：说明测试未成功及排查发现地图未配准，S 形线路为概念示意。
5. 地图配准：用道路错位和对齐目标说明配准含义，配准与复测列为下一步。
6. 动态安全距离专利稿：固定距离可能使实际有空间的窄路不可通行。
7. 方法：保留车身与误差决定的底线，只调整额外余量，同时检查连续通过及停车。
8. 方向四专利稿：导航换路而保护仍看旧路，可能导致正常绕障误停车。
9. 方法：检查旧路径故障、同步切换、拒绝旧指令、确认新路径与新指令后恢复。
10. 下一步：现场配准、复测 S 弯、完善两稿及验证内容。

内容依据：用户本次提供的测试结果；当前 simple.html / simple.css / simple.js 和 OFFLINE_NAVIGATION.md；outputs 下动态安全距离与方向四两份专利正文。数字仅取自稿件算例，不作实车测试成果。当前未声称配准完成、S 弯通过、专利已申请或授权。
'''
(OUT/'汇报说明.md').write_text(summary,encoding='utf-8')
print(OUT/(name+'.pptx'))
