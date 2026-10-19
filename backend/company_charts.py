"""Bound explicit employee-score line charts to native PDF geometry.

No interpolation, OCR guess or company-specific coordinates: a reported
number, year, plotted vertex and calibrated axis must agree independently.
"""
import hashlib
import math
import os
import re
from io import BytesIO

from opencc import OpenCC

VERSION='company-survey-vector-chart-v1'
_CC=OpenCC('t2s')
NUMBER=re.compile(r'[-+]?\d+(?:\.\d+)?')
YEAR=re.compile(r'(20\d{2})年?')


def looks_like_survey_chart(text):
    text=_CC.convert(str(text or ''))
    return bool(re.search(r'(?:员工|雇员)[^\n]{0,40}(?:调查分数|满意度|敬业度)[^\n]{0,30}[（(]满分\s*\d+(?:\.\d+)?\s*分[）)]',text)
                and len(set(re.findall(r'20\d{2}年',text)))>=2)


def _center(word):return ((word['x0']+word['x1'])/2,(word['top']+word['bottom'])/2)
def _box(word):return [word[k] for k in ('x0','top','x1','bottom')]


def _caption(words,left,right,top):
    rows=[]
    for w in words:
        x,y=_center(w)
        if not (left<=x<=right and top-100<y<top):continue
        row=next((r for r in rows if abs(r[0]-y)<3),None)
        if row is None:rows.append([y,[w]])
        else:row[1].append(w)
    matches=[]
    for y,row in rows:
        row=sorted(row,key=lambda w:w['x0']);original=' '.join(w['text'] for w in row)
        text=_CC.convert(original)
        if re.search(r'目标|预测|预期|计划|预计|forecast|target|planned',text,re.I):continue
        scale=re.search(r'[（(]满分\s*(\d+(?:\.\d+)?)\s*分[）)]',text)
        if scale and re.search(r'(?:员工|雇员).*(?:调查分数|满意度|敬业度)',text):
            if 0<float(scale[1])<=1000:matches.append((y,original,scale[1],row))
    return max(matches,key=lambda m:m[0]) if matches else None


def _grid(curve,lines,words):
    pts=curve.get('pts') or []
    left,right=pts[0][0],pts[-1][0]
    groups={}
    for line in lines:
        if (abs(line['bottom']-line['top'])>.2 or line['x0']>left+2 or line['x1']<right-2
                or line['top']<curve['top']-150 or line['top']>curve['bottom']+150):continue
        key=(round(line['x0']/3),round(line['x1']/3))
        groups.setdefault(key,[]).append(line)
    candidates=[]
    for lineset in groups.values():
        lineset=sorted(lineset,key=lambda x:x['top'])
        ticks=[]
        for line in lineset:
            near=[w for w in words if NUMBER.fullmatch(w['text'])
                  and line['x0']-65<=w['x1']<=line['x0']+3
                  and abs(_center(w)[1]-line['top'])<=max(4,(w['bottom']-w['top'])*.8)]
            if len(near)!=1:continue
            ticks.append((line['top'],float(near[0]['text']),near[0]))
        if len(ticks)<4:continue
        # Distinct monotonic ticks and an affine axis, including truncated axes.
        if not all(ticks[i][0]<ticks[i+1][0] and ticks[i][1]>ticks[i+1][1] for i in range(len(ticks)-1)):continue
        ys=[t[0] for t in ticks];vs=[t[1] for t in ticks]
        ym,vm=sum(ys)/len(ys),sum(vs)/len(vs)
        variance=sum((y-ym)**2 for y in ys)
        if not variance:continue
        slope=sum((y-ym)*(v-vm) for y,v in zip(ys,vs))/variance
        intercept=vm-slope*ym
        step=min(abs(vs[i+1]-vs[i]) for i in range(len(vs)-1))
        if max(abs(slope*y+intercept-v) for y,v in zip(ys,vs))>max(.01,step*.02):continue
        candidates.append((lineset[0]['x0'],lineset[0]['x1'],min(ys),max(ys),slope,intercept,ticks))
    return candidates[0] if len(candidates)==1 else None


