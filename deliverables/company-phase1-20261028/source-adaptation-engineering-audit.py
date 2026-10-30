"""Bind pinned sources to exact tested native code, never to report approval."""
import ast,hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2];RUN=ROOT/'work/company-phase1-20261028'
OUT=ROOT/'deliverables/company-phase1-20261028'
COMMIT='c881cfe163f2f0d81b508469a4a80cc07101e96f'
def sha(data):return hashlib.sha256(data).hexdigest()
def blob(path):return subprocess.check_output(['git','show',COMMIT+':'+path],cwd=ROOT)

# These are inspected mechanisms and engineering choices. The map intentionally
# distinguishes native mechanisms retained after comparison from new goal work.
MAP={
 'assafelovic/gpt-researcher':{
  'design':'研究、编写、独立审稿和修订分离；本项目不采用修订次数耗尽即接受。',
  'origin':'已有原生双审与修复机制，经对标沿用；不宣称本轮复制上游实现。',
  'implementations':{'backend/report_agents/company_editorial.py':['build_editorial_package','validate_audit','document_review'],
                     'backend/report_agents/company_delivery_contract.py':['assess_delivery']},
  'tests':{'test_company_editorial':['test_partial_coverage_and_falsified_review_cannot_pass',
       'test_persistent_model_failure_remains_pending_and_never_fabricates_prose',
       'test_final_document_review_cannot_pass_on_invalid_or_unbound_issue',
       'test_final_editorial_receipts_are_rechecked_instead_of_trusting_green_counts']},
  'open':['三份真实报告的独立复核与全篇阅读证据尚未完成。']},
 'langchain-ai/open_deep_research':{
  'design':'研究问题、工具参数与停止条件绑定；单次恢复只补具体缺口，预算停止不授予通过。',
  'origin':'本目标已增加需求合同和专项恢复约束；跨轮无进展持久化门禁仍待接入。',
  'implementations':{'backend/company_requirements.py':['build_requirements','resume_gap_intake']},
  'tests':{'test_company_requirements':['test_every_real_company_checkbox_has_a_specific_question_and_original_contract',
       'test_resume_uses_only_specific_gaps_without_mutating_intake_or_claiming_acceptance',
       'test_real_resume_and_collector_pass_only_gap_queries_with_requirement_ids']},
  'open':['跨轮无进展的持久化门禁尚未实现。','真实问题与原件采用回执仍须在三个最终报告中核对。']},
 'stanford-oval/storm':{
  'design':'问题驱动查询、去重和有界深入；不采用首条摘要或固定字数裁剪代替全报告采用核查。',
  'origin':'本目标需求查询绑定与去重，保留项目既有完整原文及字段语义审核。',
  'implementations':{'backend/company_requirements.py':['bind_queries','resume_gap_intake'],
                     'backend/report_agents/company_information_usage.py':['information_records','routing_fingerprint']},
  'tests':{'test_company_requirements':['test_resume_uses_only_specific_gaps_without_mutating_intake_or_claiming_acceptance'],
       'test_company_information_usage':['test_same_text_different_url_is_one_information_with_every_source',
       'test_different_fields_periods_and_numeric_precision_are_not_fuzzy_duplicates']},
  'open':['两个开发报告及保留样本中限定语、相反信息和财务期间的最终正文核验待完成。']},
 'duhu2000/financial-services-qcc':{
  'design':'将主体、治理和风险问题映射到工具参数、预期原件字段和章节；不把第三方技能示例视为官方能力或既成事实。',
  'origin':'本目标需求 ID 到已有工具精确参数和调用回执的关联。',
  'implementations':{'backend/company_requirements.py':['build_requirements','platform_requirement_ids']},
  'tests':{'test_company_requirements':['test_platform_mapping_requires_the_actual_target_and_aspect',
       'test_actual_xiniu_aspect_label_binds_only_matching_arguments_and_preserves_the_label',
       'test_unexecuted_planned_tools_remain_requirement_gaps_without_invented_arguments',
       'test_platform_quota_failure_remains_a_collection_gap_linked_to_the_question']},
  'open':['工具与模型的真实可用性仍须由当前三个真实运行回执分别证明。']},
 'alephdata/followthemoney':{
  'design':'主体、关系、时间与文档证据分层；不由股权或交易对手关系推断目标公司的保证义务。',
  'origin':'沿用原生治理与证据图谱，本目标收紧短别名、目标主体和交易对手混淆的边界。',
  'implementations':{'backend/report_agents/company_governance.py':['build_governance_package'],
                     'backend/report_agents/company_issuer_identity.py':['build_issuer_identity']},
  'tests':{'test_company_governance':['test_duplicate_snapshot_removed_but_distinct_dates_remain',
       'test_subsidiary_statement_and_generic_charter_rules_never_create_control_edges',
       'test_uncompleted_capital_reduction_is_not_reported_as_completed_event']},
  'open':['关系有效期、责任主体及完整报告判断仍需真实原件和最终正文复核。']},
 'rgerjeki/Dossier':{
  'design':'采集归档状态、来源评价与采用去向分列；included 或已归档不等同于事实或报告通过。',
  'origin':'沿用原生采集去向审计和逐信息采用账本；人工复核定位仍须真实交付补齐。',
  'implementations':{'backend/company_collection_audit.py':['CollectionAudit.candidate','CollectionAudit.observe','CollectionAudit.snapshot'],
                     'backend/report_agents/company_information_usage.py':['finalize_usage']},
  'tests':{'test_company_collection_audit':['test_deferred_candidate_remains_auditable_and_is_not_labelled_irrelevant',
       'test_real_collector_can_admit_a_primary_for_an_uncovered_module_after_another_module_deferred_it']},
  'open':['人工复核清单的来源到正文定位，以及三份完整报告复核尚待实际完成。']},
 'openaleph/openaleph':{
  'design':'内容哈希与文档版本索引；原件、发现与结论保持可追溯，不宣称自动风险评级。',
  'origin':'沿用原生内容哈希检查点；本目标新增逐信息原生用途判定回执的内容索引与严格恢复。',
  'implementations':{'backend/report_agents/company_checkpoint.py':['save_generation_checkpoint','read_generation_checkpoint'],
                     'backend/report_agents/company_information_journal.py':['checkpoint_batch','read_decisions']},
  'tests':{'test_company_checkpoint':['test_immutable_payload_must_match_pointer_hash',
       'test_changed_original_or_research_scope_does_not_load_checkpoint'],
       'test_company_information_journal':['test_completed_batch_survives_without_whole_stage_or_delivery_approval',
       'test_current_input_scope_and_template_are_revalidated',
       'test_real_builder_resumes_completed_batch_after_phase_interrupt_without_recalling_it']},
  'open':['逐批恢复机制的真实恢复运行与原生回执观察尚待完成。','最终报告的事实与引用定位、逐条采用及全部导出验证待完成。']},
}

