"""Reader placeholders and confused source locators cannot become approvals."""
import json
from copy import deepcopy

import pytest

from report_agents.company_editorial import (
    build_editorial_package,parse_proposal,prose_errors,proposal_prompt,package_errors,
)
from test_company_editorial import record,proposal,invoke_for,OUTLINE


@pytest.mark.parametrize('empty',['“”','“  ”','「」','『\n』','《 》'])
def test_empty_entity_and_document_placeholders_require_readable_explanation(empty):
    row=record(text='公司是'+empty+'注册商标的权利人，提取内容未呈现图样。')
    assert 'empty_quote_placeholder' in prose_errors(row['text'],[row])
    clear='公司是注册商标的权利人，提取内容未呈现图样。'
    assert not prose_errors(clear,[row])
    prompt=proposal_prompt([row],'远帆公司',6,'业务')
    assert json.loads(prompt.split('材料：\n',1)[1])[0]['text']==row['text']


def test_nonempty_source_quotes_names_and_unknown_values_are_not_placeholders():
    for text in ['公司“青禾”商标获准注册。','原文载明“未知”，不能据此认定为零。','该参数为空字符串。']:
        assert not prose_errors(text,[record(text=text)])


@pytest.mark.parametrize('ids',[['I-a-P1'],['I-a-M1'],['I-other'],['I-a','I-a']])
def test_bad_record_ids_get_fresh_full_context_response_and_independent_review(ids):
    rows=[record()];calls=[];base=invoke_for(rows)
    bad=proposal(rows);bad['findings'][0]['information_ids']=ids
    def invoke(role,prompt,trace):
        calls.append((role,prompt))
        if role=='公司交付正文编写':return json.dumps(bad)
        if role=='公司交付信息编号格式重核':return json.dumps(proposal(rows))
        return base(role,prompt,trace)
    result=build_editorial_package({'records':rows},OUTLINE,'远帆公司',invoke,workers=1)
    assert not package_errors(result,rows,'远帆公司')
    assert [role for role,_ in calls]==['公司交付正文编写','公司交付信息编号格式重核','公司交付正文独立审稿']
    assert rows[0]['text'] in calls[1][1] and 'proposition_id' in calls[1][1]
    check=result['batches'][0]['attempts'][0]['information_id_recheck']
    assert check['original_proposal']['findings'][0]['information_ids']==ids
    assert check['revised_proposal']['findings'][0]['information_ids']==['I-a']
    assert not check['revised_errors']


def test_repeated_bad_ids_are_never_canonically_guessed_or_accepted():
    rows=[record()];calls=[];bad=proposal(rows);bad['findings'][0]['information_ids']=['I-a-P1']
    def invoke(role,prompt,trace):calls.append(role);return json.dumps(bad)
    result=build_editorial_package({'records':rows},OUTLINE,'远帆公司',invoke,workers=1)
    assert result['diagnostic']['pending_information_ids']==['I-a'] and not result['findings']
    assert calls.count('公司交付信息编号格式重核')==3
    assert '公司交付正文独立审稿' not in calls
    assert package_errors(result,rows,'远帆公司')


def test_source_id_format_retry_does_not_waive_fresh_negative_semantic_verdict():
    rows=[record()];base=invoke_for(rows);calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':
            bad=proposal(rows);bad['findings'][0]['information_ids']=['I-a-P1'];return json.dumps(bad)
        if role=='公司交付信息编号格式重核':return json.dumps(proposal(rows))
        answer=json.loads(base(role,prompt,trace))
        if role=='公司交付正文独立审稿':
            answer['criteria']['factual_support']=False
            answer['findings'][0]['status']='unsupported';answer['issues']=['该段主体与来源口径不一致。']
        return json.dumps(answer)
    result=build_editorial_package({'records':rows},OUTLINE,'远帆公司',invoke,workers=1)
    assert not result['findings'] and result['diagnostic']['failed_batches']==1
    assert calls.count('公司交付正文独立审稿')==3


def test_changed_cached_empty_placeholder_needs_new_writer_and_complete_review():
    rows=[record(text='公司为注册商标权利人。')];base=invoke_for(rows)
    old=build_editorial_package({'records':rows},OUTLINE,'远帆公司',base,workers=1)
    old=deepcopy(old)
    for finding in old['batches'][0]['findings']:finding['text']='公司为“”注册商标权利人。'
    calls=[]
    result=build_editorial_package({'records':rows},OUTLINE,'远帆公司',invoke_for(rows,calls),previous=old,workers=1)
    assert not result['batches'][0].get('reused') and len(calls)==2
    assert not package_errors(result,rows,'远帆公司')
