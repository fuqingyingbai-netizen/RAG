import json
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from report_agents.company_presentation import (
    reading_mode,build_presentation,package_errors,main_usage,render_annex,annex_errors,
    placement_payload,AnnexParser,knowledge_annex_text,
)
from report_agents.company_editorial import fingerprint,record_payload
import hashlib
from test_company_editorial import record


TARGET='青禾食品公司'
SCOPE={'as_of_date':'2026-10-24','reading_format':'analysis_with_annex'}


def placements(rows,surface='evidence'):
    return {'records':[{'information_id':r['information_id'],'surface':surface,
        'reason':'该条为常规程序的完整原文细节，供读者查阅来源。','source_excerpt':r['text']} for r in rows]}


def invoke_for(rows,*,promote=None,calls=None):
    def invoke(role,prompt,trace):
        if calls is not None:calls.append(role)
        answer=placements(rows)
        if role.endswith('独立审稿'):
            for item in answer['records']:
                if item['information_id']==promote:item.update(surface='main',reason='该条包含影响本章判断的重要变化，正文需要具体表达。')
        return json.dumps(answer,ensure_ascii=False)
    return invoke


def test_format_default_and_explicit_detailed_mode_are_adjustable(monkeypatch):
    monkeypatch.delenv('COMPANY_REPORT_READING_MODE',raising=False)
    assert reading_mode(NS())=='analysis_with_annex'
    assert reading_mode(NS(company_research_intake={'reading_format':'detailed'}))=='detailed'
    with pytest.raises(ValueError):reading_mode(NS(company_research_intake={'reading_format':'unknown'}))


def test_two_bound_reviews_required_for_annex_and_disagreement_promotes_main():
    rows=[record('I-a',text='公司章程载明会议记录应由出席人员签名。'),record('I-b',text='公司披露新产线已于报告期内完成投产。')]
    usage={'records':rows};before=deepcopy(usage)
    package=build_presentation(usage,TARGET,SCOPE,invoke_for(rows,promote='I-b'),workers=1)
    assert package['main_information_ids']==['I-b'] and package['evidence_information_ids']==['I-a']
    assert not package_errors(package,usage,TARGET,SCOPE) and usage==before
    assert main_usage(usage,package)['records']==[rows[1]]
    html=render_annex(usage,package,TARGET)
    assert not annex_errors(usage,html) and all(r['text'] in html for r in rows)


@pytest.mark.parametrize('context',[{'kind':'registry'},{'kind':'case'},{'field':'注册资本','value':'未知'},
                                    {'field':'实缴资本','value':'0'}])
def test_structured_core_and_zero_unknown_identity_fields_cannot_be_hidden_in_annex(context):
    rows=[record(text='平台返回目标公司的本字段原值为未知或零，保留原义。',**context)]
    package=build_presentation({'records':rows},TARGET,SCOPE,invoke_for(rows),workers=1)
    assert package['main_information_ids']==['I-a'] and not package['evidence_information_ids']


def test_explicit_comparable_differences_force_both_originals_into_main():
    rows=[record('I-a',text='平台披露本期同口径指标原值10元。',entity=TARGET,scope='target',field='样本指标',period='2026年半年度',value='10',unit='元'),
          record('I-b',text='另一来源披露本期同口径指标原值12元。',entity=TARGET,scope='target',field='样本指标',period='2026年半年度',value='12',unit='元')]
    package=build_presentation({'records':rows},TARGET,SCOPE,invoke_for(rows),workers=1)
    assert set(package['main_information_ids'])=={'I-a','I-b'}
    assert not package_errors(package,{'records':rows},TARGET,SCOPE)


def test_missing_or_unbound_independent_review_stays_pending_instead_of_accepting_flags():
    rows=[record()]
    def invoke(role,prompt,trace):
        answer=placements(rows)
        if role.endswith('独立审稿'):answer['records'][0]['source_excerpt']='并不存在于本条原文的引文。'
        return json.dumps(answer)
    package=build_presentation({'records':rows},TARGET,SCOPE,invoke,workers=1)
    assert package['diagnostic']['pending_information_ids']==['I-a']
    assert not package['main_information_ids'] and not package['evidence_information_ids']
    assert package_errors(package,{'records':rows},TARGET,SCOPE)


