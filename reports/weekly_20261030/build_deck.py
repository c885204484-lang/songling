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
 q=s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h));q.fill.solid();q.fill.fore_color.rgb=RGBColor.from_string(c);q.line.fill.background();return q
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

for src,dst in [('Screenshot from 2026-10-27 14-54-26.png','initial_issue.png'),('Screenshot from 2026-10-28 15-41-06.png','tracking_issue.png')]:
 shutil.copy2(Path('/home/nvidia/Pictures/Screenshots')/src,OUT/'assets'/dst)
report=json.loads(Path('/home/nvidia/songling/rtk_delay_report.json').read_text());(OUT/'assets/rtk_delay_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))

s=base(1,'本周工作汇报','松灵无人车 · RTK 定位与实车导航联调','统计周期：2026.10.26—10.30  |  依据：本周联调记录、诊断报告与代码提交')
rect(s,.65,2.52,7.6,3.98,NAVY);text(s,.98,2.83,6.9,.35,'本周核心进展',14,'90D6D0',True)
text(s,.98,3.48,6.9,1.65,'从定位延迟排查\n推进到实车到达验证',34,W,True)
text(s,.98,5.48,6.8,.67,'完成 GNSS 输出精简、导航策略优化、CAN 恢复及路径保护同步修复。',17,'CFDFE5')
metric(s,8.55,2.52,4.12,'29 ms','修复后 GNSS 延迟中位数','10/27 静止采集')
metric(s,8.55,4.48,4.12,'14.8 m','实车目标导航成功到达','起终点直线距离 · 单次验证')
note(s,'本周承接上周地图与导航工作台，重点解决实车联调问题。29ms 为 GNSS 测量时刻到 ROS 接收的时间差中位数。14.8m 是起终点直线距离，并非累计行驶里程。10月28日路径保护修复晚于此次实车成功验证，须单独进行实车复测。')

s=base(2,'本周完成四项关键工作','先确认差分解状态，再解决延迟、任务失败与路径保护问题。','来源：10/26—10/28 联调记录；rtk_delay_report.json；提交 0792ba4')
for i,(tag,title,body) in enumerate([
 ('01 / 设备与定位','确认 RTK 固定解','完成 EP-D200 连接排查\n以原始 GGA 确认 gps_qual=4\n建立定位与运动数据采集'),
 ('02 / 数据时效','消除秒级定位延迟','定位到 GNSS 串口输出拥堵\n精简 GSV 输出并保存配置\n延迟降至约 29 毫秒'),
 ('03 / 导航闭环','完成一次实车到达','优化接近终点时的路径复用\n恢复 USB-CAN 与里程计\n约 14.8 米目标成功到达'),
 ('04 / 跟踪保护','同步重规划参考路径','修复新旧参考路径不一致\n保留 0.75 米偏离保护\n完成软件与独立仿真验证')]):card(s,.65+i*3.06,2.55,2.84,3.8,tag,title,body)
note(s,'10月26日完成设备排查；27日完成差分链路确认、GNSS延迟修复、CAN恢复和实车到达；28日修复参考路径同步问题并更新工作台。未将上周地图工作台建设列作本周新增成果。')

s=base(3,'定位排查：从“账号接入”核实到 RTK 固定解','将地图显示偏移、定位质量和任务停止原因分别核查。','来源：10/26 DTU 排查、10/27 GGA 采集记录；左图为修复前现场截图')
pic(s,'initial_issue.png',.65,2.55,6.65,3.77)
text(s,7.65,2.55,4.9,.42,'先查链路，再判断精度',22,TEAL,True)
text(s,7.65,3.22,4.9,2.2,'设备：完成 EP-D200 USB 连接排查，尚不能据此判定硬件损坏。\n定位：初期水平标准差约 1.8 米；后续 GGA 持续为 4，确认 RTK 固定解。',17)
rect(s,7.45,5.45,5.22,.94,LIGHT);text(s,7.66,5.62,4.8,.68,'地图约 3 米显示偏移仍需现场配准核验；固定解不等于底图已准确对齐。',15,TEAL,True)
note(s,'用户报告实际车位较标记偏东北约3m。初期 /gps/fix status=0，水平标准差约1.75—1.88m；接入CORS后 status=2，标准差约1.26cm，最终以原始GGA gps_qual=4严格确认固定解。标准差是接收机上报指标，不代表已完成独立绝对精度验证。DTU硬件故障未被证实。')

s=base(4,'核心突破：GNSS 延迟从 2.87 秒降至 29 毫秒','原始数据存在秒级积压；精简接收机输出后，定位时效显著改善。','来源：rtk_delay_report.json；10/27 串口与时钟采集记录；数据为本机观测')
text(s,.72,2.6,7,.4,'GNSS 测量时间 → 电脑接收时间（中位数）',17,INK,True)
text(s,.72,3.42,1.4,.4,'修复前',18);rect(s,2.2,3.43,5.65,.43,ORANGE);text(s,8.05,3.34,1.8,.55,'2.87 s',25,ORANGE,True)
text(s,.72,4.45,1.4,.4,'修复后',18);rect(s,2.2,4.46,.057,.43,TEAL);text(s,2.5,4.37,3,.55,'0.029 s',25,TEAL,True)
text(s,.72,5.45,7.8,.68,'关闭当前输出口 GSV 卫星列表报文，并确认保存接收机配置。',18)
metric(s,9.68,2.63,2.99,'≈99%','延迟降幅','2.87 s → 0.029 s')
rect(s,9.68,4.55,2.99,1.8,GREY);text(s,9.88,4.76,2.58,1.4,'115200 波特率\n约 10.5 KB/s 输出\nGSV 占约 55%',17)
note(s,'时间基准：修复前静止时间采集的时间差中位数约2.87s。初次只修改驱动后仍约2.82s，表明主要延迟未消除。绕过ROS的原始串口数据仍滞后约2.7s，输出约10.5KB/s，GSV占约55%。执行UNLOG GPGSV并保存后，原始中位数0.027277946s，重启后ROS中位数0.029123425s，最大0.103310347s。固定解持续保持。降幅约98.99%。两条柱形为线性同比例示意。')

s=base(5,'驱动改进：处理积压报文，补全时间解析','将接收端抗积压能力和观测工具一并补齐，便于后续定位同类故障。','来源：src/nmea_navsat_driver；rtk_navigation_capture.py；提交 0792ba4')
for i,(a,b,c) in enumerate([
 ('读取方式','逐行读取 → 分块读取','按串口缓冲量读取；减少高频流下逐字节读取开销。'),
 ('报文处理','保留最新完整有效报文','合并同类积压数据；处理分段、噪声、校验错误和超长输入。'),
 ('时间解析','保留小数秒与跨日校正','恢复亚秒级测量时间；选择临近日期，便于核对真实延迟。')]):card(s,.65+i*4.08,2.6,3.85,2.92,a,b,c)
rect(s,.65,5.85,12.02,.65,LIGHT);text(s,.88,5.99,11.55,.4,'验证：新增 6 项串口与时间测试通过；主要延迟通过接收机输出精简消除。',17,TEAL,True)
note(s,'提交0792ba4：NMEABuffer按GGA/RMC/GST/HDT/VTG类型保留最新校验有效报文并保序；pending最大65536字节。串口timeout改为0.2s，分块read。convert_time保留小数秒并做最近日期修正。这些改进本身未消除最初约3秒延迟，不能将主要效果归因于仅修改读取方式。test_serial_buffer.py含3个普通用例和3个参数化时间用例，共6项。')

s=base(6,'导航恢复：优化终点附近规划，修复 CAN 断连恢复','分别处理规划失败与底盘链路故障，避免将不同问题归为定位误差。','来源：offline_to_pose.xml；can_hotplug/；10/27 联调与恢复记录')
card(s,.65,2.57,5.86,3.9,'规划策略','有效路径继续跟踪','现象：距终点约 1.4 米时，重新搜索路径失败。\n修改：每秒检查路径有效性；目标未变且路径有效时复用。\n触发重算：路径失效或目标更新。')
card(s,6.8,2.57,5.87,3.9,'底盘链路','USB-CAN 恢复与自动激活','现象：适配器重新枚举，can0 DOWN，底盘反馈中断。\n处理：安装热插拔规则及 500 kbit/s 自动激活服务。\n恢复：重载导航，清除断流期里程计外推状态。')
note(s,'10月27日延迟修复后的第一次动态复测，先在距终点约1.4m处规划失败，约一分钟后才发生USB-CAN重枚举，不将两者混为同一直接原因。行为树增加GlobalUpdatedGoal/IsPathValid复用逻辑。/etc/udev/rules.d/80-songling-usb-can.rules和/etc/systemd/system/songling-usb-can.service在本次制作时确认存在。恢复后CAN、里程计和导航模块状态正常；未声称已完成长期热插拔可靠性验收。')

s=base(7,'实车验证：目标导航成功到达，停车状态正常','10 月 27 日完成一次完整任务；日志与用户现场反馈一致。','来源：rtk_delay_report.json → final_verification；10/27 用户反馈“已到达”')
metric(s,.65,2.55,3.82,'14.8 m','起终点直线距离','单次实车任务')
metric(s,4.75,2.55,3.82,'33.38 s','任务用时','Nav2 返回成功')
metric(s,8.85,2.55,3.82,'0 m/s','到达后底盘速度','CAN 与里程计状态正常')
rect(s,.65,4.65,7.7,1.77,NAVY);text(s,.95,4.88,7.1,.6,'“Goal succeeded / Reached the goal”',25,W,True);text(s,.95,5.65,7.1,.45,'用户现场确认：界面显示“已到达”。',18,'CDE1E6')
text(s,8.85,4.73,3.82,1.7,'此前动态复测：\n最新路径偏差中位数约 2.9 cm，最大约 20.4 cm。\n该指标属于此前一次采样。',15,MUTE)
note(s,'final_verification起点(-0.65,-0.26)，终点(-1.82,-15.0)，直线距离14.78636196m，用时33.38s，Nav2状态4成功，到达后车速0，底盘和里程计ready。此前dynamic_navigation_retest的GNSS时间差中位数0.0295248s，距最新路径误差中位数0.0288937m，最大0.203514m。这些跟踪误差不属于最终成功任务的独立测量，也不是绝对定位精度。一次成功不外推为长期可靠性结论。')

s=base(8,'后续修复：让控制器与停车保护使用同一参考路径','10 月 28 日处理重规划后的误停；保留原有 0.75 米偏离保护。','来源：ros_bridge.py、app.js、test_offline_velocity_gate.py；左图为 10/28 修复前截图')
pic(s,'tracking_issue.png',.65,2.55,6.32,3.57)
text(s,7.35,2.53,5.2,.45,'问题：控制器换新路径，保护仍看旧路径',20,ORANGE,True)
text(s,7.35,3.25,5.15,2.2,'切换前：先确认未偏离旧路径，且定位新鲜、起终点匹配。\n切换后：同步跟踪参考，等待新的速度指令。\n界面：显示同一参考路径，失败后保留。',17)
rect(s,.65,6.25,12.02,.45,LIGHT);text(s,.85,6.31,11.6,.32,'实际偏离、故障或取消后，重规划不会自动放行；软件与仿真通过，实车复测待完成。',14,TEAL,True)
note(s,'提交0792ba4。on_path切换前调用tracking_block_reason检查旧参考；要求pose不超过0.5s、新路径起点距车不超过0.75m、终点距任务目标不超过0.5m，且处于有效任务且无锁存故障。更新tracking_path并将cmd_seen清零，等待新控制命令。status返回tracking_path或path；前端增加取消中/任务失败/已取消状态路径显示。现有0.75m偏离阈值保留。10/28对话记录报告独立仿真中弯道和航点任务到达、错误转向停车。修复后的实车行驶效果未记录为已完成。')

s=base(9,'验证与交付：形成可复用的排查、修复和回归资产','代码、配置、采集工具与诊断报告均已沉淀，便于后续复现与维护。','来源：10/28 验证记录；0792ba4（9 文件，+199 / −26）；10/30 本次复核')
for i,(v,l,d) in enumerate([('90 项','10/28 软件测试通过','含 63 项门控 + 27 项地图等测试'),('独立仿真','导航到达与错误转向停车','弯道、航点及故障注入场景'),('6 项','新增串口与时间测试','积压、分段、噪声、小数秒与跨日')]):
 metric(s,.65+i*4.08,2.55,3.85,v,l,d)
text(s,.75,4.64,5.65,.4,'本周交付',21,TEAL,True)
text(s,.75,5.23,5.65,1.25,'GNSS 采集、串口检查与输出精简脚本\nCAN 热插拔恢复规则与导航恢复脚本\n导航行为树、路径同步及界面修复',17)
text(s,7.05,4.64,5.52,.4,'代码与复核口径',21,TEAL,True)
text(s,7.05,5.23,5.52,1.3,'代码已归档至提交 0792ba4。\n本次本地复核：89 项通过；2 项 HTTP 测试因环境禁止开端口未完成。',17)
note(s,'历史验证口径来自10/28联调记录：63项门控测试、另27项地图工作台等测试，合计90项，且独立仿真通过。串口6项为10/27新增，勿与90项相加声称为同批96项。本次10/30复核选择test_serial_buffer.py、test_offline_nav.py和test_offline_velocity_gate.py，结果89通过、2个HTTP测试因PermissionError禁止创建socket而未完成；并非重现同一90项组合。申请扩大本地端口访问的调用被中断，未宣称本次全部通过。本次复核未控制实车。')

s=base(10,'下周重点：把单次到达扩展为可重复验证','继续围绕地图、定位、控制与底盘恢复建立完整验收记录。','以下为建议计划，尚未作为已完成成果；截至 2026.10.30')
rows=[('01','实车复测路径同步修复','重复弯道、重规划、取消再发任务；记录到达、误停及保护触发原因。'),('02','核验地图与现场位置','在固定解稳定后使用现场控制点复核约 3 米显示偏移，保存配准误差。'),('03','验证恢复与定位稳定性','复测 CAN 重连、GNSS 重启和长时间运行；记录时间差及解状态。')]
for i,(n,t,b) in enumerate(rows):
 y=2.57+i*1.17;rect(s,.65,y,.67,.67,TEAL);text(s,.79,y+.1,.45,.4,n,19,W,True);text(s,1.59,y+.02,10.7,.4,t,21,INK,True);text(s,1.59,y+.56,10.7,.5,b,16,MUTE)
rect(s,.65,6.22,12.02,.48,NAVY);text(s,.9,6.29,11.5,.32,'本周阶段成果：RTK 数据恢复实时性，实车完成一次到达，重规划保护逻辑进一步完善。',14,W,True)
note(s,'建议以成功率、路径偏差、端到端定位时间差、RTK解状态和CAN恢复时间作为后续验收记录项。当前不填未经验证的成功率或误差承诺。地图实地配准与10/28修复后实车复测为尚未完成工作。')

name='松灵无人车_本周工作汇报_20261030'
R.core_properties.title='松灵无人车本周工作汇报｜2026.10.26—10.30'
R.core_properties.subject='RTK定位、GNSS延迟、CAN恢复与实车导航验证'
R.core_properties.author='松灵无人车项目组'
R.save(OUT/(name+'.pptx'))
print(OUT/(name+'.pptx'))
