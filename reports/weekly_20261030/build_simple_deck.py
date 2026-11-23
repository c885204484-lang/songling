from pathlib import Path
import json, shutil
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.xmlchemy import OxmlElement

OUT=Path(__file__).parent
R=Presentation(); R.slide_width=Inches(13.333); R.slide_height=Inches(7.5)
W='FFFFFF'; INK='182B39'; MUTE='657684'; TEAL='087E82'; LIGHT='EAF5F4'; GREY='F2F5F7'; ORANGE='D97732'; LINE='DBE4E8'; NAVY='102C3A'
FONT='Noto Sans CJK SC'
def rect(s,x,y,w,h,c):
 q=s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h));q.fill.solid();q.fill.fore_color.rgb=RGBColor.from_string(c);q.line.fill.background();q._element.spPr.append(OxmlElement('a:effectLst'));return q
def text(s,x,y,w,h,t,size=20,c=INK,bold=False):
 q=s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h));f=q.text_frame;f.word_wrap=True
 f.margin_left=f.margin_right=f.margin_top=f.margin_bottom=0
 for i,line in enumerate(t.split('\n')):
  p=f.paragraphs[0] if i==0 else f.add_paragraph();p.space_after=Pt(8)
  r=p.add_run();r.text=line;r.font.name=FONT;r.font.size=Pt(size);r.font.bold=bold;r.font.color.rgb=RGBColor.from_string(c)
  ea=OxmlElement('a:ea');ea.set('typeface',FONT);r._r.get_or_add_rPr().append(ea)
 return q
def base(n,title,sub,source):
 s=R.slides.add_slide(R.slide_layouts[6]);s.background.fill.solid();s.background.fill.fore_color.rgb=RGBColor.from_string(W)
 rect(s,.55,.45,.45,.07,TEAL);text(s,1.12,.32,10,.3,'SONGLING  /  HUNTER SE     ·     周工作汇报  2026.10.26—10.30',10,MUTE)
 text(s,.65,.94,12,.7,title,29,INK,True);text(s,.67,1.76,12,.55,sub,14,MUTE)
 rect(s,.65,6.94,12.02,.012,LINE);text(s,.68,7.07,11.3,.23,source,8,MUTE);text(s,12.15,7.03,.5,.3,f'{n:02}',12,TEAL,True)
 return s
def note(s,t):s.notes_slide.notes_text_frame.text=t
def card(s,x,y,w,h,tag,title,body,c=TEAL):
 rect(s,x,y,w,h,GREY);rect(s,x,y,.045,h,c);text(s,x+.22,y+.18,w-.4,.35,tag,11,c,True);text(s,x+.22,y+.68,w-.4,.65,title,23,INK,True);text(s,x+.22,y+1.48,w-.44,h-1.6,body,16,MUTE)
def metric(s,x,y,w,value,label,caption='',dark=False):
 rect(s,x,y,w,1.65,NAVY if dark else LIGHT);text(s,x+.2,y+.12,w-.4,.65,value,34,W if dark else TEAL,True);text(s,x+.2,y+.85,w-.4,.35,label,15,W if dark else INK,True)
 if caption:text(s,x+.2,y+1.25,w-.4,.3,caption,10,'C2D6DE' if dark else MUTE)
def pic(s,name,x,y,w,h):
 from PIL import Image
 p=OUT/'assets'/name;im=Image.open(p);iw,ih=im.size;k=min(w/iw,h/ih)
 s.shapes.add_picture(str(p), Inches(x+(w-iw*k)/2), Inches(y+(h-ih*k)/2),width=Inches(iw*k),height=Inches(ih*k))

def lines(s,x,y,w,items):
 for i,t in enumerate(items):
  rect(s,x,y+i*.89+.13,.09,.09,TEAL)
  text(s,x+.3,y+i*.89,w-.3,.72,t,21)

s=base(1,'松灵无人车 · 本周工作汇报','2026 年 10 月 26 日—30 日','本周重点：定位改善、导航修复与实车测试')
rect(s,.65,2.55,12.02,3.88,NAVY)
text(s,1.05,3.03,10.9,1.25,'解决定位延迟\n完成一次实车导航到达',35,W,True)
text(s,1.08,5.15,10.8,.6,'定位数据更及时，导航运行进一步改善。',23,'CCE3E6')
note(s,'本周结论依据10/26—10/28联调记录、rtk_delay_report.json和提交0792ba4。一次实车成功发生在10/27；10/28路径同步修复另经软件与仿真验证，仍待实车复测。')

s=base(2,'本周主要完成三项工作','围绕“让小车顺利完成导航”开展联调。','工作内容：定位链路、导航功能、实车验证')
for i,(tag,title,body) in enumerate([
 ('01','改善定位','确认 RTK 固定解\n解决定位数据延迟'),
 ('02','修复导航问题','优化终点附近规划\n恢复底盘通信'),
 ('03','开展验证','完成一次实车到达\n修复路径保护误停')]):
 x=.65+i*4.08
 rect(s,x,2.7,3.85,3.6,GREY)
 text(s,x+.27,2.98,3.3,.5,tag,25,TEAL,True)
 text(s,x+.27,3.78,3.3,.55,title,27,INK,True)
 text(s,x+.27,4.72,3.3,1.15,body,21,MUTE)
note(s,'10/26完成DTU连接排查；10/27确认固定解，修复GNSS输出积压、终点重规划与CAN恢复，并完成一次实车到达；10/28修复重规划与停车保护参考不一致。')

