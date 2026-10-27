"""Real checkpoint JSON ordering must not invalidate unchanged source witnesses."""
import json
from copy import deepcopy
from report_agents.company_checkpoint import encode
from report_agents.company_main_focus import build_main_focus,focus_prompt,package_errors,validate_focus_batch
from report_agents.company_presentation import build_presentation
from test_company_editorial import record
from test_company_main_focus_delivery import native_answers
from test_company_presentation import TARGET,SCOPE,placements


def prepared():
    row=record(text='公司披露新产品已交付。该产线尚未完成验收。')
    row['context']={'z_nested_scope':{'z':'parent','a':'disclosed'},**row['context'],'a_zero':0}
    row['provenance'][0]={'z_nested_origin':{'z':'original','a':'page'},**row['provenance'][0]}
    usage={'records':[row]};scope={'z_conditions':{'z':0,'a':'unknown'},**SCOPE,'a_scope':'target'}
    placement=build_presentation(usage,TARGET,scope,lambda *a:json.dumps(placements([row],'main')),workers=1)
    focus=build_main_focus(usage,placement,TARGET,scope,lambda *a:json.dumps(native_answers([row])),workers=1)
    return usage,placement,focus,scope


def test_sorted_checkpoint_roundtrip_keeps_exact_prompt_and_independent_receipts_reusable():
    usage,placement,focus,scope=prepared()
    restored=json.loads(encode({'usage':usage,'placement':placement,'focus':focus,'scope':scope}))
    assert restored['usage']==usage and restored['scope']==scope
    assert list(restored['usage']['records'][0]['context'])!=list(usage['records'][0]['context'])
    assert focus_prompt(usage['records'],TARGET,scope)==focus_prompt(restored['usage']['records'],TARGET,restored['scope'])
    assert not package_errors(restored['focus'],restored['usage'],restored['placement'],TARGET,restored['scope'])
    choices,errors=validate_focus_batch(restored['usage']['records'],restored['focus']['batches'][0],TARGET,restored['scope'])
    assert choices and not errors
    def unexpected(*args):raise AssertionError('Unchanged restored witnesses must reuse without model calls.')
    resumed=build_main_focus(restored['usage'],restored['placement'],TARGET,restored['scope'],unexpected,
                             previous=restored['focus'],workers=1)
    assert resumed['batches'][0]['reused'] and not package_errors(resumed,restored['usage'],restored['placement'],TARGET,restored['scope'])
    assert resumed['batches'][0]['attempts']==focus['batches'][0]['attempts']


def test_canonical_order_does_not_allow_a_changed_source_value_to_reuse():
    usage,placement,focus,scope=prepared();altered=deepcopy(usage)
    altered['records'][0]['context']['z_nested_scope']['z']='subsidiary'
    assert package_errors(focus,altered,placement,TARGET,scope)
    altered=deepcopy(scope);altered['z_conditions']['z']=1
    assert package_errors(focus,usage,placement,TARGET,altered)


def test_old_order_sensitive_focus_contract_requires_fresh_independent_calls():
    usage,placement,focus,scope=prepared();old=deepcopy(focus)
    old['version']='company-main-focus-v1-source-bound-facts';calls=[]
    def invoke(role,prompt,trace):
        calls.append(role);return json.dumps(native_answers(usage['records']))
    current=build_main_focus(usage,placement,TARGET,scope,invoke,previous=old,workers=1)
    assert calls==['公司主报告事实选择','公司主报告事实选择独立审稿']
    assert not package_errors(current,usage,placement,TARGET,scope)
