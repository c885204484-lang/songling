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

# 01 — Test report cover.
s=base(1,'WEEKLY TEST REPORT  /  松灵无人车','本周测试工作汇报','2026 年 11 月 9 日—11 月 13 日')
shape(s,.65,2.45,7.65,4.15,NAVY)
txt(s,1.06,2.88,6.9,1.8,'开展多航点与 8 字测试\n排查停车原因并复测',32,W,True)
txt(s,1.09,5.25,6.8,.85,'重点汇报：测试过程、发现的问题\n以及处理后的验证结果',18,'BFDADC')
for y,k,t,c,bg in [(2.51,'01','直线末段与 8 字测试',TEAL,MINT),(3.88,'02','掉线与中断恢复测试',BLUE,SOFTBLUE),(5.25,'03','无雷达规划与转角复测',ORANGE,PALE)]:
    shape(s,8.62,y,4.06,1.14,bg)
    txt(s,8.88,y+.16,.7,.4,k,22,c,True)
    txt(s,9.65,y+.27,2.8,.65,t,17,INK,True)
note(s,'根据用户要求将汇报重点改为上周开展的测试，减少功能介绍。周期2026年11月9—13日，主要测试记录集中在10日、11日、13日。实车尝试、静止规划、隔离仿真与软件回归分别标注，不将局部验证等同于整条路线实车通过。')

# 02 — Test timeline.
s=base(2,'测试概览','上周主要围绕三组测试展开','从实车发现问题，再结合日志、规划检查和仿真进行验证。')
rows=[('11.10','多航点 / 直线末段','检查末段能否直达终点','发现终点前绕圈、里程计中断',TEAL,MINT),('11.11','8 字路线实车测试','检查连续转弯与航点衔接','行驶中报碰撞，恢复后仍失败',BLUE,SOFTBLUE),('11.13','无雷达与转角复测','检查无雷达规划及同点停车','规划恢复；转角仿真通过',ORANGE,PALE)]
for i,(d,h,target,result,c,bg) in enumerate(rows):
    y=2.45+i*1.10
    shape(s,.65,y,12.03,.94,GREY)
    pill(s,.88,y+.15,.95,d,c,bg)
    txt(s,2.02,y+.17,3.05,.44,h,20,INK,True)
    txt(s,5.20,y+.19,3.21,.55,target,15,MUT)
    txt(s,8.53,y+.19,3.87,.55,result,15,c,True)
banner(s,'总体结果：实车测试暴露了关键问题，修复后已完成部分规划和仿真复测。',size=18)
note(s,'依据11月10日用户关于航点2到终点直线绕圈的反馈、11月11日用户明确提及绕8字到某点报障碍并终止，以及11月13日无雷达后仍在相同位置报碰撞的反馈。没有足够记录证明上周完成S弯验收，因此不将S弯列为已通过项目。11月13日最后修复后实车未移动，转角通过为隔离仿真结果。')

# 03 — Real vehicle straight section and subsequent planning check.
s=base(3,'11.10  /  多航点路线测试','直线末段测试：接近终点时出现绕圈','测试内容：车辆从航点 2 沿较长直线路段前往终点。')
shape(s,.65,2.43,6.08,3.31,GREY)
txt(s,.95,2.68,5.5,.4,'测试问题示意（非实测轨迹）',16,MUT,True)
poly(s,[(1.2,4.1),(3.2,4.1),(3.8,3.45),(4.7,3.45),(5.2,4.05),(4.72,4.71),(3.85,4.71),(3.4,4.1),(6.1,4.1)],ORANGE,3,True)
poly(s,[(1.2,4.1),(6.1,4.1)],TEAL,4)
dot(s,1.2,4.1,.1);dot(s,6.1,4.1,.12)
txt(s,.96,4.98,2.8,.3,'橙色：终点前重算出回转',12,ORANGE)
txt(s,4.02,4.98,2.4,.3,'绿色：预期直达路线',12,TEAL)
item(s,7.07,2.54,1,'实车发现','接近终点时路线绕圈，\n本次任务最终未完成。',5.45,ORANGE)
item(s,7.07,4.03,2,'排查与处理','反复重算叠加终点朝向约束；\n改为复用有效路线并提前减速。',5.45)
banner(s,'修复后规划检查：生成约 42.7 米的近直线路径，实车到达仍待复测。',size=18)
note(s,'11月10日16:19用户反馈航点2到终点的大直线快到终点时绕圈导致失败。16:48记录确认每秒无条件重规划叠加终点朝东和最小转弯半径；当次最终中止日志仍是滤波里程计超时。修复路线复用，航点2朝向由30度调为约-1.2度，末段提前2米减速。42.7m为规划验证长度，并非实车完成里程。图为问题概念示意。')

