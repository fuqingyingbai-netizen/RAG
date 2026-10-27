from copy import deepcopy
from types import SimpleNamespace as NS

from report_agents.company_presentation import source_captions,render_annex,annex_errors
from test_company_editorial import record


def source(target='远山制造股份有限公司',title='另一企业股份有限公司'):
    return NS(url='https://static.cninfo.com.cn/charter.pdf',title=title,source_type='web',
        content='## '+target+'\n\n### 章 程 二〇二五年十月\n\n目 录\n第一章 总则',
        source_metadata={'content_kind':'provider_text','provider_content_complete':True})


def test_cover_caption_is_generic_literal_and_retains_conflicting_original_title():
    original=source();before=deepcopy(vars(original));project=NS(target_name='远山制造股份有限公司',sources=[original])
    captions=source_captions(project);caption=captions[original.url]
    assert caption['title']=='远山制造股份有限公司 章程 二〇二五年十月' and caption['mismatch']
    assert caption['original_title']=='另一企业股份有限公司' and vars(original)==before
    row=record(text='注册资本原值为100.00万元。')
    row['provenance'][0].update(source_url=original.url,source_title=original.title)
    content=render_annex({'records':[row]}, {}, project.target_name,captions)
    assert caption['title'] in content and '原记录标题与正文抬头不同' in content
    assert not annex_errors({'records':[row]},content)


def test_another_issuer_or_a_business_sentence_cannot_be_promoted_to_a_cover_caption():
    original=source();original.content='其他企业股份有限公司\n章程\n涉及远山制造股份有限公司。'
    assert source_captions(NS(target_name='远山制造股份有限公司',sources=[original]))=={}
    original.content='远山制造股份有限公司\n公司披露完成新产品交付。'
    assert source_captions(NS(target_name='远山制造股份有限公司',sources=[original]))=={}


def test_english_cover_uses_the_same_complete_issuer_binding():
    original=source('Northstar Devices Ltd.','Other Issuer Inc.')
    original.content='Northstar Devices Ltd.\nArticles of Association (2025)\nContents'
    captions=source_captions(NS(target_name='Northstar Devices Ltd.',sources=[original]))
    assert captions[original.url]['title']=='Northstar Devices Ltd. Articles of Association (2025)'


def test_display_alias_requires_same_native_source_id_and_exact_resource_path():
    original=source();original.id=7;original.url='http://static.cninfo.com.cn/charter.pdf'
    project=NS(target_name='远山制造股份有限公司',sources=[original]);row=record()
    row['provenance'][0].update(source_id='7',source_url='https://static.cninfo.com.cn/charter.pdf')
    assert row['provenance'][0]['source_url'] in source_captions(project,{'records':[row]})
    row['provenance'][0]['source_id']='8'
    assert row['provenance'][0]['source_url'] not in source_captions(project,{'records':[row]})
    row['provenance'][0].update(source_id='7',source_url='https://static.cninfo.com.cn/other.pdf')
    assert row['provenance'][0]['source_url'] not in source_captions(project,{'records':[row]})


def test_source_index_displays_cover_caption_without_changing_original_evidence_id():
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);original=source();target='远山制造股份有限公司'
    eid=workflow._stable_evidence_id(original.url,original.title)
    fact={'source_url':original.url,'source_title':original.title,'fact':target+'注册资本为100.00万元。',
          'evidence_id':eid,'evidence_ids':[eid],'evidence_scope':'target_direct','chapter':2}
    project=NS(target_name=target,target_type='company',sources=[original],company_source_review_package={'facts':[fact]})
    project.company_source_captions=source_captions(project)
    text='## 2. 主体\n原文记录。['+eid+']\n\n## 13. 来源\n\n## 14. 后续'
    result=workflow._append_report_evidence_index(project,text,'{"facts":[]}')
    assert '远山制造股份有限公司 章程' in result and eid in result and original.title=='另一企业股份有限公司'
