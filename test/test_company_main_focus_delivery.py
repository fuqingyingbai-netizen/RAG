"""Fact focusing must preserve sources, independent witnesses and final gates."""
import json
from copy import deepcopy

import pytest

from report_agents.company_main_focus import (
    CRITERIA,build_main_focus,package_errors,source_units,validate_focus_batch,checkpoint_batch,
)
from report_agents.company_presentation import build_presentation,main_usage,render_annex,annex_errors
from report_agents.company_editorial import (
    retention_propositions,retention_source_text,record_payload,fingerprint,prose_errors,
    bind_proposition_spans,validate_audit,REVIEW_CRITERIA,proposal_prompt,audit_prompt,
)
from report_agents.company_checkpoint import read_generation_checkpoint,save_generation_checkpoint
from test_company_editorial import record
from test_company_presentation import TARGET,SCOPE,placements
from test_company_checkpoint import project,store


def native_answers(rows,select=None):
    return {'records':[{'information_id':r['information_id'],
        'main_proposition_ids':select(r) if select else [u['proposition_id'] for u in source_units(r)],
        'reason':'保留具体经营事实以及影响其解读的限定条件。','criteria':dict.fromkeys(CRITERIA,True)} for r in rows]}


def selected_package(rows,invoke=None):
    usage={'records':rows}
    placement=build_presentation(usage,TARGET,SCOPE,lambda *a:json.dumps(placements(rows,'main')),workers=1)
    focus=build_main_focus(usage,placement,TARGET,SCOPE,invoke or (lambda *a:json.dumps(native_answers(rows))),workers=1)
    return usage,placement,focus


@pytest.mark.parametrize('target',['青禾食品公司','远帆物流有限公司','Northstar Devices Ltd','某研发工作室'])
def test_same_source_bound_focus_contract_for_different_companies_and_sectors(target):
    rows=[record(text=target+'披露产品已交付。联系电话：12345678。')]
    usage={'records':rows};before=deepcopy(usage);calls=[]
    placement=build_presentation(usage,target,SCOPE,lambda *a:json.dumps(placements(rows,'main')),workers=1)
    def invoke(role,prompt,trace):
        calls.append((role,prompt))
        return json.dumps(native_answers(rows,lambda r:[source_units(r)[0]['proposition_id']]))
    focus=build_main_focus(usage,placement,target,SCOPE,invoke,workers=1)
    assert not package_errors(focus,usage,placement,target,SCOPE)
    assert len(calls)==2 and rows[0]['text'] in calls[0][1] and rows[0]['text'] in calls[1][1]
    assert '不提供另一人的候选结论' in calls[1][1]
    focused=main_usage(usage,placement,focus)['records'][0]
    assert focused['text']==rows[0]['text'] and usage==before
    assert '12345678' not in retention_source_text(focused)
    assert '12345678' in render_annex(usage,placement,target)
    assert not annex_errors(usage,render_annex(usage,placement,target),placement)
    assert len(retention_propositions(focused))==1
    assert record_payload(focused)!=record_payload(rows[0])
    assert prose_errors(target+'披露产品已交付，收入为999元。',[focused])


def test_independent_reader_selection_promotes_extra_facts_without_dropping_first_choice():
    row=record(text='公司收入为100万元。公司经营现金流为0元。联系电话：12345678。')
    def invoke(role,prompt,trace):
        ids=[source_units(row)[1 if role.endswith('独立审稿') else 0]['proposition_id']]
        return json.dumps(native_answers([row],lambda r:ids))
    usage,placement,focus=selected_package([row],invoke)
    assert not package_errors(focus,usage,placement,TARGET,SCOPE)
    retained=retention_source_text(main_usage(usage,placement,focus)['records'][0])
    assert '100万元' in retained and '0元' in retained and '12345678' not in retained


def test_missing_choices_are_retried_in_full_context_and_need_actual_witnesses():
    rows=[record('I-a'),record('I-b',text='公司披露新产线尚未投产。')];calls=[]
    def invoke(role,prompt,trace):
        calls.append((role,prompt))
        subset=[rows[0]] if len(calls)==1 else [rows[1]] if len(calls)==2 else rows
        return json.dumps(native_answers(subset))
    usage,placement,focus=selected_package(rows,invoke)
    assert not package_errors(focus,usage,placement,TARGET,SCOPE)
    assert len(calls)==3 and all(all(r['text'] in p for r in rows) for _,p in calls)
    assert '本轮只补齐' in calls[1][1]
    changed=deepcopy(focus);changed['batches'][0]['attempts']=[]
    assert package_errors(changed,usage,placement,TARGET,SCOPE)
    changed=deepcopy(focus);changed['batches'][0]['attempts'][0]['object_response_attempts'][0]['input_sha256']='0'*64
    assert 'main_focus_original_input_witness_changed' in package_errors(changed,usage,placement,TARGET,SCOPE)


@pytest.mark.parametrize('change',['text','context','provenance','scope','selection','witness','input'])
def test_reused_focus_revalidates_originals_scope_choices_and_actual_raw_reply(change):
    rows=[record()];usage,placement,focus=selected_package(rows)
    altered=deepcopy(focus);usage=deepcopy(usage);scope=deepcopy(SCOPE)
    if change=='text':usage['records'][0]['text']+='另一期间的新事实。'
    elif change=='context':usage['records'][0]['context']['scope']='subsidiary_only'
    elif change=='provenance':usage['records'][0]['provenance'][0]['source_title']='其他主体公告'
    elif change=='scope':scope['as_of_date']='2026-10-25'
    elif change=='selection':altered['focuses']['I-a']['spans'][0]['text']='伪造原文'
    elif change=='witness':altered['batches'][0]['attempts'][0]['object_response_attempts'][0]['raw_response']='{}'
    else:altered['batches'][0]['input_sha256']='0'*64
    assert package_errors(altered,usage,placement,TARGET,scope)


