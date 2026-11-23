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

# 01 — Cover: reuse the previous report's palette, typography and layout.
s=base(1,'WEEKLY PROGRESS  /  松灵无人车','本周工作进度汇报','2026 年 11 月 9 日—11 月 13 日')
shape(s,.65,2.45,7.65,4.15,NAVY)
txt(s,1.06,2.88,6.9,1.8,'优化路线跟踪\n完善停车与任务恢复',34,W,True)
txt(s,1.09,5.25,6.8,.85,'排查底盘反馈异常\n完成无雷达导航模式切换',18,'BFDADC')
for y,k,t,c,bg in [(2.51,'01','减少绕圈与误停车',TEAL,MINT),(3.88,'02','中断任务可以继续',BLUE,SOFTBLUE),(5.25,'03','支持无雷达导航',ORANGE,PALE)]:
    shape(s,8.62,y,4.06,1.14,bg)
    txt(s,8.88,y+.16,.7,.4,k,22,c,True)
    txt(s,9.65,y+.31,2.8,.6,t,18,INK,True)
note(s,'周期为2026年11月9日至13日。依据11月10日、11日、13日的项目工作记录和当前实现整理。本周重点是现场问题排查、软件修复、任务继续功能及无雷达模式。历史记录中的回归、静止规划与仿真结果分别陈述，不将其作为整车道路验收通过的证据。')

# 02 — Overview.
s=base(2,'本周概览','围绕“能按路线走、停后能继续”开展改进','完成多项软件修复与功能部署，整条路线的实车复测仍需继续。')
cards=[('01','路线跟踪','有效路线继续用\n减少终点前反复绕圈',TEAL,MINT),('02','任务恢复','保存已完成进度\n继续执行剩余目标',BLUE,SOFTBLUE),('03','底盘与定位','区分短时延迟和掉线\n直接检查底盘原始反馈',TEAL,MINT),('04','无雷达模式','轮速 + 双天线 RTK\n不再等待雷达数据',ORANGE,PALE)]
for i,(n,h,b,c,bg) in enumerate(cards):
    x=.65+3.075*i
    shape(s,x,2.49,2.805,2.96,bg)
    txt(s,x+.22,2.74,.8,.5,n,28,c,True)
    txt(s,x+.22,3.48,2.4,.5,h,23,INK,True)
    txt(s,x+.22,4.29,2.4,.91,b,16,MUT)
shape(s,.65,5.78,12.03,.88,GREY)
txt(s,.93,5.97,11.45,.48,'操作调整：移除地图配准入口及强制配准限制，保留其余地图设置。',18,INK)
note(s,'11月10日完成配准入口和强制门槛移除；同日修复终点重规划、滤波里程计等待逻辑并增加底盘原始反馈检查。11月11日增加任务进度与继续弹窗，修复恢复流程。11月13日完成无雷达模式及重复扩边修复。移除配准门槛是用户要求的界面和流程调整，不等于地图已通过多点精度核验；11月10日保存过单点平移近似对齐，不作完整配准成果表述。')

