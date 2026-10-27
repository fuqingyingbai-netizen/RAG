import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('complete_source_review_test',Path(__file__).resolve().parents[1]/'scripts/run_person_content_acceptance.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


def test_source_repair_reviews_unchanged_paragraphs_as_well_as_the_repaired_one(monkeypatch):
    old={'analysis':'其于2002年投入动力电池。','evidence_ids':['E-PINVESTONE']}
    changed={'analysis':'2022年度股东会其发表预期。','evidence_ids':['E-PMEETINGTWO']}
    facts=[{'evidence_id':eid,'analysis_allowed':True} for eid in old['evidence_ids']+changed['evidence_ids']]
    package={'chapter':3,'title':'人格特质','facts':facts};seen=[]
    def review(n,title,eligible,claims,invoke,**kwargs):
        seen.append(list(claims));assert claims==[old,changed]
        return claims,['semantic_inference_requires_review'],{'status':'old_company_actor_requires_correction'}
    def repair(n,title,eligible,before,claims,errors,audit,p,writing,invoke,emit,validate,**kwargs):
        assert before==[old,changed] and seen==[[old,changed]]
        return [{**old,'analysis':'公司于2002年投入动力电池。'},changed],[],{'status':'reviewed'}
    monkeypatch.setattr(runner,'review_analyses',review);monkeypatch.setattr(runner,'repair_semantic_findings',repair)
    final,errors,audit=runner.review_complete_candidate(package,facts,[old,changed],{},None,'来源修订后完整语义复核')
    assert not errors and final[1]==changed and final[0]['analysis'].startswith('公司')
