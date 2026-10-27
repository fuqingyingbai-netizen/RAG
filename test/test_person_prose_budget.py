"""More sources/findings may support concise prose without count truncation."""
import json

from person_evidence import validate_model_claims
from person_material_review import presentation_facts, read_then_write
from person_material_tables import distinct_inherited_analyses
from person_prose_budget import compact_draft, enforce_budget, prose_chars
from test_person_complete_material import facts


def test_validation_keeps_more_than_sixteen_short_source_bound_findings():
    package = {**facts(20), 'writing_contract': 'evidence_selection_v2'}
    package['facts'] = package['research_facts']
    rows = [{'evidence_ids': [f['evidence_id']],
             'analysis': '来源记载历史任职，不证明当前职责。'} for f in package['facts']]
    accepted, rejected = validate_model_claims(json.dumps({'claims': rows}), package)
    assert not rejected and len(accepted) == 20
    published, audit = enforce_budget(accepted, 9)
    assert len(published) == 20 and audit['published_chars'] <= 600


def test_quote_budget_allows_more_than_four_sources_and_never_cuts_originals():
    rows = [{'evidence_id': str(i), 'fact': f'第{i}份来源原文，各有独立事项。',
             'source_url': f'https://fixture.invalid/{i}'} for i in range(8)]
    package = {'facts': rows, 'research_facts': rows}
    claims = [{'analysis': '合并结论', 'evidence_ids': [r['evidence_id'] for r in rows]}]
    assert presentation_facts(package, claims) == rows
    assert package['quotation_budget']['max_records'] is None
    huge = {**rows[0], 'fact': '完整的超长原文。' * 300}
    package = {'facts': [huge, *rows[1:]], 'research_facts': [huge, *rows[1:]]}
    shown = presentation_facts(package, claims)
    assert huge not in shown and sum(len(r['fact']) for r in shown) <= 1600
    assert package['research_facts'][0] == huge
    assert huge['evidence_id'] in package['quotation_budget']['undisplayed_evidence_ids']


def test_synthesis_gets_every_original_even_when_research_proposes_nothing(monkeypatch):
    monkeypatch.setenv('PERSON_RESEARCH_BATCH_CHARS', '4000')
    package = {**facts(80), 'writing_contract': 'evidence_selection_v2'}
    rows = [{'evidence_id': f['evidence_id'], 'fact': f['fact']} for f in package['research_facts']]
    received = []
    def invoke(role, prompt, emit):
        data = json.loads(prompt.splitlines()[-1])
        if role.endswith('综合写作'):
            received.extend(data['facts'])
            assert not data['research_findings']
            return json.dumps({'claims': [{'evidence_ids': [rows[-1]['evidence_id']],
                'analysis': '来源记载历史任职，不证明当前职责。'}]})
        assert '研读阶段不限制判断条数' in prompt
        return '{"claims":[]}'
    answer, calls = read_then_write('章节', '仅用原文。\n', {'chapter': 9, 'facts': rows},
        package, invoke, None, validate_model_claims)
    assert [{'evidence_id':r['evidence_id'],'fact':r['fact']} for r in received] == rows
    assert json.loads(answer)['claims'][0]['evidence_ids'] == [rows[-1]['evidence_id']]
    assert calls == len(package['material_review']['batches']) + 1
    assert package['material_review']['synthesis']['input_evidence_ids'] == [r['evidence_id'] for r in rows]


def test_oversized_draft_is_compressed_with_all_originals_then_validated():
    rows = [{'evidence_id': str(i), 'fact': '原始资料'} for i in range(7)]
    draft = {'claims': [{'analysis': '待压缩的重复内容。' * 70, 'evidence_ids': ['0']}]}
    received = []
    def invoke(role, prompt, emit):
        data = json.loads(prompt.splitlines()[-1])
        received.extend(data['facts'])
        assert '不限制分析条数或来源数量' in prompt
        return json.dumps({'claims': [{'analysis': '来源载明各项安排，适用条件见原文。',
                                       'evidence_ids': [r['evidence_id'] for r in rows]}]})
    audit = {}
    result, calls = compact_draft(json.dumps(draft), '章节', '', {'chapter': 9, 'facts': rows},
                                  invoke, None, audit)
    assert calls == 1 and received == rows
    assert prose_chars(json.loads(result)['claims']) <= 600
    assert audit['compression']['status'] == 'returned_for_validation'