# 04 — Figure-eight real vehicle attempt.
s=base(4,'11.11  /  8 字路线实车测试','8 字测试：行驶中提示“前方有障碍”并终止','测试内容：沿设定航点连续转弯，观察交叉路段与后续航点的衔接。')
shape(s,.65,2.43,5.87,3.31,GREY)
txt(s,.95,2.68,5.3,.4,'8 字路线概念示意',17,MUT,True)
pts=[(3.58+2.12*math.sin(t),4.24+.72*math.sin(2*t)) for t in [i*2*math.pi/180 for i in range(181)]]
poly(s,pts,TEAL,4)
for t in [.7,2.3,3.9,5.3]:
    dot(s,3.58+2.12*math.sin(t),4.24+.72*math.sin(2*t),.085,TEAL)
txt(s,.98,5.15,5.13,.3,'非实测轨迹，停车位置以现场日志为准。',12,MUT)
item(s,6.87,2.54,1,'现场现象','前方看似无障碍，系统仍报碰撞；\n任务终止后未能顺利恢复。',5.55,ORANGE)
item(s,6.87,4.03,2,'检查发现','局部地图有旧障碍残留，\n停车后的重规划与等待也有问题。',5.55)
banner(s,'本轮结果：未完成 8 字全程；已针对障碍清除和恢复流程开展修复。',size=18)
note(s,'11月11日16:11用户反馈前方无物；16:50明确反馈绕8字到截图位置后报障碍并终止。排查发现16个无当前回波对应的障碍格，但未保存当时触发瞬间，无法确定具体是哪一格，也不能断言该次全部由残影引起。控制器恢复重发旧长路径会出现局部路径为空；清图服务20ms超时造成重试失败。后续细化扫描间隔，改为从当前位置重规划，服务超时调至200ms、清图后等待1秒。左图仅表达8字测试形态，不表达实际路径或精确停车点。')

# 05 — Connection and interrupted mission verification.
s=base(5,'11.10—11.11  /  稳定性与恢复测试','测试中反复中断，重点检查连接与任务恢复','将设备掉线、数据短暂延迟和中断后续跑分开验证。')
shape(s,.65,2.43,5.87,3.28,PALE)
txt(s,.94,2.70,5.24,.49,'连接稳定性：做了静止复测',23,ORANGE,True)
txt(s,.96,3.45,5.18,1.24,'发现 USB 断连，CAN / GPS 丢失。\n处理线缆后监测约 63 秒，\n该次未出现反馈中断。',18,INK)
txt(s,.96,5.03,5.15,.41,'后续仍有断连，需继续检查硬件。',16,ORANGE,True)
shape(s,6.8,2.43,5.87,3.28,MINT)
txt(s,7.09,2.70,5.24,.49,'任务恢复：完成软件侧验证',23,TEAL,True)
txt(s,7.11,3.45,5.16,1.24,'检查进度保存、继续任务弹窗，\n以及按剩余航点重新规划。\n相关回归与弹窗检查通过。',18,INK)
txt(s,7.11,5.03,5.15,.41,'实车中断后续跑仍需完整复测。',16,TEAL,True)
banner(s,'测试结论：短暂恢复不等于链路稳定，软件检查通过后还需行驶验证。',size=18)
note(s,'11月10日内核USB -71错误导致CAN与GPS消失；用户处理线缆后静止监测约63秒240次，最大数据年龄约0.03秒。11月11日16:48:31后又反复USB断连，故不能描述为硬件已根治。增加原始底盘反馈检查，并修复短时滤波里程计延迟的等待恢复。11月11日工作记录报告111项回归、3项原生及弹窗测试通过，覆盖任务继续等改动；没有证据证明当时实车完整续跑通过。不同阶段测试数量不累加。')

# 06 — No-lidar planning test.
s=base(6,'11.13  /  无雷达规划测试','无雷达测试：从“一直规划”到正常生成路线','测试内容：关闭雷达依赖，检查 4 个航点加终点能否完成规划。')
for i,(h,b,c,bg) in enumerate([('测试中遇到的问题','页面长时间显示规划中\n采集 6 秒没有雷达消息\n实际卡在等待扫描数据',ORANGE,PALE),('调整后重新测试','采用底盘轮速与双天线 RTK\n解除雷达数据依赖\n按原航点顺序再次规划',TEAL,MINT),('本轮验证结果','4 个航点 + 终点\n约 0.23 秒生成规划路径\n测试期间车辆保持静止',BLUE,SOFTBLUE)]):
    x=.65+i*4.1
    shape(s,x,2.45,3.83,2.91,bg)
    txt(s,x+.25,2.74,3.34,.5,h,22,c,True)
    txt(s,x+.25,3.66,3.34,1.30,b,17,INK)
