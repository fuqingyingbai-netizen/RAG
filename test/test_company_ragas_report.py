import importlib.util
from copy import deepcopy
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('ragas_report',Path(__file__).resolve().parents[1]/'scripts/manual/report_company_ragas.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)


def test_report_keeps_unanswerable_out_of_positive_metric_denominators():
    rows=[{'id':'A','split':'development','factual_recall':0.5},
        {'id':'B','split':'holdout','factual_recall':1.0},
        {'id':'C','split':'holdout'}]
    assert report.aggregate(rows)['factual_recall']=={'count':2,'mean':0.75}
    assert report.aggregate(rows,'holdout')['factual_recall']=={'count':1,'mean':1.0}
    assert report.aggregate(rows)['faithfulness']=={'count':0,'mean':None}


def controlled_inputs():
    config={'model':'glm-5.3-flash','endpoint_sha256':'official','options':{'reasoning_effort':'low'}}
    row={'generation_config':config,'selection_source_sha256':'selection','generation_source_sha256':'baseline'}
    return {'baseline':[deepcopy(row)],'improved':[{**deepcopy(row),'generation_source_sha256':'candidate'}]},\
        {'commit':'frozen','selection_source_sha256':'selection','generation_source_sha256':'baseline'},\
        {'kind':'controlled_same_provider','baseline_commit':'frozen','config':deepcopy(config)}


def test_controlled_report_accepts_same_generation_provider_with_changed_prompt():
    report.validate_generation_provenance(*controlled_inputs())


@pytest.mark.parametrize('field,value',[('model','other-model'),('endpoint_sha256','relay'),('options',{})])
def test_controlled_report_rejects_model_endpoint_or_options_changes(field,value):
    inputs,lock,provenance=controlled_inputs();inputs['improved'][0]['generation_config'][field]=value
    with pytest.raises(AssertionError,match='provider/options'):report.validate_generation_provenance(inputs,lock,provenance)


def test_controlled_report_rejects_changed_baseline_source():
    inputs,lock,provenance=controlled_inputs();inputs['baseline'][0]['generation_source_sha256']='other-code'
    with pytest.raises(AssertionError,match='Baseline generation'):report.validate_generation_provenance(inputs,lock,provenance)


def test_citation_probe_summary_preserves_low_scores_and_excludes_not_applicable():
    assert report.aggregate_probes([{'status':'completed','value':0.25},
        {'status':'completed','value':0.75},{'status':'not_applicable','value':None}])=={'count':2,'mean':0.5}
    assert report.aggregate_probes([{'status':'not_applicable','value':None}])=={'count':0,'mean':None}