def parse_score_charts(words,curves,lines):
    """Pure geometry adapter shared by real PDFs and adverse-layout tests."""
    candidates=[];observed={}
    for curve in curves:
        pts=curve.get('pts') or []
        if (not curve.get('stroke') or curve.get('fill') or not 2<=len(pts)<=8
                or any(p[0]>=q[0] for p,q in zip(pts,pts[1:]))):continue
        if not all(math.isfinite(v) for point in pts for v in point):continue
        if any(step[0]=='c' for step in curve.get('path') or []):continue
        grid=_grid(curve,lines,words)
        if not grid:continue
        left,right,top,bottom,slope,intercept,ticks=grid
        caption=_caption(words,left,right,top)
        if not caption:continue
        _,title,scale,caption_words=caption
        spacing=min(q[0]-p[0] for p,q in zip(pts,pts[1:]))
        years=sorted([w for w in words if YEAR.fullmatch(w['text'])
                      and bottom<=_center(w)[1]<=bottom+65 and pts[0][0]-spacing*.3<=_center(w)[0]<=pts[-1][0]+spacing*.3],key=lambda w:_center(w)[0])
        if len(years)!=len(pts):continue
        year_values=[int(YEAR.fullmatch(w['text'])[1]) for w in years]
        if any(a>=b for a,b in zip(year_values,year_values[1:])):continue
        if any(abs(_center(w)[0]-point[0])>max(4,spacing*.1) for w,point in zip(years,pts)):continue
        grid_key=tuple(round(x,1) for x in (left,top,right,bottom))
        observed.setdefault(grid_key,set()).add(str((pts,curve.get('stroking_color'))))
        points=[]
        for year,vertex in zip(years,pts):
            predicted=slope*vertex[1]+intercept
            labels=[]
            for word in words:
                if not NUMBER.fullmatch(word['text']):continue
                x,y=_center(word);value=float(word['text'])
                if not 0<=value<=float(scale):continue
                decimals=len(word['text'].partition('.')[2])
                tolerance=max(.01,.5*10**(-decimals))
                if (abs(x-vertex[0])<=max(6,spacing*.15)
                        and abs(y-vertex[1])<=max(12,(word['bottom']-word['top'])*2.6)
                        and abs(predicted-value)<=tolerance):labels.append(word)
            if len(labels)!=1:break
            label=labels[0]
            points.append({'year':YEAR.fullmatch(year['text'])[1],'value':label['text'],
                           'year_label':year['text'],'year_bbox':_box(year),'value_bbox':_box(label),
                           'vertex':list(vertex),'axis_predicted_value':round(predicted,5)})
        if len(points)!=len(pts):continue
        candidates.append({'method':'native_vector_line_chart','caption':title,'score_scale':scale,
            'caption_words':[{'text':w['text'],'bbox':_box(w)} for w in caption_words],
            'chart_bbox':[left,top,right,bottom],'points':points,
            'axis_ticks':[{'value':t[2]['text'],'grid_y':t[0],'label_bbox':_box(t[2])} for t in ticks],
            'axis_slope':slope,'axis_intercept':intercept,'stroke_color':curve.get('stroking_color')})
    # Several series sharing one axis need a verified legend-to-series map.
    grouped={}
    for chart in candidates:
        grouped.setdefault(tuple(round(x,1) for x in chart['chart_bbox']),[]).append(chart)
    result=[]
    for charts in grouped.values():
        signatures={str((c['caption'],c['points'],c['stroke_color'])) for c in charts}
        key=tuple(round(x,1) for x in charts[0]['chart_bbox'])
        if len(signatures)==1 and len(observed[key])==1:result.append(charts[0])
    return result


def extract_survey_charts(payload,pages):
    selected=[p for p in pages if looks_like_survey_chart(p.get('text'))]
    try:maximum=max(1,min(40,int(os.getenv('COMPANY_PDF_CHART_MAX_PAGES','8'))))
    except ValueError:maximum=8
    selected_numbers=[p['page'] for p in selected]
    receipt={'version':VERSION,'processed_pages':[],'unresolved_pages':[],
             'pending_pages':selected_numbers[maximum:],'charts':0,'method':'not_needed'}
    if not selected:return receipt
    source_sha=hashlib.sha256(payload).hexdigest()
    receipt['source_sha256']=source_sha
    try:
        import pdfplumber
        by_page={p['page']:p for p in selected[:maximum]}
        with pdfplumber.open(BytesIO(payload),pages=list(by_page)) as doc:
            for pdf in doc.pages:
                record=by_page[pdf.page_number]
                charts=parse_score_charts(pdf.extract_words(x_tolerance=2,y_tolerance=3),pdf.curves,pdf.lines)
                for chart in charts:chart.update(page=pdf.page_number,source_sha256=source_sha,version=VERSION)
                record['survey_charts']=charts
                record['survey_chart_attempt']={'version':VERSION,'source_sha256':source_sha,
                    'status':'geometry_matched' if charts else 'unresolved',
                    'boundary':'仅原生文字/单折线/显式年份数值标签且坐标轴校准一致；不是员工独立访谈。'}
                receipt['processed_pages'].append(pdf.page_number);receipt['charts']+=len(charts)
                if not charts:receipt['unresolved_pages'].append(pdf.page_number)
                pdf.close()
        receipt['method']='native_vector_line_chart'
    except Exception as exc:
        receipt.update(method='extraction_failed',error_type=type(exc).__name__)
        receipt['pending_pages']+= [p['page'] for p in selected[:maximum] if p['page'] not in receipt['processed_pages']]
    return receipt