# 03 — Terminal route.
s=base(3,'01  /  路线跟踪','终点前绕圈：减少不必要的重新规划','问题：原本可以直行，接近终点时却反复改成回转路线。')
shape(s,.65,2.43,6.08,3.31,GREY)
txt(s,.95,2.68,5.5,.4,'路线变化示意',17,MUT,True)
poly(s,[(1.2,4.1),(3.2,4.1),(3.8,3.45),(4.7,3.45),(5.2,4.05),(4.72,4.71),(3.85,4.71),(3.4,4.1),(6.1,4.1)],ORANGE,3,True)
poly(s,[(1.2,4.1),(6.1,4.1)],TEAL,4)
dot(s,1.2,4.1,.1);dot(s,6.1,4.1,.12)
txt(s,1.05,4.98,2.4,.3,'橙色：反复重算后回转',12,ORANGE)
txt(s,3.99,4.98,2.45,.3,'绿色：复用有效直线',12,TEAL)
item(s,7.07,2.54,1,'查明原因','每秒重算路线，叠加终点朝向\n和最小转弯半径约束。',5.45)
item(s,7.07,4.03,2,'调整方法','原路有效就继续使用；遇障或\n目标变化再重算，并提前减速。',5.45)
banner(s,'规划验证：航点 2 到终点生成约 42.7 米的近直线路径。',size=20)
note(s,'来源：11月10日16:48工作结果及OFFLINE_NAVIGATION.md路线复用说明。原行为树每秒无条件重规划，临近终点车头偏转后，前进Dubins规划为满足终点朝向和1.9m最小转弯半径产生回转。修复有效路径复用，航点2朝向从30度调到约-1.2度，末段提前2m减速。42.7m是规划路径长度，并非实车完成行驶里程；当次任务最终中止日志仍涉及滤波里程计超时。图为概念示意，不是实测轨迹。')

# 04 — Three causes of collision reports.
s=base(4,'02  /  碰撞问题排查','“前面没东西”也停车：分开排查三类原因','同一条碰撞提示可能对应不同问题，本周逐项修复并补充现场记录。')
rows=[('11.11','旧障碍残留','地图留有已消失的回波','细化扫描间隔，改善旧障碍清除',TEAL,MINT),('11.11','停车后恢复失败','旧长路径重发，清图等待过短','从当前位置重规划，等待地图更新',BLUE,SOFTBLUE),('11.13','转角重复计算边距','地图已留边距，又叠加车身范围','消除重复扩边，保留真实碰撞检查',ORANGE,PALE)]
for i,(d,h,b,a,c,bg) in enumerate(rows):
    y=2.42+i*1.12
    shape(s,.65,y,12.03,.97,GREY)
    pill(s,.89,y+.16,.94,d,c,bg)
    txt(s,2.02,y+.17,2.68,.44,h,20,INK,True)
    txt(s,4.78,y+.19,3.45,.56,b,15,MUT)
    txt(s,8.38,y+.19,3.96,.56,a,15,c,True)
banner(s,'最新转角仿真：从暂停点经过航点 4 到达终点，碰撞事件为 0。',size=19)
note(s,'11月11日发现16个缺少当前对应回波的障碍格；没有报错瞬间证据，不能断定每次停车均由残影造成。扫描角度间隔从0.025rad调至0.005rad，使用本机Nav2射线清除回归。恢复改为清图后等待1s，从当前位置规划剩余目标；服务超时20ms改200ms。11月13日在无雷达模式仍出现同位置碰撞，进一步确认静态导航图已扩边与控制器车身检查重复；引入独立footprint_map消除重复计算，保留原始障碍、禁行及安全边距。工作记录报告转角隔离仿真成功且碰撞事件0、实车未移动。碰撞时保存前三帧局部地图、坐标变换、扫描和预测轨迹。')

# 05 — Resume modal and route progress.
s=base(5,'03  /  任务继续','任务中断后，可选择接着走还是重新开始','新增进度保存和选择弹窗，避免每次都从第一个航点重新出发。')
shape(s,.65,2.4,6.1,4.25,GREY)
txt(s,.96,2.67,5.5,.42,'点击“开始导航”后的选项',20,INK,True)
options=[('继续刚才任务','执行剩余航点，前往原终点',TEAL,MINT),('从头执行','重新经过全部航点',BLUE,SOFTBLUE),('仅到终点','跳过航点，前往当前终点',INK,W),('取消','保持停车',MUT,W)]
for i,(h,b,c,bg) in enumerate(options):
    y=3.29+i*.72
    shape(s,.96,y,5.48,.59,bg,LINE,MSO_SHAPE.ROUNDED_RECTANGLE)
    txt(s,1.13,y+.13,2.02,.33,h,16,c,True)
    txt(s,3.22,y+.16,3.0,.28,b,12,MUT)
