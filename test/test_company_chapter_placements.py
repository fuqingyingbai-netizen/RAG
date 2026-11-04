import json
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from report_agents.company_editorial import build_editorial_package,package_errors,parse_proposal,validate_audit,apply_narrative_uses
from report_agents.company_chapter_placements import appendix_html,accounted_ids
from test_company_editorial import record,proposal,audit,OUTLINE


def test_writer_can_place_minor_evidence_in_annex_with_independent_receipt_and_reuse():
    rows=[record('I-main'),record('I-annex',text='来源说明本期文件呈交日期，原字段未载单位。')]
    draft=proposal(rows[:1]);draft['placements']=[{'information_id':'I-annex','destination':'annex','reason':'原始呈交字段供对照，主文不重复版式细节。'}]
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':return json.dumps(draft,ensure_ascii=False)
        data=json.loads(prompt.rsplit('资料：\n',1)[1]);qa=audit(rows[:1],data['findings'])
        qa['placements']=[{'information_id':'I-annex','destination':'annex','supported':True,'critical_to_conclusion':False,'reason':'该原字段不影响主文结论，附件仍完整保留。'}]
        return json.dumps(qa,ensure_ascii=False)
    result=build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    assert result['batches'][0]['accepted'] and not result['diagnostic']['pending_information_ids']
    assert not package_errors(result,rows,'公司')
    assert accounted_ids(result)=={'I-main','I-annex'}
    usage=apply_narrative_uses({'records':deepcopy(rows)},result)
    assert any(u['surface']=='chapter_annex' for u in usage['records'][1]['uses'])
    html=appendix_html(usage,result);assert rows[1]['text'] in html and 'E-123456ABCDEF' in html
    reused=build_editorial_package({'records':rows},OUTLINE,'公司',lambda *a:pytest.fail('must reuse'),previous=result,workers=1)
    assert reused['batches'][0]['reused']
    changed=deepcopy(rows);changed[1]['text']+='本次已发生变化。'
    assert package_errors(result,changed,'公司')


def test_unapproved_or_critical_evidence_cannot_be_hidden_in_annex_or_excluded():
    rows=[record()]
    draft={'findings':[],'placements':[{'information_id':'I-a','destination':'annex','reason':'拟放附件'}]}
    findings,issues=parse_proposal(draft,rows,6,OUTLINE[5][1][0]);assert not issues
    chosen={'I-a':draft['placements'][0]}
    qa=audit([],[])
    assert 'missing_placement_review' in validate_audit(rows,findings,qa,chosen)
    qa['placements']=[{'information_id':'I-a','destination':'annex','supported':True,'critical_to_conclusion':True,'reason':'这是相反证据，会改变结论。'}]
    assert any('critical_or_unreviewed' in e for e in validate_audit(rows,findings,qa,chosen))


def test_foreign_placement_id_cannot_remove_an_unrepresented_record():
    rows=[record()];draft={'findings':[],'placements':[{'information_id':'I-foreign','destination':'exclude','reason':'不采用'}]}
    _,issues=parse_proposal(draft,rows,6,OUTLINE[5][1][0])
    assert 'unknown_or_repeated_placement' in issues and 'unrepresented_information:I-a' in issues


def test_native_subspan_selection_restores_only_unique_whitespace_and_keeps_context():
    from test_company_evidence_recovery import candidates,selected,TARGET
    from report_agents.company_source_review import validate_selection
    raw='表头：主体 / 期间 / 金额\n目标方 2025年 5万元\n限制：尚未完成交割。'
    _,sel=candidates(raw);doc=sel['prepared'][0][0]
    fact,error=validate_selection(selected(doc,quote='目标方2025年5万元'),{doc['evidence_id']:doc},TARGET)
    assert not error and fact['fact']=='目标方 2025年 5万元'
    assert raw[fact['original_offset']:fact['original_end']]==fact['fact']
    assert '尚未完成交割' in fact['context_quote']
    assert validate_selection(selected(doc,quote='目标方2025年5亿元'),{doc['evidence_id']:doc},TARGET)[1]=='nonliteral_quote'


def test_pending_batch_does_not_hide_passed_prose_from_summary_evidence():
    from report_agents.company_summary import build_company_summary_package
    from test_company_editorial import invoke_for
    rows=[record()]
    e=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke_for(rows),workers=1)
    e['diagnostic']['pending_information_ids']=['I-unfinished-other-batch']
    summary=build_company_summary_package({'facts':[]},'青禾食品公司',[],chapter_packages={'editorial':e})
    assert summary['facts'] and summary['pending_information_ids']==['I-unfinished-other-batch']


def test_new_company_heading_keeps_native_word_citation_bookmarks():
    from docx_exporter import markdown_to_docx_bytes
    from company_chapters import outline
    text='\n\n'.join('## '+str(n)+'. '+title+'\n\n'+('明确的公司原文事实[E-123456ABCDEF]。' if n==6 else
        '| 证据编号 | 支持章节 | 来源标题 | 台账定位 |\n| --- | --- | --- | --- |\n| E-123456ABCDEF | 6 | 原文 | https://source.test |' if n==13 else '本章资料仍待核对。') for n,(title,_) in enumerate(outline(),1))
    payload=markdown_to_docx_bytes(text,outline=outline(),document_kind='company_report')
    import zipfile,io,xml.etree.ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(payload)) as z:root=ET.fromstring(z.read('word/document.xml'))
    ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    names={x.get(ns+'name') for x in root.iter(ns+'bookmarkStart')}
    anchors={x.get(ns+'anchor') for x in root.iter(ns+'hyperlink')}
    assert 'evidence_E_123456ABCDEF' in names and 'evidence_E_123456ABCDEF' in anchors


def test_annex_html_roundtrips_actual_sqlite_object_store_and_download(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database import Base
    from models import User,ResearchProject
    import research_workflow,research_api
    from test_company_chapter_flow import local_store
    store=local_store(tmp_path);monkeypatch.setattr(research_workflow,'research_store',store)
    monkeypatch.setattr(research_api,'research_store',store)
    row=record('I-annex',text='原始值：0；未知；'+('完整字段。'*300)+'<script>untrusted()</script>')
    content=appendix_html({'records':[row]},{'batches':[{'chapter':6,'accepted':True,
        'placements':[{'information_id':'I-annex','destination':'annex','reason':'保留完整附加字段供复核。'}]}]})
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(username='annex-roundtrip',password_hash='local-unused',role='user');db.add(user);db.flush()
        project=ResearchProject(title='附件回读',target_type='company',target_name='测试公司',created_by_id=user.id)
        db.add(project);db.flush()
        artifact=research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow).save_artifact(
            db,project,'company_evidence_annex','章节证据附件',content,{'placement_scope':'chapter_writer_independently_reviewed'})
        response=research_api.download_artifact(artifact.id,db=db,current_user=user)
        assert response.media_type.startswith('text/html') and response.body.decode('utf-8')==content
        assert store.get_text(artifact.object_key)==content
        assert '<script>untrusted()' not in content and '&lt;script&gt;untrusted()' in content
        assert content.count('完整字段。')==300 and 'E-123456ABCDEF' in content
    engine.dispose()
