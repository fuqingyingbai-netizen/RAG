import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('ragas_report',Path(__file__).resolve().parents[1]/'scripts/manual/report_company_ragas.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)


def test_report_keeps_unanswerable_out_of_positive_metric_denominators():
    rows=[{'id':'A','split':'development','factual_recall':0.5},
        {'id':'B','split':'holdout','factual_recall':1.0},
        {'id':'C','split':'holdout'}]
    assert report.aggregate(rows)['factual_recall']=={'count':2,'mean':0.75}
    assert report.aggregate(rows,'holdout')['factual_recall']=={'count':1,'mean':1.0}
    assert report.aggregate(rows)['faithfulness']=={'count':0,'mean':None}