item(s,7.13,2.65,1,'自动保存进度','记录已完成目标，刷新页面\n或服务重启后仍可读取。',5.25)
item(s,7.13,4.12,2,'按原顺序继续','8 字交叉处按任务进度判断，\n避免跳到距离最近的错误航点。',5.25)
pill(s,7.68,5.76,4.58,'由用户确认后继续，不自动发车',TEAL,MINT)
note(s,'来源：11月11日17:32工作结果及mission.py、simple.js。检查点持久化mission.json，依据Nav2剩余目标数推进原序列，不按最近点推断。继续使用保存的原终点和朝向；地图约束或航点改变时拒绝继续旧任务。旧版没有可靠进度记录时需用户确认下一目标。服务重启仅恢复待继续状态。页面是按当前功能重绘的示意，非实时截图。弹窗、任务恢复逻辑已有回归验证，实车整程续跑仍待复测。')

# 06 — Hardware and odometry.
s=base(6,'04  /  底盘与定位','区分短时数据延迟和设备真正掉线','排查发现 USB 链路自行断连，CAN 和 GPS 随后丢失。')
shape(s,.65,2.43,5.87,3.27,PALE)
txt(s,.94,2.71,5.24,.49,'设备掉线：立即停止任务',23,ORANGE,True)
txt(s,.96,3.47,5.18,1.11,'滤波器仍可能输出预测位置，\n页面“还有定位”不代表\n底盘和 GPS 已恢复。',19,INK)
txt(s,.96,4.95,5.17,.48,'新增原始底盘反馈的独立检查。',17,ORANGE,True)
shape(s,6.8,2.43,5.87,3.27,MINT)
txt(s,7.09,2.71,5.25,.49,'短时延迟：先停，再确认恢复',23,TEAL,True)
txt(s,7.11,3.47,5.16,1.11,'仅在原始底盘反馈正常时，\n允许滤波数据短暂等待；\n连续收到有效反馈后再恢复。',19,INK)
txt(s,7.11,4.95,5.17,.48,'持续断流仍取消，避免带故障续跑。',17,TEAL,True)
banner(s,'处理线缆后：静止监测约 63 秒未中断；行驶振动下仍需复测。',size=19)
note(s,'来源：11月10日16:06工作结果。内核USB -71错误，CAN/GPS消失；用户确认未主动拔插，后重新插紧或更换线缆。静止监测约63秒、240次采样无反馈中断，但11月11日16:48:31后USB又反复断连，因此不能声称硬件故障已根治。代码对/odom原始底盘数据独立看门狗；超过0.5秒或无效则停止取消，EKF预测不能解除。仅原始输入正常时，滤波/odometry/local短时延迟进入有限等待，连续3帧恢复，需新控制指令；达到持续超时门槛则取消。另修复基于暂停起点导致0.25秒误取消的问题。')

# 07 — No lidar mode.
s=base(7,'05  /  无雷达导航','完成无雷达模式，不再卡在等待扫描数据','定位改用底盘轮速与双天线 RTK，保留地图和底盘状态检查。')
for i,(h,b,c,bg) in enumerate([('原先卡在哪里','驱动进程还在\n但没有有效雷达数据\n规划一直等待地图更新',ORANGE,PALE),('本周怎样调整','解除雷达数据依赖\n启用无雷达定位配置\n园区离线模式默认使用',TEAL,MINT),('继续保留的检查','地图禁行区与安全边距\n定位新鲜度及路径偏离\n底盘反馈与急停状态',BLUE,SOFTBLUE)]):
    x=.65+i*4.1
    shape(s,x,2.45,3.83,2.79,bg)
    txt(s,x+.25,2.74,3.34,.5,h,23,c,True)
    txt(s,x+.25,3.64,3.34,1.25,b,18,INK)
