"""Run the actual candidate caller in an isolated interpreter, not the live run."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from test_routing_journal import setup, journal, statement, decision, OUTLINE


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_candidate_production_caller_saves_native_batches_and_restores_without_whole_stage(monkeypatch):
    usage=load('report_agents._candidate_usage','company_information_usage.py')
    monkeypatch.setitem(sys.modules,'report_agents.company_information_usage',usage)
    monkeypatch.setitem(sys.modules,'report_agents.company_information_journal',journal)
    caller=load('report_agents._candidate_caller','company_report_agent.py')
    real_builder=usage.build_information_usage
    def serial_builder(*args,**kwargs):
        kwargs['workers']=1
        return real_builder(*args,**kwargs)
    monkeypatch.setattr(usage,'build_information_usage',serial_builder)
    project,store,_=setup()
    project.sources=[];project.target_type='company';project.title='测试公司报告';project.description=''
    statements=[statement('T-'+str(i),'平台披露岗位编号'+str(i)+'，不表示在岗人数。') for i in range(19)]
    monkeypatch.setenv('COMPANY_CORPUS_REVIEW_ENABLED','true')
    monkeypatch.setenv('COMPANY_CORPUS_COMPACT_WRITE_ENABLED','true')
    monkeypatch.setenv('COMPANY_DELIVERY_EDITORIAL_ENABLED','true')
    monkeypatch.setattr(caller,'build_corpus_review_with_recovery',lambda *a,**k:{'version':'synthetic-corpus','facts':[]})
    monkeypatch.setattr(caller,'collect_statements',lambda *a:statements)
    calls=[];phase_checkpoints=[]
    class StageSaved(BaseException):pass
    def stage(p,*a,**k):
        phase_checkpoints.append(bool(getattr(p,'company_information_usage_package',{})))
        if phase_checkpoints[-1]:raise StageSaved()
    monkeypatch.setattr('report_agents.company_checkpoint.checkpoint_generation_stage',stage)
    def invoke(role,prompt,trace):
        assert role=='公司信息逐项用途核对'
        rows=json.loads(prompt.rsplit('\n信息：\n',1)[1]);calls.append([r['information_id'] for r in rows])
        if len(calls)==2:raise SystemExit('interrupted before whole-stage checkpoint')
        return json.dumps({'records':[decision(r) for r in rows]})
    agent=caller.CompanyReportAgent()
    with pytest.raises(SystemExit):agent.generate(project,'{"facts":[]}','{}',invoke,lambda s,n:s[:n],lambda *a,**k:None)
    first_ids=set(calls[0])
    assert len(first_ids)==18 and True not in phase_checkpoints
    assert len(journal.read_decisions(project,usage.information_records(statements),OUTLINE))==18
    calls.clear()
    # generate clears transient packages itself; no full routing package is
    # supplied as previous cache. Only the genuinely saved batch is available.
    with pytest.raises(StageSaved):agent.generate(project,'{"facts":[]}','{}',invoke,lambda s,n:s[:n],lambda *a,**k:None)
    assert len(calls)==1 and set(calls[0]).isdisjoint(first_ids)
    package=project.company_information_usage_package
    assert package['diagnostic']['cached_journal_records']==18
    assert package['diagnostic']['pending_information_ids']==[]
    assert len(package['records'])==19 and not project.company_delivery_contract