def functions(path,names):
    data=blob(path);tree=ast.parse(data.decode('utf-8'));result=[]
    actual=(RUN/'routing-candidate-overlay'/path) if (RUN/'routing-candidate-overlay'/path).is_file() else ROOT/path
    assert sha(actual.read_bytes())==sha(data), 'Tested implementation differs: '+path
    for name in names:
        nodes=tree.body
        for part in name.split('.'):
            matches=[n for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==part]
            assert len(matches)==1,(path,name)
            node=matches[0];nodes=node.body
        result.append({'symbol':name,'start_line':node.lineno,'end_line':node.end_lineno})
    return {'path':path,'git_commit':COMMIT,'sha256':sha(data),'symbols':result}

def main():
    xml_path=OUT/'test-results/routing-recovery-full-20261030.xml'
    xml=ET.parse(xml_path).getroot();cases=list(xml.iter('testcase'));rows=[]
    for pin in json.loads((OUT/'upstream-source-index.json').read_text(encoding='utf-8')):
        repository=pin['repository'].removeprefix('https://github.com/');entry=MAP[repository]
        folder=RUN/'upstream'/repository.replace('/','--');files=[]
        for kind in ['license_files','selected_files']:
            for item in pin.get(kind,[]):
                path=folder/('selected' if kind=='selected_files' else '')/item['path']
                assert sha(path.read_bytes())==item['sha256']
                files.append({'kind':kind,'path':item['path'],'sha256':item['sha256']})
        tests=[]
        for module,names in entry['tests'].items():
            for name in names:
                found=[t for t in cases if t.get('classname','').split('.')[-1]==module
                       and t.get('name','').split('[',1)[0]==name]
                assert found,(module,name)
                assert all(not any(t.find(k) is not None for k in ['failure','error','skipped']) for t in found)
                tests.extend({'classname':t.get('classname'),'name':t.get('name'),'result':'passed'} for t in found)
        rows.append({'repository':pin['repository'],'upstream_commit':pin['commit'],'pinned_files_reverified':files,
            'design':entry['design'],'native_origin_and_change_boundary':entry['origin'],
            'implementations':[functions(path,names) for path,names in entry['implementations'].items()],
            'specific_passed_test_cases':tests,'remaining_evidence':entry['open'],
            'real_case_acceptance':{'haitian':False,'kingsoft':False,'holdout':False}})
    result={'at':datetime.now(timezone.utc).isoformat(),'scope':'engineering source/implementation/test correspondence only',
        'generator_sha256':sha(Path(__file__).read_bytes()),
        'candidate_commit':COMMIT,
        'candidate_promoted':subprocess.run(['git','merge-base','--is-ancestor',COMMIT,'HEAD'],cwd=ROOT).returncode==0,
        'rows':rows,
        'regression_xml_sha256':sha(xml_path.read_bytes()),'network_calls':0,'model_calls':0,
        'third_party_runtime_dependency_added':False,'upstream_source_copied_into_runtime':False,
        'full_report_acceptance':False,'goal_complete':False}
    destination=RUN/'source-adaptation-engineering-proof-20261030.json'
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'source_repositories':len(rows),'reverified_files':sum(len(r['pinned_files_reverified']) for r in rows),
        'specific_test_links':sum(len(r['specific_passed_test_cases']) for r in rows),
        'candidate_promoted':result['candidate_promoted'],'goal_complete':False}))

if __name__=='__main__':main()
