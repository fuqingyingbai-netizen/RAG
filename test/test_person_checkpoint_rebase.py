import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/run_person_content_acceptance.py'
spec=importlib.util.spec_from_file_location('person_acceptance_resume_test',SCRIPT)
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


def fixture(tmp_path):
    folder=tmp_path/'prior';folder.mkdir()
    write=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8')
    claims=[{'analysis':'来源记载林知远在2022年度股东会上发表预期。','evidence_ids':['E-PREBASEONE']}]
    plan=[{'evidence_id':'E-PREBASEONE','quote':'召开2022年度股东会','reason':'真实待复核展示状态'}]
    code={'backend/person_evidence.py':'frozen-file-hash'};write(folder/'generation-code-snapshot.json',code)
    digest=hashlib.sha256(json.dumps(code,sort_keys=True).encode()).hexdigest()
    packet={'draft':claims,'source_display_quotes':[{'shown_evidence_id':r['evidence_id'],'quote':r['quote']} for r in plan]}
    entry={'input_sha256':'request-one','prompt':'材料诊断\n'+json.dumps(packet,ensure_ascii=False)}
    (folder/'chapter-model-inputs.jsonl').write_text(json.dumps(entry,ensure_ascii=False)+'\n',encoding='utf-8')
    write(folder/'contract.json',{'chapters':{'3':{'required_source_displays':plan}}})
    checkpoint={'chapter':3,'sources_sha256':'same-original-corpus','origin_inputs':str(folder/'chapter-model-inputs.jsonl'),
        'origin_code_snapshot':str(folder/'generation-code-snapshot.json'),'origin_generation_code_sha256':digest,
        'claims':claims,'origin_input_sha256':'request-one','required_source_displays':copy.deepcopy(plan)}
    cp=tmp_path/'automatic.json';write(cp,checkpoint)
    summary={'sources_sha256':'same-original-corpus','code_unchanged_during_run':True,
        'generation_code_sha256':digest,'automatic_checkpoint_sha256':'different-starting-file'}
    audit={'3':{'content_acceptance':{'last_validated_candidate':copy.deepcopy(claims),
        'material_diagnosis':{'status':'pending','counts':{'analysis':1,'pending':1}}}}}
    return folder,checkpoint,cp,summary,audit


def test_authentic_unchanged_final_candidate_can_continue_pending_review(tmp_path):
    folder,checkpoint,cp,summary,audit=fixture(tmp_path)
    assert runner.material_checkpoint_origin_binding(checkpoint,cp,summary,audit,folder)=='authenticated_last_validated_candidate_rebase'
    assert audit['3']['content_acceptance']['material_diagnosis']['status']=='pending'


def test_same_initial_checkpoint_keeps_legacy_binding(tmp_path):
    folder,checkpoint,cp,summary,audit=fixture(tmp_path)
    summary['automatic_checkpoint_sha256']=hashlib.sha256(cp.read_bytes()).hexdigest()
    assert runner.material_checkpoint_origin_binding(checkpoint,cp,summary,audit,folder)=='same_initial_automatic_checkpoint'


def test_coverage_request_with_exact_candidate_and_literal_plan_can_authenticate_rebase(tmp_path):
    folder,checkpoint,cp,summary,audit=fixture(tmp_path)
    packet={'draft':checkpoint['claims'],'tables':[{'representation':'literal_source_excerpt',
        'evidence_ids':[r['evidence_id']],'text':r['quote']} for r in checkpoint['required_source_displays']]}
    entry={'input_sha256':checkpoint['origin_input_sha256'],'prompt':'覆盖验收\n'+json.dumps(packet,ensure_ascii=False)}
    (folder/'chapter-model-inputs.jsonl').write_text(json.dumps(entry,ensure_ascii=False)+'\n',encoding='utf-8')
    assert runner.material_checkpoint_origin_binding(checkpoint,cp,summary,audit,folder)=='authenticated_last_validated_candidate_rebase'


@pytest.mark.parametrize('change',['origin','candidate','literal','code','raw_candidate','missing_validated_candidate'])
def test_changed_or_unproven_rebase_is_rejected(tmp_path,change):
    folder,checkpoint,cp,summary,audit=fixture(tmp_path)
    if change=='origin':checkpoint['origin_inputs']=str(tmp_path/'other.jsonl')
    elif change=='candidate':checkpoint['claims'][0]['analysis']='另一段人工文字。'
    elif change=='literal':checkpoint['required_source_displays'][0]['quote']='更改的原文。'
    elif change=='code':checkpoint['origin_generation_code_sha256']='different-code'
    elif change=='missing_validated_candidate':audit['3']['content_acceptance'].pop('last_validated_candidate')
    else:
        p=folder/'chapter-model-inputs.jsonl';entry=json.loads(p.read_text(encoding='utf-8'))
        entry['prompt']='材料诊断\n'+json.dumps({'draft':[],'source_display_quotes':[]});p.write_text(json.dumps(entry)+'\n',encoding='utf-8')
    with pytest.raises(AssertionError):runner.material_checkpoint_origin_binding(checkpoint,cp,summary,audit,folder)


def test_pending_literal_state_is_restored_only_from_current_admitted_originals(tmp_path):
    from person_content_acceptance import restore_literal_plan_from_checkpoint
    folder,checkpoint,cp,summary,audit=fixture(tmp_path)
    assert runner.material_checkpoint_origin_binding(checkpoint,cp,summary,audit,folder)=='authenticated_last_validated_candidate_rebase'
    prior=json.loads((folder/'contract.json').read_text(encoding='utf-8'))['chapters']['3']
    package={'facts':[{'evidence_id':'E-PREBASEONE','fact':'公司召开2022年度股东会。'}]}
    restore_literal_plan_from_checkpoint(package,prior)
    assert package['required_source_displays']==prior['required_source_displays']
    package['facts'][0]['fact']='不同原文。'
    with pytest.raises(ValueError):restore_literal_plan_from_checkpoint(package,prior)