@pytest.mark.parametrize('kind',['registry','financial_metric','event','case_detail','scan','lookup'])
def test_core_records_never_enter_model_fact_trimming(kind):
    row=record(text='公司披露本期为0元，上期为100万元，原因及口径尚待核实。',kind=kind)
    usage,placement,focus=selected_package([row],lambda *a:pytest.fail('Core record must retain full text.'))
    assert not package_errors(focus,usage,placement,TARGET,SCOPE)
    assert not focus['batches'] and focus['full_record_information_ids']==['I-a']
    assert main_usage(usage,placement,focus)['records'][0]==row


def test_unfinished_focus_never_becomes_an_accepted_partition_or_silent_annex():
    usage,placement,focus=selected_package([record()],lambda *a:'{"records":[]}')
    assert focus['diagnostic']['pending_information_ids']==['I-a']
    assert package_errors(focus,usage,placement,TARGET,SCOPE)
    assert main_usage(usage,placement,focus)['records'][0]['information_id']=='I-a'


def test_body_audit_requires_selected_numbers_and_retains_full_source_support_check():
    row=record(text='公司收入为100万元。联系电话：12345678。')
    usage,placement,focus=selected_package([row],lambda *a:json.dumps(native_answers([row],lambda r:[source_units(r)[0]['proposition_id']])))
    focused=main_usage(usage,placement,focus)['records'][0];unit=retention_propositions(focused)[0]
    findings=[{'finding_id':'f','text':'公司收入为100万元。','information_ids':['I-a']}]
    audit={'criteria':dict.fromkeys(REVIEW_CRITERIA,True),'findings':[{'finding_id':'f','status':'supported','reason':'原文支持该金额和范围。'}],
        'information':[{'information_id':'I-a','status':'retained','reason':'所选经营事实已经完整表达。',
            'spans':[{'proposition_id':unit['proposition_id'],'finding_id':'f','output_excerpt':findings[0]['text']}]}],'issues':[]}
    bind_proposition_spans([focused],audit)
    assert not validate_audit([focused],findings,audit)
    changed=deepcopy(findings);changed[0]['text']='公司收入增长。'
    assert any(e.startswith('lost_numeric_information') for e in validate_audit([focused],changed,audit))
    assert prose_errors('公司收入为999万元。',[focused])
    assert '完整text' in proposal_prompt([focused],TARGET,6,'实际经营')
    assert '事实筛选漏掉' in audit_prompt([focused],findings,TARGET)
    assert 'source_text_sha256' not in proposal_prompt([focused],TARGET,6,'实际经营')


def test_native_focus_journal_survives_interrupt_and_is_revalidated_before_reuse(tmp_path):
    usage,placement,focus=selected_package([record()]);p=project();storage=store(tmp_path)
    p.company_generation_checkpoint_store=storage
    checkpoint_batch(p,focus['batches'][0]);caches=read_generation_checkpoint(p,store=storage)
    prior=caches['company_main_focus_cache'];prior.update(target_name=TARGET,scope=SCOPE)
    recovered=build_main_focus(usage,placement,TARGET,SCOPE,lambda *a:pytest.fail('Valid batch should reuse.'),previous=prior,workers=1)
    assert recovered['batches'][0]['reused'] and not package_errors(recovered,usage,placement,TARGET,SCOPE)
    p.company_main_focus_package=focus;save_generation_checkpoint(p,store=storage)
    assert read_generation_checkpoint(p,store=storage)['company_main_focus_cache']['batches']


def test_selected_short_unknown_requires_its_own_review_span():
    row=record(text='公司披露产品已交付。\n无')
    usage,placement,focus=selected_package([row])
    focused=main_usage(usage,placement,focus)['records'][0];units=retention_propositions(focused)
    findings=[{'finding_id':'f','text':'公司披露产品已交付。','information_ids':['I-a']}]
    audit={'criteria':dict.fromkeys(REVIEW_CRITERIA,True),'findings':[{'finding_id':'f','status':'supported','reason':'原文支持该事实。'}],
        'information':[{'information_id':'I-a','status':'retained','reason':'经营事实已经表达。','spans':[
            {'proposition_id':units[0]['proposition_id'],'finding_id':'f','output_excerpt':findings[0]['text']}]}],'issues':[]}
    bind_proposition_spans([focused],audit)
    assert 'unreviewed_selected_proposition:I-a' in validate_audit([focused],findings,audit)


def test_unreadable_format_requires_new_full_context_response_and_reviewer_still_runs():
    row=record();calls=[]
    def invoke(role,prompt,trace):
        calls.append((role,prompt))
        return '<escape>'+json.dumps(native_answers([row])) if len(calls)==1 else json.dumps(native_answers([row]))
    usage,placement,focus=selected_package([row],invoke)
    assert not package_errors(focus,usage,placement,TARGET,SCOPE)
    assert len(calls)==3 and all(row['text'] in prompt for _,prompt in calls)
    assert len(focus['batches'][0]['attempts'][0]['object_response_attempts'])==2
    assert calls[-1][0].endswith('独立审稿')