shape(s,.65,5.55,12.03,.64,MINT)
txt(s,.94,5.72,11.44,.36,'静止规划验证：4 个航点 + 终点，约 0.23 秒完成规划。',20,TEAL,True)
txt(s,.78,6.4,11.88,.3,'使用边界：无雷达模式不能检测临时出现的行人或障碍物。',15,ORANGE,True)
note(s,'来源：11月13日15:03、15:15工作结果及gps_navigation.launch.py、ekf_*_no_lidar.yaml、sensors.py。当时6秒订阅点云、IMU、scan均0消息，持续等scan超过7分钟。用户明确要求取消必须接雷达才能行驶，随后部署无雷达模式；定位采用轮速与双天线RTK航向，不再依赖雷达IMU角速度。四航点加终点约0.23秒是当时本机的一次规划观测，车辆未移动，不能视为平均性能或实际路线完成。离线园区启动默认无雷达，其他模式按参数选择。无雷达模式不具备临时动态障碍检测能力，保留地图静态约束和状态保护。')

# 08 — Evidence and next work.
s=base(8,'验证结果与下一步','软件改动已部署，下一步完成整条路线实车复测','本周重点解决了终点绕圈、恢复失败、任务进度和无雷达运行问题。')
for i,(v,h,b,c,bg) in enumerate([('144 项','回归检查通过','截至 11 月 13 日修复后',TEAL,MINT),('0 次','转角仿真碰撞事件','暂停点 → 航点 4 → 终点',BLUE,SOFTBLUE),('待复测','整条路线实车行驶','本周记录尚未确认全程通过',ORANGE,PALE)]):
    x=.65+i*4.1
    shape(s,x,2.45,3.83,1.67,bg)
    txt(s,x+.25,2.61,3.3,.57,v,30,c,True)
    txt(s,x+.25,3.31,3.32,.35,h,18,INK,True)
    txt(s,x+.25,3.81,3.32,.24,b,11,MUT)
nexts=[('01','先查连接稳定性','检查 USB 供电、线缆与 CAN/GPS，覆盖行驶振动。',TEAL),('02','再跑完整路线','复测直线末段、S 弯 / 8 字及中断后继续任务。',BLUE),('03','保留现场证据','记录轨迹、停车原因和碰撞现场，核对地图边界。',TEAL)]
for i,(n,h,b,c) in enumerate(nexts):
    y=4.48+i*.71
    shape(s,.65,y,12.03,.59,GREY)
    txt(s,.93,y+.12,.62,.34,n,19,c,True)
    txt(s,1.79,y+.12,2.75,.35,h,18,INK,True)
    txt(s,4.66,y+.15,7.65,.35,b,15,MUT)
note(s,'144项回归通过和0碰撞仿真取自11月13日15:34最终工作结果；本次制作报告不重新执行车辆测试。0碰撞限于该次暂停点至航点4再至终点的隔离仿真，不代表整程实车成功。此前111项及132项是不同阶段同套回归，不能与144相加。上周有实车尝试与报错记录，但最后修复后车辆未移动，缺少完整S弯/8字、终点停车及恢复续跑的最终道路验收。下步计划为建议安排。')

name='松灵无人车_本周进度汇报_20261113'
R.save(OUT/(name+'.pptx'))
lines=['# 松灵无人车上周工作汇报','', '周期：2026 年 11 月 9 日—11 月 13 日。共 8 页，16:9。',
       '样式沿用 2026-11-06 汇报：白底、青绿重点色、深蓝封面信息块、页脚及页码；正文和示意图均可编辑，每页附讲解与依据备注。','']
for i,slide in enumerate(R.slides,1):
    texts=[sh.text for sh in slide.shapes if sh.has_text_frame]
    lines.extend([f'## 第 {i} 页', '', *texts, '', '讲解与依据：'+slide.notes_slide.notes_text_frame.text, ''])
(OUT/'汇报说明.md').write_text('\n'.join(lines),encoding='utf-8')
print(OUT/(name+'.pptx'))