s=base(3,'定位链路：确认 RTK 已生效','从设备连接排查，推进到固定解确认。','左图：10/27 联调现场，修复前界面')
pic(s,'initial_issue.png',.65,2.55,6.6,3.75)
lines(s,7.65,2.88,4.92,['完成 DTU 连接排查','确认差分定位正常生效','原始数据确认 RTK 固定解'])
note(s,'设备型号EP-D200，USB连接；硬件损坏未被证实。原始GGA gps_qual=4确认固定解。仍不能将固定解等同于底图配准完成，现场约3米显示偏移尚待控制点核验。')

s=base(4,'定位延迟明显降低','精简接收机输出，减少数据积压。','指标：GNSS 数据接收延迟中位数；10/27 本机采集')
metric(s,.65,2.75,5.55,'2.87 秒','修复前','定位数据存在明显滞后')
text(s,6.36,3.18,.7,.6,'→',32,TEAL,True)
metric(s,7.12,2.75,5.55,'29 毫秒','修复后','定位数据更及时')
rect(s,.65,5.12,12.02,1.08,LIGHT)
text(s,.98,5.39,11.3,.6,'完成接收机配置调整和驱动改进，并保存相关配置。',23,TEAL,True)
note(s,'修复前静止时钟采集中位数约2.87秒。关闭当前串口GSV输出并保存后，重启后ROS延迟中位数0.029123425秒，最大0.103310347秒。驱动增加分块读取、同类报文去积压、小数秒和跨日解析；仅修改驱动未消除主要延迟。数据为本机观测。来源rtk_delay_report.json及10/27采集。')

s=base(5,'修复影响导航的两个问题','针对任务失败和底盘断连分别处理。','完成：规划策略优化、底盘通信恢复')
for x,title,problem,fix in [
 (.65,'终点附近规划失败','接近终点时，任务提前结束。','优化规划策略，继续跟踪有效路径。'),
 (6.8,'底盘通信中断','USB-CAN 断连后，反馈丢失。','恢复通信，并加入重连自动激活。')]:
 rect(s,x,2.65,5.87,3.65,GREY)
 text(s,x+.3,3.02,5.25,.6,title,26,TEAL,True)
 text(s,x+.3,4.05,5.25,.85,problem,21)
 text(s,x+.3,5.13,5.25,.85,fix,21)
note(s,'10/27在距终点约1.4米处重规划失败，后另发生USB-CAN重新枚举导致can0 DOWN。修改行为树：目标未变且现有路径有效时复用，失效或目标更新再规划。安装USB-CAN热插拔规则与服务，重载导航恢复里程计。长期恢复可靠性尚未作为完成验收。')

s=base(6,'实车测试：成功到达目标','10 月 27 日，完成一次完整导航任务。','来源：实车日志与现场反馈；距离为起终点直线距离')
metric(s,.65,2.65,3.82,'约 14.8 米','目标距离')
metric(s,4.75,2.65,3.82,'约 33 秒','任务用时')
metric(s,8.85,2.65,3.82,'0 m/s','到达后车速')
rect(s,.65,4.9,12.02,1.35,NAVY)
text(s,1,5.22,11.3,.66,'界面显示“已到达”，底盘与里程计状态正常。',26,W,True)
note(s,'来源rtk_delay_report.json final_verification：起终点直线距离14.7863619596m、耗时33.38s、Nav2状态4成功，到达后车速0，chassis_ready和odometry_ready为true。此次为单次实车成功，不能外推为长期可靠性验证完成。')

s=base(7,'进一步修复路径保护误停','10 月 28 日，让导航控制与停车保护使用同一条路径。','验证状态：软件与仿真通过，修复后的实车效果待复测')
pic(s,'tracking_issue.png',.65,2.55,6.6,3.75)
lines(s,7.65,2.88,4.92,['同步更新保护参考路径','保留偏离路径停车功能','失败后保留路径显示'])
note(s,'原问题：控制器跟随新规划路径，保护仍参考首条路径。修复先验证未偏离旧路径，再校验新鲜定位、起终点与任务匹配，切换后等新控制命令；保留0.75m偏离保护。10/28记录63项门控及27项地图等测试通过，并完成独立导航和错误转向停车仿真。此处左图为修复前截图。未将10/27成功任务作为10/28修复后的实车验证。')

s=base(8,'下周工作计划（暂定）','简化 UI 界面，并开展测试。','计划状态：暂定，后续根据测试结果调整')
rect(s,.65,2.65,5.86,3.65,LIGHT)
text(s,.98,3.02,5.2,.6,'01  简化 UI 界面',28,TEAL,True)
lines(s,1,4.15,5.1,['精简页面信息与操作入口','突出常用功能和任务状态'])
rect(s,6.8,2.65,5.87,3.65,GREY)
text(s,7.13,3.02,5.2,.6,'02  测试与调整',28,TEAL,True)
lines(s,7.15,4.15,5.1,['测试简化后的操作流程','检查导航功能并优化问题'])
note(s,'用户明确指定：下周工作目前暂定为简化UI界面并测试。页面信息精简、常用功能突出、操作流程与导航功能测试是对该计划的简要展开，尚未执行。')

name='松灵无人车_本周工作汇报_20261030_简化版'
R.core_properties.title='松灵无人车本周工作汇报｜8页简化版'
R.core_properties.subject='本周成果与下周UI简化测试计划'
R.core_properties.author='松灵无人车项目组'
assert len(R.slides)==8
R.save(OUT/(name+'.pptx'))
print(OUT/(name+'.pptx'))

