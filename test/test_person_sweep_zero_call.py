import importlib.util,json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/"backend"),str(Path.cwd()/"scripts")]
from pathlib import Path
spec=importlib.util.spec_from_file_location("staged_sweep",Path(__file__).resolve().parents[1]/"scripts/run_person_report_sweep.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_zero_call_prior_run_has_no_fabricated_recovery(tmp_path):
    assert m.authentic_candidate(tmp_path,8,tmp_path/'feedback.json',tmp_path/'candidate.json')==(None,None)
    assert not (tmp_path/'candidate.json').exists()

def test_empty_raw_history_has_no_fabricated_recovery(tmp_path):
    (tmp_path/'acceptance-results.json').write_text(json.dumps({'8':{'content_acceptance':{'status':'passed_without_targeted_repair'}}}),encoding='utf-8')
    (tmp_path/'contract.json').write_text(json.dumps({'chapters':{'8':{}}}),encoding='utf-8')
    (tmp_path/'chapter-model-inputs.jsonl').write_text('',encoding='utf-8')
    assert m.authentic_candidate(tmp_path,8,tmp_path/'feedback.json',tmp_path/'candidate.json')==(None,None)
    assert not (tmp_path/'candidate.json').exists()


def test_passed_body_never_rolls_back_to_an_older_raw_candidate(tmp_path):
    (tmp_path/'acceptance-results.json').write_text(json.dumps({'9':{'status':'passed_after_targeted_repair','content_acceptance':{'last_validated_candidate':[{'analysis':'Published source-supported final text.'}]}}}),encoding='utf-8')
    (tmp_path/'chapter-model-inputs.jsonl').write_text('old candidate history must not be read',encoding='utf-8')
    assert m.authentic_candidate(tmp_path,9,tmp_path/'feedback.json',tmp_path/'candidate.json')==(None,None)
    assert not (tmp_path/'candidate.json').exists()