shape(s,.65,5.68,12.03,.65,MINT)
txt(s,.94,5.84,11.44,.38,'结果：无雷达条件下规划通过，整条路线实车行驶仍待复测。',20,TEAL,True)
txt(s,.78,6.47,11.88,.29,'测试条件说明：无雷达模式不检测临时出现的行人和障碍物。',14,ORANGE,True)
note(s,'11月13日15:03记录订阅6秒，点云、IMU和scan均0消息，日志scan超时已超过7分钟。用户要求取消必须接雷达才能运行。15:15结果：采用轮速和双天线RTK，解除雷达依赖，四航点加终点约0.23s完成规划，车辆未移动。该时间是单次本机规划观测，不代表平均性能或整车行驶通过。保留地图禁行、定位与底盘检查。无雷达无法检测临时动态障碍。')

# 07 — Corner reproduction and simulation replay.
s=base(7,'11.13  /  同一转角复测','关闭雷达后仍在同处报碰撞，再对转角做回放','测试目的：确认误停车是否只由雷达数据引起。')
for i,(num,h,b,c,bg) in enumerate([('1','现场再次出现','无雷达模式下\n相同位置仍报碰撞\n继续排查地图和车身检查',ORANGE,PALE),('2','发现重复计算','地图已预留安全边距\n控制器又叠加车身范围\n导致转角空间被重复扣除',BLUE,SOFTBLUE),('3','修复后仿真复测','从暂停位置出发\n经过航点 4 到达终点\n本次碰撞事件为 0',TEAL,MINT)]):
    x=.65+i*4.1
    shape(s,x,2.45,3.83,3.08,bg)
    txt(s,x+.25,2.68,.7,.55,num,30,c,True)
    txt(s,x+.25,3.40,3.34,.48,h,23,INK,True)
    txt(s,x+.25,4.15,3.34,1.21,b,17,MUT)
    if i<2:line(s,x+3.87,3.87,x+4.06,3.87,TEAL,2,arrow=True)
banner(s,'本轮结果：该转角仿真回放通过；修复后的实车复测尚未完成。',size=19)
note(s,'11月13日15:23用户明确表示无雷达后仍在与前一天相同位置报碰撞。15:34最终结果确认导航图已经扩边，控制器又加车身范围，产生重复扩边。修复保留真实障碍和安全距离检查。隔离仿真从本次暂停位置经过航点4到终点，碰撞事件0；实车未移动，原前三航点进度保留。144项回归通过。本页仅表述该次局部仿真成功，不能推断8字全程实车通过。')

# 08 — Test conclusions and next test plan.
s=base(8,'测试结论与下轮安排','已完成问题定位与局部复测，继续验证实车全程','上周测试帮助我们明确了绕圈、异常停车和中断恢复的主要问题。')
rows=[('实车路线测试','已开展直线末段、8 字测试，过程中发生中断。',ORANGE,PALE),('修复后规划检查','直线末段、无雷达多航点规划均得到有效路径。',TEAL,MINT),('局部仿真与软件检查','转角仿真通过；截至 11 月 13 日，144 项回归检查通过。',BLUE,SOFTBLUE)]
for i,(h,b,c,bg) in enumerate(rows):
    y=2.44+i*.83
    shape(s,.65,y,12.03,.67,bg)
    txt(s,.94,y+.15,3.0,.38,h,19,c,True)
    txt(s,4.07,y+.18,8.29,.37,b,16,INK)
txt(s,.71,5.12,11.8,.42,'下一轮重点测试',22,INK,True)
for i,(h,b,c) in enumerate([('连接稳定','覆盖行驶振动\n检查 USB / CAN / GPS',TEAL),('整程跑通','复测直线末段与 8 字\n记录轨迹和停车点',BLUE),('中断续跑','停车后继续剩余航点\n确认最终到达终点',TEAL)]):
    x=.65+i*4.1
    shape(s,x,5.72,3.83,.94,GREY)
    txt(s,x+.18,5.91,1.15,.42,h,18,c,True)
    txt(s,x+1.43,5.89,2.22,.67,b,13,MUT)
note(s,'总结仅依据上周已有记录，不重新运行车辆测试。实车部分有明确问题反馈，最终修复后完成规划和局部仿真，尚无整条8字路线实车到达及中断续跑最终验收证据。144项为11月13日修复后的回归结果，不与此前111项、132项相加。下轮重点是连接在行驶振动下稳定、原路线完整跑通、途中暂停后按剩余航点继续至原终点。')

name='松灵无人车_本周测试汇报_20261113_测试重点版'
R.save(OUT/(name+'.pptx'))
lines=['# 松灵无人车上周测试汇报','', '周期：2026 年 11 月 9 日—11 月 13 日。8 页，16:9，沿用原样式。',
       '本版以实际测试、现场问题、排查处理及复测结果为主；分别标注实车、静止规划、仿真和软件检查。','']
for i,slide in enumerate(R.slides,1):
    texts=[sh.text for sh in slide.shapes if sh.has_text_frame]
    lines.extend([f'## 第 {i} 页','',*texts,'','讲解与依据：'+slide.notes_slide.notes_text_frame.text,''])
(OUT/'测试重点版_汇报说明.md').write_text('\n'.join(lines),encoding='utf-8')
print(OUT/(name+'.pptx'))

