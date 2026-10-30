"""Produce a reviewable patch without modifying the live native runtime."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

here=Path(__file__).resolve().parent; root=here.parents[2]
assert (root/'backend/report_agents/company_information_usage.py').is_file()
caller_path='backend/report_agents/company_report_agent.py'
caller=(root/caller_path).read_text(encoding='utf-8')
old="""            usage=build_information_usage(digest,sections_by_index,self.outline,str(project.target_name),invoke,
                previous=getattr(project,'company_information_usage_cache',{}),review_scope=routing_scope(project),
                emit=emit,trace_emit=trace_emit)"""
new="""            from .company_information_journal import checkpoint_batch as checkpoint_routing, read_decisions as read_routing
            usage=build_information_usage(digest,sections_by_index,self.outline,str(project.target_name),invoke,
                previous=getattr(project,'company_information_usage_cache',{}),review_scope=routing_scope(project),
                emit=emit,trace_emit=trace_emit,
                receipt_callback=lambda batch:checkpoint_routing(project,batch,self.outline,emit,trace_emit),
                journal_loader=lambda rows:read_routing(project,rows,self.outline))"""
assert caller.count(old)==1
test=(here/'test_routing_journal.py').read_text(encoding='utf-8')
start="""spec = importlib.util.spec_from_file_location('routing_journal_prototype', Path(__file__).with_name('company_information_journal.py'))
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)"""
test=test.replace(start,'from report_agents import company_information_journal as journal')
old_builder="""    spec = importlib.util.spec_from_file_location('report_agents._usage_prototype',
        Path(__file__).with_name('company_information_usage.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.build_information_usage"""
test=test.replace(old_builder,'    from report_agents.company_information_usage import build_information_usage\n    return build_information_usage')
test=test.replace('import importlib.util\n','').replace('from pathlib import Path\n','')
changes={
    'backend/report_agents/company_information_journal.py':(here/'company_information_journal.py').read_text(encoding='utf-8'),
    'backend/report_agents/company_information_usage.py':(here/'company_information_usage.py').read_text(encoding='utf-8'),
    caller_path:caller.replace(old,new),
    'test/test_company_information_journal.py':test,
}
patch=[]; hashes={}
for path,after in changes.items():
    target=root/path; before=target.read_text(encoding='utf-8') if target.exists() else ''
    patch.append('diff --git a/'+path+' b/'+path+'\n')
    if not target.exists():patch.append('new file mode 100644\n')
    patch.extend(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),
        fromfile='a/'+path if target.exists() else '/dev/null',tofile='b/'+path))
    hashes[path]={'base_sha256':hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None,
                  'candidate_utf8_sha256':hashlib.sha256(after.encode()).hexdigest()}
data=''.join(patch).encode(); (here/'routing-recovery-candidate.patch').write_bytes(data)
(here/'candidate-manifest.json').write_text(json.dumps({
    'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
    'patch_sha256':hashlib.sha256(data).hexdigest(),'paths':hashes,
    'applied_to_backend':False,'production_caller_integration_test':'pending safe stage boundary',
    'real_report_acceptance':False},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'patch_prepared':True,'paths':len(changes),'backend_mutated':False}))
