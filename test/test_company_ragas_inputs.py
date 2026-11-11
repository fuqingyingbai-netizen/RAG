import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('company_ragas',Path(__file__).resolve().parents[1]/'scripts/manual/evaluate_company_ragas.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)


def row():
    return {'question':'实际结算金额？','answer':'未披露实际结算；原文报价为占位符[id_2]。',
        'expected_answer':'当前资料没有实际结算金额。','references':[
            {'id':'1','text':'调查安排。','title':'同名文件'},
            {'id':'2','text':'咨询费：RMB xxx,000.00','title':'同名文件'}]}


def test_citation_probe_uses_only_actual_cited_fragment_not_same_file():
    value=row()
    assert evaluation.metric_inputs(value,'cited_faithfulness')['retrieved_contexts']==['咨询费：RMB xxx,000.00']
    assert len(evaluation.metric_inputs(value,'faithfulness')['retrieved_contexts'])==2
    value['answer']='答案[id_99]'
    with pytest.raises(ValueError):evaluation.metric_inputs(value,'cited_faithfulness')


def test_factual_metric_preserves_complete_response_and_reference():
    value=row();payload=evaluation.metric_inputs(value,'factual_correctness')
    assert payload=={'response':value['answer'],'reference':value['expected_answer']}
    assert evaluation.digest(payload)==evaluation.digest(dict(reversed(list(payload.items()))))


def test_uncited_refusal_is_not_a_perfect_citation_score():
    value=row();value.update(answer='资料未提供实际结算金额。',unanswerable=True)
    assert evaluation.metric_inputs(value,'cited_faithfulness') is None
    value['unanswerable']=False
    with pytest.raises(ValueError):evaluation.metric_inputs(value,'cited_faithfulness')
