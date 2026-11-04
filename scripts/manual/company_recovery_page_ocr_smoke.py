"""Exercise actual local OCR on retained synthetic page pixels, not company facts."""
import hashlib,json,sys,time
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from report_agents.company_page_context import read_page_context


def main():
    directory=ROOT/'work/page-ocr-smoke';directory.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1200,650),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/simhei.ttf',38)
    draw.multiline_text((60,60),'原页转录能力测试（合成样本）\n姓名：王某    期间：2025年度\n单位：元    本期    上期\n测试字段       0       未知',font=font,fill='black',spacing=25)
    path=directory/'synthetic-page.png';image.save(path);payload=path.read_bytes()
    source=SimpleNamespace(source_metadata={'images':[{'physical_page':1,'object_key':'synthetic-page'}]},object_key=None)
    start=time.monotonic();result=read_page_context(source,1,SimpleNamespace(get_bytes=lambda key:payload))
    outcome={'scope':'Actual RapidOCR engine on retained synthetic pixels; no company page or factual verification claimed',
        'seconds':round(time.monotonic()-start,3),'fixture_sha256':hashlib.sha256(payload).hexdigest(),'result':result}
    (ROOT/'docs/deliverables/company-recovery-20261104/page-ocr-real-smoke.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'pixels_read':result['pixels_read'],'lines':len(result.get('lines',[])),'seconds':outcome['seconds']}))


if __name__=='__main__':main()
