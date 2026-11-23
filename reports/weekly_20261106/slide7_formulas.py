"""Editable formula layout for slide 7 of the weekly deck."""
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.xmlchemy import OxmlElement

TITLE='动态安全距离如何算出来？'
SUBTITLE='先算不能缩的下限，再按通道宽度保留部分余量；左右两侧分别计算。'
FONT='Noto Sans CJK SC'
INK='172E3C'; MUT='637888'; TEAL='087F83'; BLUE='3479B8'
MINT='E8F5F2'; SOFTBLUE='EAF1F9'; GREY='F1F5F7'; WHITE='FFFFFF'

def box(s,x,y,w,h,color):
    q=s.shapes.add_shape(MSO_SHAPE.RECTANGLE,Inches(x),Inches(y),Inches(w),Inches(h))
    q.fill.solid();q.fill.fore_color.rgb=RGBColor.from_string(color);q.line.fill.background()
    q._element.spPr.append(OxmlElement('a:effectLst'))
    return q

def text(s,x,y,w,h,t,size=18,color=INK,bold=False):
    q=s.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
    tf=q.text_frame;tf.word_wrap=True
    tf.margin_left=tf.margin_right=tf.margin_top=tf.margin_bottom=0
    for i,line in enumerate(t.split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph()
        p.space_after=Pt(3);p.line_spacing=1.08
        r=p.add_run();r.text=line;r.font.name=FONT;r.font.size=Pt(size)
        r.font.bold=bold;r.font.color.rgb=RGBColor.from_string(color)
        ea=OxmlElement('a:ea');ea.set('typeface',FONT);r._r.get_or_add_rPr().append(ea)
    return q

def draw_slide7(s):
    box(s,.65,2.40,6.40,1.17,MINT)
    text(s,.88,2.53,5.95,.28,'① 算出每侧不能缩的下限',13,TEAL,True)
    text(s,.9,2.87,5.95,.43,'lᵢ = Hᵢ + eᵢ + cᵢ',23,INK,True)
    text(s,.9,3.32,5.95,.22,'Hᵢ：含姿态误差的车身占用；eᵢ：其余误差；cᵢ：基本净距',10.5,MUT)

    box(s,.65,3.70,6.40,.96,SOFTBLUE)
    text(s,.88,3.81,5.95,.28,'② 算出默认距离中的额外余量',13,BLUE,True)
    text(s,.9,4.12,5.95,.40,'qᵢ = max(0, d⁰ᵢ − lᵢ)',22,INK,True)
    text(s,.9,4.47,5.95,.20,'d⁰ᵢ：默认中心安全距离；qᵢ：可调整的额外余量',10.5,MUT)

    box(s,.65,4.79,6.40,1.01,MINT)
    text(s,.88,4.90,5.95,.28,'③ 按保留系数 λ 得到动态距离',13,TEAL,True)
    text(s,.9,5.21,5.95,.40,'dᵢ = lᵢ + λqᵢ',23,TEAL,True)
    text(s,.9,5.60,5.95,.20,'λ = 1：全部保留额外余量；λ = 0：仅保留硬下限',10.5,MUT)

    box(s,7.28,2.40,5.40,3.40,GREY)
    text(s,7.53,2.55,4.90,.32,'算例：0.90 米直通道、两侧对称',16,INK,True)
    text(s,7.53,3.02,4.90,.31,'车宽 B = 0.64 m；默认距离 d⁰ = 0.65 m',13,MUT)
    text(s,7.53,3.42,4.90,.35,'l = 0.64 / 2 + 0.08 = 0.40 m',17,INK,True)
    text(s,7.53,3.82,4.90,.35,'q = 0.65 − 0.40 = 0.25 m',17,INK,True)
    text(s,7.53,4.23,4.90,.26,'留出 2η = 0.04 m 的中心可选区间：',12,MUT)
    text(s,7.53,4.55,4.90,.31,'0.90 − 2 × (0.40 + 0.25λ) ≥ 0.04',15,INK)
    text(s,7.53,4.90,4.90,.29,'因此 λ ≤ 0.12，本例取 λ = 0.12',14,BLUE,True)
    box(s,7.48,5.31,5.0,.37,TEAL)
    text(s,7.60,5.35,4.77,.29,'d = 0.40 + 0.12 × 0.25 = 0.43 m',17,WHITE,True)

    box(s,.65,6.03,12.03,.65,MINT)
    text(s,.9,6.14,11.55,.30,'选 λ 的宽度条件：W − l左 − l右 − λ(q左 + q右) ≥ 2η，且 0 ≤ λ ≤ 1',16,TEAL,True)
    text(s,.90,6.50,11.55,.18,'W 为通道净宽，η 为中心位置预留半宽；从较大 λ 开始检查完整通行和停车，通过后才采用。',10.5,TEAL)
    text(s,.90,6.77,11.55,.18,'d 为车中心到边界的距离；0.08 m 是算例假设预算，需实测标定；算例结果不等于实车通行许可。',9.5,MUT)
    s.notes_slide.notes_text_frame.text=(
        '本页按用户要求加入动态安全距离计算公式。符号i表示左或右侧，l为不可压缩中心距离，'
        'H为考虑姿态及航向误差的车身方向占用，e合并其余有效误差上界，c为基本净距；'
        '同一误差不能重复计入。对正矩形车名义半宽为B/2，转弯时需考虑车长和方向占用。'
        'q_i=max(0,d0_i-l_i)，d_i=l_i+lambda*q_i；若下限大于默认距离，q为零并保留较大的下限。'
        '平行通道局部候选需满足W-l左-l右-lambda(q左+q右)>=2eta。'
        '示例W=0.90米、B=0.64米、d0=0.65米，已将示例航向扩展、其余误差和基本净距合计假设为0.08米，'
        '故l=0.40米、q=0.25米；eta=0.02米时lambda<=0.12；取上限得两侧d=0.43米，'
        '中心可选区间宽0.90-2*0.43=0.04米。0.08米是稿件中的假设输入，不是现场实测参数。'
        '宽度条件只筛选候选，需从较大lambda开始验证整条状态链、扫掠区域、入口对正与停车分支。'
        '校验不通过时尝试其他候选，无解则拒绝进入；硬下限和预留宽度已不足时直接拒绝。'
        '来源：outputs/动态安全距离专利稿/专利正文_可编辑文本.txt，式(5)—(10)与第九节0.90米参数算例。'
    )
