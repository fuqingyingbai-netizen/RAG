"""Read actually retained original-page pixels with the existing local OCR engine."""
from io import BytesIO
import hashlib,json
from .company_evidence import source_body
from company_flow_state import fingerprint


def page_input_fingerprint(source,page,store):
    meta=source.source_metadata or {}
    keys=[i.get('object_key') for i in meta.get('images',[]) if isinstance(i,dict)
        and (i.get('physical_page') or i.get('page'))==page]
    keys+=[meta.get('original_object_key'),source.object_key]
    versions=[]
    for key in dict.fromkeys(k for k in keys if k):
        try:versions.append([key,hashlib.sha256(store.get_bytes(key)).hexdigest()])
        except FileNotFoundError:versions.append([key,'unavailable'])
    return fingerprint(versions)


def read_page_context(source,page,store,*,recognize=None):
    if type(page) is not int or page<1:
        return {'status':'unavailable','reason':'physical_page_not_located','pixels_read':False}
    meta=source.source_metadata or {};payload=None;image=None;kind=''
    images=[i for i in meta.get('images',[]) if isinstance(i,dict) and (i.get('physical_page') or i.get('page'))==page]
    for entry in images:
        key=entry.get('object_key')
        if not key:continue
        try:
            payload=store.get_bytes(key)
            from PIL import Image
            image=Image.open(BytesIO(payload)).convert('RGB');kind='retained_page_image';break
        except (FileNotFoundError,OSError):continue
    pdf=None;pdf_page=None;bitmap=None
    try:
        if image is None:
            for key in (meta.get('original_object_key'),source.object_key):
                if not key:continue
                try:body=store.get_bytes(key)
                except FileNotFoundError:continue
                if not body.startswith(b'%PDF-'):continue
                import pypdfium2
                pdf=pypdfium2.PdfDocument(body)
                if page>len(pdf):continue
                payload=body;pdf_page=pdf[page-1];width,height=pdf_page.get_size()
                bitmap=pdf_page.render(scale=min(2.5,3200/max(width,height)))
                image=bitmap.to_pil().convert('RGB');kind='retained_pdf_page';break
        if image is None:return {'status':'unavailable','reason':'retained_original_pixels_not_available','physical_page':page,'pixels_read':False}
        from company_ocr import _recognize,VERSION
        import numpy as np
        lines=(recognize or _recognize)(np.asarray(image))
        records=[{'box':row[0],'text':str(row[1]),'confidence':float(row[2])} for row in lines if len(row)>=3]
        return {'status':'transcribed' if records else 'unreadable','physical_page':page,'pixels_read':True,
            'mode':'local_ocr_transcription_not_visual_model_review','engine_version':VERSION,'original_kind':kind,
            'original_sha256':hashlib.sha256(payload).hexdigest(),'lines':records,
            'text':'\n'.join(r['text'] for r in records),
            'boundary':'实际原页OCR转录及坐标，置信度不是数值/表格或法律事实已核实；模型仍须检查列关系、主体、期间和单位，不确定处保留缺口。'}
    finally:
        if image is not None:image.close()
        if bitmap is not None:bitmap.close()
        if pdf_page is not None:pdf_page.close()
        if pdf is not None:pdf.close()
