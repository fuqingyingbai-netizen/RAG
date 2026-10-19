import copy
import hashlib
from types import SimpleNamespace

import pytest

from company_charts import VERSION, extract_survey_charts, parse_score_charts
from report_agents.company_reputation import survey_chart_rows, build_reputation_package, render_reputation


def geometry(title='Band类员工调查分数（满分100分）',years=(2022,2023,2024,2025),values=(74,80,77,79),scale=100):
    ticks=(82,80,78,76,74,72,70) if scale==100 else (5,4,3,2,1,0)
    ratio=10 if scale==100 else 40
    y=lambda v:100+(ticks[0]-v)*ratio
    words=[{'text':title,'x0':220,'x1':480,'top':75,'bottom':85}]
    lines=[]
    for tick in ticks:
        lines.append({'x0':100,'x1':600,'top':y(tick),'bottom':y(tick)})
        words.append({'text':str(tick),'x0':70,'x1':90,'top':y(tick)-4,'bottom':y(tick)+6})
    points=[]
    for i,(year,value) in enumerate(zip(years,values)):
        x=200+i*100;points.append((x,y(value)))
        words.append({'text':str(year)+'年','x0':x-18,'x1':x+18,'top':y(ticks[-1])+15,'bottom':y(ticks[-1])+25})
        offset=14 if i%2 else -10
        words.append({'text':str(value),'x0':x-6,'x1':x+6,'top':y(value)+offset-5,'bottom':y(value)+offset+5})
    curve={'pts':points,'top':min(p[1] for p in points),'bottom':max(p[1] for p in points),
           'stroke':True,'fill':False,'stroking_color':(0,.5,.8)}
    return words,[curve],lines


@pytest.mark.parametrize('title,values,scale',[
    ('Band類員工調查分數（滿分100分）',(74,80,77,79),100),
    ('制造类员工满意度调查分数（满分5分）',(3.8,4.1,4.3,4.2),5),
    ('星河服务员工敬业度分数（满分100分）',(73,78,76,80),100),
])
def test_different_populations_and_scales_bind_labels_years_and_vertices(title,values,scale):
    charts=parse_score_charts(*geometry(title=title,values=values,scale=scale))
    assert len(charts)==1
    assert [(p['year'],p['value']) for p in charts[0]['points']]==[(str(2022+i),str(v)) for i,v in enumerate(values)]
    assert charts[0]['caption']==title and charts[0]['score_scale']==str(scale)
    assert len(charts[0]['axis_ticks'])>=4


@pytest.mark.parametrize('change',['missing_label','wrong_value','missing_year','reversed_years','nonlinear_axis','second_series','bezier'])
def test_ambiguous_or_inconsistent_geometry_is_not_interpolated(change):
    words,curves,lines=geometry()
    if change=='missing_label':words=[w for w in words if not(w['text']=='79' and w['x0']>100)]
    if change=='wrong_value':next(w for w in words if w['text']=='79')['text']='86'
    if change=='missing_year':words=[w for w in words if w['text']!='2023年']
    if change=='reversed_years':
        next(w for w in words if w['text']=='2022年')['text']='2026年'
    if change=='nonlinear_axis':next(w for w in words if w['text']=='82')['text']='95'
    if change=='second_series':
        other=copy.deepcopy(curves[0]);other['pts']=[(x,y+4) for x,y in other['pts']]
        other['top']+=4;other['bottom']+=4;other['stroking_color']=(.8,.2,.2);curves.append(other)
    if change=='bezier':curves[0]['path']=[('c',(1,2),(3,4),(5,6))]
    assert not parse_score_charts(words,curves,lines)


def extracted_chart():
    c=parse_score_charts(*geometry())[0]
    return {**c,'page':39,'version':VERSION,'source_sha256':'a'*64}


def test_source_hash_caption_and_original_scale_are_required():
    chart=extracted_chart();page={'page':39,'text':chart['caption'],'survey_charts':[chart]}
    assert not survey_chart_rows(page,'b'*64)
    assert not survey_chart_rows({**page,'text':'another document'},'a'*64)
    row=survey_chart_rows(page,'a'*64)[0]
    assert row['metric']=='Band类员工调查分数'
    assert row['value']=='79（满分100分）' and row['previous_value']=='77（满分100分）'
    assert row['period']=='2025年' and row['previous_period']=='2024年'
    assert row['evidence_quote']==chart['caption'] and len(row['chart_evidence']['points'])==4
    assert not survey_chart_rows(page,'a'*64,as_of_year=2024)
    assert not survey_chart_rows({**page,'page':40},'a'*64)


