from pathlib import Path
from pptx import Presentation
from pptx.util import Pt
from slide7_formulas import draw_slide7, TITLE, SUBTITLE

OUT=Path(__file__).resolve().parent
src=OUT/'松灵无人车_本周进度汇报_20261106.pptx'
dst=OUT/'松灵无人车_本周进度汇报_20261106_第7页公式版.pptx'
r=Presentation(src)
assert len(r.slides)==10
before=[s._element.xml for s in r.slides]
s=r.slides[6]
assert s.shapes[6].text=='07'
for q in list(s.shapes)[7:]:
    q._element.getparent().remove(q._element)
for idx,t in [(2,TITLE),(3,SUBTITLE)]:
    p=s.shapes[idx].text_frame.paragraphs[0]
    p.runs[0].text=t
    for run in list(p.runs)[1:]:
        p._p.remove(run._r)
draw_slide7(s)
for i,slide in enumerate(r.slides):
    if i!=6:assert before[i]==slide._element.xml, f'Unexpected change to slide {i+1}'
for q in s.shapes:
    assert q.left>=0 and q.top>=0 and q.left+q.width<=r.slide_width and q.top+q.height<=r.slide_height
r.save(dst)
# Also verify preservation after reloading the saved file.
check=Presentation(dst)
for i,slide in enumerate(check.slides):
    if i!=6:assert before[i]==slide._element.xml
assert abs((.90-.40-.40-.04)/(.25+.25)-.12)<1e-12
assert abs(.40+.12*.25-.43)<1e-12
print(dst)
print('Only slide 7 changed; numerical example verified.')
