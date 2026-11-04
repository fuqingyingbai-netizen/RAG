"""Semantic dates/quotations, recoverable reviews and visible partial chapters."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from report_agents.company_editorial import (
    LEGACY_VERSION, VERSION, REVIEW_CRITERIA, bind_proposition_spans,
    build_editorial_package, digest_groups, fingerprint, native_propositions,
    package_errors, parse_proposal, record_payload, review_observations, validate_audit,
)
from report_agents.company_corpus_writer import render_compact_chapters
from report_agents.company_delivery_contract import fill_evidence_gaps
from test_company_editorial import OUTLINE, audit, invoke_for, proposal, record


@pytest.mark.parametrize('date', ['2025年9月26日', '2025-09-26', 'September 26, 2025'])
def test_real_announcement_date_and_page_do_not_force_literal_number_retention(date):
    rows=[record(text='董事会\n二〇二五年九月二十六日\n--- PDF page 3 ---\n3\n'
        '附件：文志州先生简历。文志州先生1978年1月出生，硕士，高级工程师。',chapter=7)]
    text='据公告，董事会于'+date+'披露文志州简历；文志州1978年1月出生，硕士，高级工程师。'
    findings,errors=parse_proposal({'findings':[{'finding_id':'p','text':text,'information_ids':['I-a']}]},rows,7,OUTLINE[6][1][0])
    assert not errors
    assert not validate_audit(rows,findings,audit(rows,findings))
    assert rows[0]['text'].count('3')==2  # The original is never edited.


def test_same_meaning_quote_can_use_native_proposition_id_instead_of_literal_retyping():
    rows=[record(text='文志州先生1998年加入海天。',chapter=7)]
    findings=[{'finding_id':'p','text':'公告称，文志州自1998年起在海天任职。','information_ids':['I-a']}]
    qa=audit(rows,findings)
    span=qa['information'][0]['spans'][0]
    span.update(proposition_id=native_propositions(rows[0])[0]['proposition_id'],
                source_excerpt='文志州自1998年开始在海天工作。',
                output_excerpt='公告称，文志州自1998年起在海天\n任职。')
    bound=bind_proposition_spans(rows,qa,findings)
    assert not validate_audit(rows,findings,bound)
    assert span['source_excerpt']==rows[0]['text']
    assert span['reported_source_excerpt']=='文志州自1998年开始在海天工作。'


def test_unknown_proposition_and_unlocatable_prose_are_not_invented_by_locator_repair():
    rows=[record()];findings=proposal(rows)['findings'];qa=audit(rows,findings)
    span=qa['information'][0]['spans'][0]
    span.update(proposition_id='invented',source_excerpt='原文并未披露的材料。',output_excerpt='正文并不存在的内容。')
    assert validate_audit(rows,findings,bind_proposition_spans(rows,qa,findings))


def test_changed_date_reaches_semantic_review_and_can_be_rejected():
    rows=[record(text='公司于二〇二五年九月二十六日完成交付。')];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':
            return json.dumps({'findings':[{'finding_id':'p','text':'公司于2025年9月27日完成交付。','information_ids':['I-a']}]},ensure_ascii=False)
        data=json.loads(prompt.split('资料：\n',1)[1]);qa=audit(rows,data['findings'])
        qa['criteria']['factual_support']=False;qa['findings'][0]['status']='unsupported'
        qa['issues']=['日期从9月26日变成9月27日，改变了事实。']
        return json.dumps(qa,ensure_ascii=False)
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    assert '公司交付正文独立审稿' in calls
    assert not package['findings'] and package['batches'][0]['review_status']=='revision_required'


def test_missing_numbers_are_observations_but_model_rejection_of_key_omission_still_blocks():
    rows=[record(text='公司披露收入100万元，净利润20万元。')]
    findings=[{'finding_id':'p','text':'公司披露收入100万元。','information_ids':['I-a']}]
    assert review_observations(rows,findings)
    qa=audit(rows,findings)
    assert not validate_audit(rows,findings,qa)  # No mechanical "copy every number" gate.
    qa['criteria']['semantic_retention']=False
    qa['information'][0]['status']='lost';qa['issues']=['遗漏本章关键净利润数据。']
    assert validate_audit(rows,findings,qa)


def test_a_review_timeout_retries_only_the_unchanged_draft_and_preserves_failure_state():
    rows=[record()];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':return json.dumps(proposal(rows),ensure_ascii=False)
        raise TimeoutError('review service unavailable')
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    batch=package['batches'][0]
    assert calls.count('公司交付正文编写')==1
    assert len(batch['attempts'])==1 and batch['attempts'][0]['proposal']==proposal(rows)
    assert calls.count('公司交付正文独立审稿')==3
    assert batch['attempts'][0]['transport_error']['attempts']==3
    assert batch['review_status']=='review_incomplete' and not package['findings']
    assert batch['attempts'][0]['last_call_role']=='公司交付正文独立审稿'
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=package,workers=1)
    assert package['batches'][0]['accepted'] and calls.count('公司交付正文编写')==1


def test_legacy_accepted_receipts_are_rechecked_and_reused_without_new_model_calls():
    rows=[record()]
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    legacy=deepcopy(package);legacy['version']=LEGACY_VERSION
    for b in legacy['batches']:
        b['input_sha256']=fingerprint({'version':LEGACY_VERSION,'target':'公司','chapter':b['chapter'],
            'aspect':b['aspect'],'records':[record_payload(r) for r in rows],'feedback':[]})
    def fail(*a):pytest.fail('valid old accepted prose should be revalidated locally')
    updated=build_editorial_package({'records':rows},OUTLINE,'公司',fail,previous=legacy,workers=1)
    assert updated['version']==VERSION and updated['batches'][0]['reused']
    assert not package_errors(updated,rows,'公司')
    legacy['batches'][0]['findings'][0]['text']='公司披露收入999亿元。'
    calls=[]
    changed=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=legacy,workers=1)
    assert calls and not changed['batches'][0].get('reused')


@pytest.mark.parametrize('review',[{}, {'criteria':[], 'findings':None, 'information':None}])
def test_empty_but_parseable_review_record_never_requests_a_prose_rewrite(review):
    rows=[record()];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps(proposal(rows) if role=='公司交付正文编写' else review,ensure_ascii=False)
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    assert calls.count('公司交付正文编写')==1
    assert not package['findings'] and package['batches'][0]['review_status']=='review_record_incomplete'


def test_partial_chapter_shows_accepted_prose_but_does_not_claim_completion():
    rows=[record(chapter=7)]
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    package['batches'].append({'chapter':7,'accepted':False,'information_ids':['I-pending']})
    p=SimpleNamespace(target_name='公司',company_editorial_package=package,company_information_usage_package={'records':rows})
    sections=render_compact_chapters(p,{'groups':digest_groups(package)},OUTLINE,{7:'旧的模板缺口说明'})
    assert rows[0]['text'] in sections[7] and '旧的模板缺口说明' not in sections[7]
    sections=fill_evidence_gaps(sections,package,OUTLINE,usage={'records':rows})
    assert rows[0]['text'] in sections[7] and '尚未通过完整验收' in sections[7]
