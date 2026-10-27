from copy import deepcopy
from types import SimpleNamespace

from report_agents.company_history import _issuer_hosts
from report_agents.company_issuer_identity import build_issuer_identity,publisher_anchor,website_declarations,binding_matches_fact
from report_agents.company_management import issuer
from report_agents.report_prompts import _company_fact_has_trusted_target_anchor
from research_workflow import ResearchWorkflow

TARGET='青禾网络科技有限公司'
LEGAL='Blue River Network Limited'


def filing(body='本公司網站 www.blueriver.test 閱覽。'):
    return {'url':'https://www.hkexnews.hk/annual.pdf','title':TARGET+'年度报告',
            'content':LEGAL+'\n'+TARGET+'\n2025年年度报告\n'+body,'source_metadata':{}}


def page(body,url='https://home.blueriver.test/news/one'):
    return {'url':url,'title':'青禾集团公告','content':body,'source_metadata':{'content_kind':'full_text'}}


def test_declared_website_does_not_require_colon_protocol_or_simplified_script():
    raw='並可於本公司網站  www.blueriver.test  \n閱覽。'
    row=website_declarations(raw)[0]
    assert row['host']=='blueriver.test' and row['evidence_quote'] in raw
    assert _issuer_hosts([filing(raw)],TARGET)=={'blueriver.test'}
    assert _issuer_hosts([filing('网站：https://www.blueriver.test')],TARGET)=={'blueriver.test'}


def test_bilingual_press_publisher_requires_independent_cover_and_site_proof():
    p=page(LEGAL+' (NYSE: BLUE, the “Company”) today announced the completion of its placing.')
    originals=[filing(),p];before=deepcopy(originals)
    context=build_issuer_identity(originals,TARGET);anchor=publisher_anchor(p,TARGET,context)
    assert anchor['matched'] and anchor['issuer_name']==TARGET
    assert anchor['evidence_quote'] in p['content']
    assert anchor['bilingual_binding']['cover_source_url']==filing()['url']
    assert _issuer_hosts(originals,TARGET)=={'blueriver.test','home.blueriver.test'}
    assert originals==before
    for url in ['https://home.blueriver.test.evil.example/news','https://users.blueriver.test/news','https://home.other.test/news']:
        assert not publisher_anchor({**p,'url':url},TARGET,context)
    assert not publisher_anchor(page('Another Network Limited (the “Company”) today announced the placing.'),TARGET,context)


def test_copyright_authenticates_a_corporate_publisher_without_owning_a_subsidiary_filing():
    p=page('公司治理\n我们的审计委员会负责审核。\n版權公告 © 1999-2026 青禾網絡科技有限公司及／或其關聯公司。')
    context=build_issuer_identity([filing(),p],TARGET)
    anchor=publisher_anchor(p,TARGET,context)
    assert anchor['publisher_only'] and anchor['evidence_quote'] in p['content']
    assert issuer(p,TARGET,_issuer_hosts([filing(),p],TARGET))
    p['content']+='\n![icon](data:image/gif;base64,'+'A'*12000+')'
    assert publisher_anchor(p,TARGET,context)['publisher_only']
    p['content']='青禾網絡技術有限公司\n2025年年度報告\n'+p['content']
    assert not publisher_anchor(p,TARGET,context)


def test_cleaning_recomputes_bilingual_binding_and_never_revives_an_explicitly_rejected_card():
    p=page(LEGAL+' (NYSE: BLUE, the “Company”) today announced the completion of its placing.')
    source=filing();project=SimpleNamespace(target_name=TARGET,target_type='company',sources=[source,p])
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    fact={'source_url':p['url'],'source_title':p['title'],'fact':'Placement completed.','evidence_quote':p['content'],'claim_type':'source_excerpt'}
    result=w._annotate_evidence_facts(project,[fact])[0]
    assert result['evidence_scope']=='target_direct' and binding_matches_fact(result,TARGET)
    assert _company_fact_has_trusted_target_anchor(result,TARGET)
    rejected=w._annotate_evidence_facts(project,[{**fact,'eligible_for_report':False}])[0]
    assert rejected['eligible_for_report'] is False and 'source_issuer_binding' not in rejected
    forged={**result,'source_url':'https://news.other.test/item'}
    result=w._annotate_evidence_facts(project,[forged])[0]
    assert 'source_issuer_binding' not in result and not _company_fact_has_trusted_target_anchor(result,TARGET)


def test_search_summary_and_rejected_original_are_not_publisher_proof():
    p=page(LEGAL+' (NYSE: BLUE, the “Company”) today announced the completion of its placing.')
    context=build_issuer_identity([filing(),p],TARGET)
    p['source_metadata']['content_kind']='search_summary'
    assert not publisher_anchor(p,TARGET,context)
    p['source_metadata']={'entity_validation':'rejected'}
    assert not publisher_anchor(p,TARGET,context)
