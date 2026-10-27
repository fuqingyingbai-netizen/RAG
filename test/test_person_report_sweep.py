import hashlib,importlib.util,json
from pathlib import Path

spec=importlib.util.spec_from_file_location('report_sweep_test',Path(__file__).resolve().parents[1]/'scripts/run_person_report_sweep.py')
sweep=importlib.util.module_from_spec(spec);spec.loader.exec_module(sweep)


def fixture(tmp_path):
    run=tmp_path/'run';run.mkdir();write=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8')
    claims=[{'analysis':'林知远介绍工程师文化。','evidence_ids':['E-PSWEEPONE']}]
    quotes=[{'evidence_id':'E-PSWEEPONE','quote':'介绍工程师文化'}]
    packet={'draft':claims,'source_display_quotes':[{'shown_evidence_id':q['evidence_id'],'quote':q['quote']} for q in quotes]}
    (run/'chapter-model-inputs.jsonl').write_text(json.dumps({'input_sha256':'authentic-input','prompt':'材料核对\n'+json.dumps(packet,ensure_ascii=False)})+'\n',encoding='utf-8')
    write(run/'acceptance-results.json',{'3':{'content_acceptance':{'last_validated_candidate':claims}}})
    write(run/'contract.json',{'chapters':{'3':{'required_source_displays':quotes}}})
    write(run/'summary.json',{'sources_sha256':'fixed-original-sources','generation_code_sha256':'actual-prior-code'})
    feedback=tmp_path/'feedback.json';write(feedback,{'records':[]})
    return run,claims,feedback


def test_exact_archived_candidate_restores_audit_only_for_matching_final_literal_plan(tmp_path):
    run,claims,feedback=fixture(tmp_path)
    cp,audit=sweep.authentic_candidate(run,3,feedback,tmp_path/'cp.json')
    result=json.loads(cp.read_text(encoding='utf-8'))
    assert result['claims']==claims and audit==run/'acceptance-results.json'
    assert result['claims_sha256']==hashlib.sha256(json.dumps(claims,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def test_different_final_candidate_uses_actual_material_input_without_rebinding_audit(tmp_path):
    run,claims,feedback=fixture(tmp_path);p=run/'acceptance-results.json'
    a=json.loads(p.read_text(encoding='utf-8'));a['3']['content_acceptance']['last_validated_candidate']=[];p.write_text(json.dumps(a),encoding='utf-8')
    cp,audit=sweep.authentic_candidate(run,3,feedback,tmp_path/'cp.json')
    assert not audit and json.loads(cp.read_text(encoding='utf-8'))['claims']==claims


def test_no_material_request_never_creates_a_candidate(tmp_path):
    run,claims,feedback=fixture(tmp_path);(run/'chapter-model-inputs.jsonl').write_text('',encoding='utf-8')
    assert sweep.authentic_candidate(run,3,feedback,tmp_path/'cp.json')==(None,None)
    assert not (tmp_path/'cp.json').exists()


def test_actual_coverage_request_preserves_the_latest_candidate_and_exact_literal_state(tmp_path):
    run,claims,feedback=fixture(tmp_path);p=run/'chapter-model-inputs.jsonl';entry=json.loads(p.read_text(encoding='utf-8'))
    entry['prompt']='覆盖验收\n'+json.dumps({'draft':claims,'tables':[{'representation':'literal_source_excerpt',
        'text':'介绍工程师文化','evidence_ids':['E-PSWEEPONE']}]},ensure_ascii=False)
    p.write_text(json.dumps(entry,ensure_ascii=False)+'\n',encoding='utf-8')
    cp,audit=sweep.authentic_candidate(run,3,feedback,tmp_path/'cp.json')
    assert audit==run/'acceptance-results.json' and json.loads(cp.read_text(encoding='utf-8'))['claims']==claims


def test_cache_keeps_unreturned_request_without_inventing_response(tmp_path):
    origin=tmp_path/'origin';origin.mkdir();request='{"role":"真实请求","prompt":"源输入"}\n'
    (origin/'chapter-model-inputs.jsonl').write_text(request,encoding='utf-8')
    sweep.raw_cache(tmp_path/'cache',[origin])
    assert (tmp_path/'cache/chapter-model-inputs.jsonl').read_text(encoding='utf-8')==request
    assert not (tmp_path/'cache/chapter-model-responses.jsonl').read_text(encoding='utf-8').strip()
    assert not (tmp_path/'cache/audit.json').exists()