def test_post_repair_overflow_is_explicit_and_retains_complete_draft():
    original = [{'analysis': '来源称这是历史安排，须满足先决条件。' * 40, 'evidence_ids': ['a', 'b']}]
    result, audit = enforce_budget(original, 5)
    assert audit['status'] == 'oversized_draft_withheld_for_review'
    assert audit['withheld_claims'] == original
    assert prose_chars(result) == 0
    assert result[0]['evidence_ids'] == ['a', 'b']
    assert original[0]['analysis'].endswith('须满足先决条件。')


def test_summary_uses_character_budget_instead_of_three_findings_or_one_per_chapter():
    rows = [{'analysis': '不同事项' + str(i), 'evidence_ids': [str(i)]} for i in range(8)]
    selected = distinct_inherited_analyses({5: rows}, [5], max_chars=300)
    assert len(selected) == 8
    assert not distinct_inherited_analyses({5: rows}, [5], max_chars=1)


def test_compaction_remeasures_the_same_candidate_before_retrying_and_keeps_all_originals():
    rows=[{'evidence_id':'E-TEST0001','fact':'完整的原始来源以及限定条件。'}];seen=[]
    draft={'claims':[{'analysis':'来源所载的不同事项。'*70,'evidence_ids':['E-TEST0001']}]}
    def invoke(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1]);seen.append(data)
        assert data['facts']==rows
        if len(seen)==1:return json.dumps(draft)
        assert data['measured_analysis_chars']==prose_chars(draft['claims'])
        return json.dumps({'claims':[{'analysis':'来源所载的不同事项，限定条件见原文。','evidence_ids':['E-TEST0001']}]})
    audit={};answer,calls=compact_draft(json.dumps(draft),'章节','',{'chapter':5,'facts':rows},invoke,None,audit)
    assert calls==2 and prose_chars(json.loads(answer)['claims'])<=600
    assert len(audit['compression']['attempts'])==2


def test_compaction_limit_does_not_turn_an_oversized_candidate_into_a_pass():
    draft={'claims':[{'analysis':'来源所载的不同事项。'*70,'evidence_ids':['E-TEST0001']}]};calls=[]
    def invoke(*a):calls.append(a);return json.dumps(draft)
    answer,count=compact_draft(json.dumps(draft),'章节','',{'chapter':5,'facts':[]},invoke,None,{})
    claims,audit=enforce_budget(json.loads(answer)['claims'],5)
    assert count==len(calls)==3 and audit['status']=='oversized_draft_withheld_for_review'
    assert not prose_chars(claims) and audit['withheld_claims']==draft['claims']


def test_compaction_has_headroom_but_still_withholds_a_601_character_candidate():
    draft={'claims':[{'analysis':'字'*601,'evidence_ids':['E-TEST0001']}]};seen=[];audit={}
    def invoke(role,prompt,emit):
        seen.append(prompt)
        packet=json.loads(prompt.splitlines()[-1]);target=packet.get('target_analysis_chars',570)
        assert 0<target<=570 and f'{target}字符以内' in prompt and '不得超过600字符' in prompt
        return json.dumps(draft)
    answer,calls=compact_draft(json.dumps(draft),'章节','',{'chapter':5,'facts':[]},invoke,None,audit)
    assert audit['compression']['target_analysis_chars']==570
    assert audit['compression']['max_analysis_chars']==600 and calls==3
    published,final=enforce_budget(json.loads(answer)['claims'],5)
    assert final['status']=='oversized_draft_withheld_for_review'
    assert not prose_chars(published) and final['withheld_claims']==draft['claims']