@pytest.mark.parametrize('text,quote',[
    ('公司董事会、单独或者合计持 有公司1%以上股份的股东可以提出独 立董事候选人。','持有公司1%以上股份的股东可以提出独'),
    ('年度股东会应于上一个会计年度结束后的\u20026\u2002个月之内举行。','应于上一个会计年度结束后的 6 个月之内举行'),
    ('第十二条 股东可以起诉公司董事、高级 \n 管理人员。','股东可以起诉公司董事、高级管理人员'),
    ('股東有權自決議 作出之日起六十日內，請求人民法院撤銷。','股東有權自決議作出之日起六十日內'),
])
def test_pdf_layout_quote_locator_restores_verbatim_native_span_in_both_reviews(text,quote):
    from report_agents.company_presentation import validate_placements
    rows=[record(text=text)];answer=placements(rows);answer['records'][0]['source_excerpt']=quote
    before=deepcopy(answer)
    checked,errors=validate_placements(rows,answer)
    assert not errors and answer==before
    assert checked['I-a']['source_excerpt'] in text and checked['I-a']['model_source_excerpt']==quote
    package=build_presentation({'records':rows},TARGET,SCOPE,lambda *args:json.dumps(answer),workers=1)
    assert not package_errors(package,{'records':rows},TARGET,SCOPE)
    for stage in ('proposal','review'):
        receipt=package['placements']['I-a'][stage]
        assert receipt['source_excerpt'] in text and receipt['model_source_excerpt']==quote
    assert package['batches'][0]['proposal']==answer  # original model locator remains auditable


@pytest.mark.parametrize('quote',[
    '公司注册资本为人民币46,401.3436万元',  # number changed
    '公司注册资本为人民币46,401.3435元',    # unit changed
    '公司注册资本为人民幣46,401.3435万元',  # glyph changed
    '公司注册资本人民币为46,401.3435万元',  # word order changed
    '公司注册资本为人民币46,401.3435万元。公司已完成变更',  # extra claim
])
def test_layout_locator_never_repairs_changed_native_glyphs_numbers_units_or_claims(quote):
    from report_agents.company_presentation import validate_placements
    rows=[record(text='公司注册资本为人民币\u200246,401.3435\u2002万元。')]
    answer=placements(rows);answer['records'][0]['source_excerpt']=quote
    checked,errors=validate_placements(rows,answer)
    assert not checked and 'unbound_placement:I-a' in errors


def test_location_repair_repeats_complete_independent_review_without_changing_valid_proposal():
    rows=[record('I-a'),record('I-b',text='公司披露本期新增产品线已投产。')];calls=[];reviews=0
    def invoke(role,prompt,trace):
        nonlocal reviews
        calls.append(role);answer=placements(rows)
        if role.endswith('独立审稿'):
            reviews+=1
            if reviews==1:answer['records'][0]['source_excerpt']='并不存在的引文。'
            else:
                assert '上次返回未通过' in prompt and all(r['text'] in prompt for r in rows)
                answer['records'][1]['surface']='main'
        return json.dumps(answer)
    package=build_presentation({'records':rows},TARGET,SCOPE,invoke,workers=1)
    assert calls.count('公司交付正文取舍')==1 and reviews==2
    assert not package['diagnostic']['pending_information_ids'] and package['main_information_ids']==['I-b']


def test_cached_receipts_need_identical_full_inputs_and_partition_cannot_be_relabelled():
    rows=[record()];usage={'records':rows};calls=[]
    package=build_presentation(usage,TARGET,SCOPE,invoke_for(rows,calls=calls),workers=1)
    assert len(calls)==2
    reused=build_presentation(usage,TARGET,SCOPE,lambda *a:pytest.fail('unchanged input was called again'),previous=package,workers=1)
    assert not package_errors(reused,usage,TARGET,SCOPE)
    forged=deepcopy(package);forged['main_information_ids']=['I-a'];forged['evidence_information_ids']=[]
    assert any(e.startswith('presentation_partition_changed:') for e in package_errors(forged,usage,TARGET,SCOPE))
    changed=deepcopy(usage);changed['records'][0]['context']['period']='2025年度'
    assert 'presentation_input_changed' in package_errors(package,changed,TARGET,SCOPE)


def test_complete_annex_preserves_native_text_excluded_records_and_escapes_untrusted_html():
    rows=[record(text='平台原值0、未知，文本含</pre><script>alert(1)</script>和甲&乙。'),
          record('I-b',text='无关内容也保存在使用与排除清单。')]
    rows[0]['provenance'][0]['source_url']='javascript:alert(1)'
    rows[1]['decision']={'status':'exclude','reason':'与本次报告主体完全无关。'}
    usage={'records':rows};html=render_annex(usage,{},TARGET)
    assert not annex_errors(usage,html)
    assert '<pre class="native">平台原值0、未知，文本含&lt;/pre&gt;' in html
    assert 'href="javascript:' not in html
    assert annex_errors(usage,html.replace('原值0','原值1'))
    assert annex_errors(usage,html.replace('data-information-id="I-b"','data-information-id="I-a"'))