def test_future_targets_are_not_reported_as_completed_employee_survey():
    assert not parse_score_charts(*geometry(title='员工满意度目标预测分数（满分100分）'))


def test_chart_updates_report_without_claiming_whole_workforce_or_independent_survey():
    chart=extracted_chart();text='我们每年开展统一的员工敬业度调查，通过分析调查结果制定针对性优化措施。\n'+chart['caption']
    source={'url':'https://www.hkexnews.hk/report.pdf','title':'星河服务股份有限公司2025年ESG报告',
            'content':'本报告是星河服务股份有限公司发布的ESG报告。\n2025年\n'+text,
            'source_metadata':{'document_pages':[{'page':39,'text':text,'survey_charts':[chart]}],
             'document_extraction':{'survey_charts':{'version':VERSION,'source_sha256':'a'*64}}}}
    card={'evidence_id':'E-123456ABCDEF','source_url':source['url'],'source_title':source['title']}
    packet=build_reputation_package({'facts':[card]},'星河服务股份有限公司',[source])
    body=render_reputation(packet)
    assert 'Band类员工调查分数' in body and '79（满分100分）' in body and '77（满分100分）' in body
    assert '尚未可靠绑定' not in body and '不扩写为全体员工满意度' in body
    assert any(r.get('chart_evidence') for r in packet['facts'])


def test_acquisition_persists_physical_page_and_pdf_hash(monkeypatch):
    import pdfplumber
    words,curves,lines=geometry()
    page=SimpleNamespace(page_number=39,extract_words=lambda **kw:words,curves=curves,lines=lines,close=lambda:None)
    class Document:
        pages=[page]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(pdfplumber,'open',lambda *a,**kw:Document())
    records=[{'page':39,'text':'Band类员工调查分数（满分100分） 2022年2023年2024年2025年'}]
    result=extract_survey_charts(b'source-pdf',records)
    assert result['processed_pages']==[39] and result['charts']==1
    assert records[0]['survey_charts'][0]['source_sha256']==hashlib.sha256(b'source-pdf').hexdigest()
    assert records[0]['survey_charts'][0]['page']==39


def test_workflow_refetches_old_candidate_once_and_reuses_completed_state(monkeypatch):
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);calls=[];chart=extracted_chart()
    source=SimpleNamespace(id=3,url='https://www.hkexnews.hk/report.pdf',content='old original',summary='',
        source_metadata={'document_pages':[{'page':39,'text':chart['caption']+' 2022年2023年2024年2025年'}]})
    project=SimpleNamespace(id=1,target_type='company',sources=[source])
    def fetch(*a,**k):
        calls.append(1)
        return {'content':'new coherent original','status':'done','document_pages':[
            {'page':39,'text':chart['caption'],'survey_charts':[chart]}],
            'document_extraction':{'survey_charts':{'version':VERSION,'source_sha256':'a'*64,'charts':1}}}
    monkeypatch.setattr(w,'_fetch_web_url_with_timeout',fetch)
    db=SimpleNamespace(commit=lambda:None)
    assert w.enrich_company_survey_charts(db,project)==1 and source.content=='new coherent original'
    assert w.enrich_company_survey_charts(db,project)==0 and len(calls)==1
    project.target_type='industry'
    assert w.enrich_company_survey_charts(db,project)==0 and len(calls)==1


def test_workflow_fetch_failure_keeps_original_and_does_not_repeat(monkeypatch):
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);calls=[]
    source=SimpleNamespace(id=3,url='https://www.hkexnews.hk/report.pdf',content='original preserved',summary='',
        source_metadata={'document_pages':[{'page':39,'text':'员工调查分数（满分100分） 2024年2025年'}]})
    p=SimpleNamespace(id=1,target_type='company',sources=[source])
    def fetch(*a,**k):calls.append(1);return {'status':'blocked_or_challenge','content':''}
    monkeypatch.setattr(w,'_fetch_web_url_with_timeout',fetch)
    db=SimpleNamespace(commit=lambda:None)
    assert w.enrich_company_survey_charts(db,p)==0 and source.content=='original preserved'
    assert source.source_metadata['survey_chart_refresh']['status']=='failed'
    assert w.enrich_company_survey_charts(db,p)==0 and len(calls)==1