def test_compact_placement_keeps_complete_native_text_all_context_and_full_hash_binding():
    row=record(text='完整原文包含0万元、未知、否定和条件。'*2000,trial_phase='phase 2',flags={'zero':0,'false':False})
    row['provenance'][0].update(native_quote='更宽的原始定位范围，包括本字段及相邻表头。',original_offset=123)
    before=deepcopy(row);payload=placement_payload(row)
    assert payload['text']==row['text'] and payload['context']==row['context']
    assert payload['provenance'][0]['original_offset']==123 and 'native_quote' not in payload['provenance'][0]
    assert row==before and row['provenance'][0]['native_quote'] in render_annex({'records':[row]}, {}, TARGET)


def test_context_and_provenance_changes_are_rejected_even_when_native_prose_is_identical():
    row=record(period='2025年度');usage={'records':[row]};content=render_annex(usage,{},TARGET)
    changed=content.replace('2025年度','2026年度')
    errors=annex_errors(usage,changed)
    assert 'annex_native_metadata_changed:context' in errors and 'annex_native_information_changed_or_missing' not in errors
    changed=content.replace('https://foods.test/report','https://other.test/replaced')
    assert 'annex_native_metadata_changed:provenance' in annex_errors(usage,changed)


def test_only_exactly_repeated_source_boundaries_are_shared_not_different_publishers_or_scopes():
    row=record(source_kind='issuer_disclosure',boundary='公司自述，执行情况未独立核实。')
    row['provenance']=[{'source_url':'https://issuer.test/a','source_kind':'issuer_disclosure','boundary':row['context']['boundary']},
        {'source_url':'https://press.test/b','source_kind':'attributed_publication','boundary':'媒体转述，不代表公司已确认。'}]
    before=deepcopy(row);payload=placement_payload(row)
    assert payload['context']==row['context'] and payload['provenance'][0]=={'source_url':'https://issuer.test/a'}
    assert payload['provenance'][1]==row['provenance'][1] and row==before


def test_knowledge_evidence_roundtrip_keeps_unknowns_scope_and_attribution_but_not_review_rationale():
    rows=[record(text='目标公司原值为0万元，数据期未知。',entity=TARGET,scope='target',period='未知'),
          record('I-child',text='子公司原值为5000万元。',entity='子公司',scope='subsidiary'),
          record('I-nav',text='不应作为公司事实检索的导航内容。')]
    rows[2]['decision']={'status':'exclude','reason':'纯导航内容，不形成公司事实。'}
    usage={'records':rows};content=render_annex(usage,{},TARGET)
    digest=hashlib.sha256(content.encode()).hexdigest();native=fingerprint([record_payload(r) for r in rows])
    text=knowledge_annex_text(content,digest,native)
    assert all(r['text'] in text for r in rows[:2]) and rows[2]['text'] not in text
    assert 'subsidiary' in text and 'https://foods.test/report' in text and 'period' in text
    with pytest.raises(ValueError):knowledge_annex_text(content+' changed',digest,native)
    altered=content.replace('https://foods.test/report','https://other.test/replaced')
    with pytest.raises(ValueError):knowledge_annex_text(altered,hashlib.sha256(altered.encode()).hexdigest(),native)


def test_changed_batch_sizing_preserves_exact_checked_groups_and_reviews_new_or_changed_inputs(monkeypatch):
    import report_agents.company_presentation as module
    rows=[record('I-a'),record('I-b',text='公司披露按章程保留完整会议记录。')]
    normal=module.presentation_batches
    monkeypatch.setattr(module,'presentation_batches',lambda records:iter([[r] for r in records]))
    def invoke(role,prompt,trace):
        native=json.JSONDecoder().raw_decode(prompt.split('资料：\n',1)[1])[0]
        return json.dumps(placements(native))
    previous=build_presentation({'records':rows},TARGET,SCOPE,invoke,workers=1)
    monkeypatch.setattr(module,'presentation_batches',normal)
    added=rows+[record('I-c',text='新增一条已接纳的原文信息，保持完整。')];calls=[]
    def tracked(role,prompt,trace):calls.append(role);return invoke(role,prompt,trace)
    package=build_presentation({'records':added},TARGET,SCOPE,tracked,previous=previous,workers=1)
    assert len(calls)==2 and sum(bool(b.get('reused')) for b in package['batches'])==2
    assert not package_errors(package,{'records':added},TARGET,SCOPE)
    changed=deepcopy(added);changed[0]['provenance'][0]['native_quote']='定位原文已改变。'
    calls.clear();build_presentation({'records':changed},TARGET,SCOPE,tracked,previous=package,workers=1)
    assert len(calls)==2  # full native hashes invalidate even fields omitted from the compact prompt
