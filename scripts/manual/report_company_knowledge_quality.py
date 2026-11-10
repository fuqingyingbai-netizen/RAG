"""Build a private HTML/JSON acceptance report without calling any model."""
import argparse
import ast
from collections import Counter
from html import escape
import json
import hashlib
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from company_quality import summary

# Set before inspecting final holdout results. These are project gates, not
# claims that a 100-question sample establishes population-wide accuracy.
GATES={'holdout_answer_correct':.90,'holdout_faithful':.95,'holdout_citation_supported':.95,
       'unanswerable_refusal_correct':1.0,'max_errors':0,'max_invalid_citations':0}


def generation_integration(reference, current):
    """Prove only already-reviewed department upload/selection endpoints changed.

    Never permit prompt, retrieval, ACL scope preparation, imports, constants,
    new global statements, or a caller of changed endpoints to differ.
    """
    allowed={'KnowledgeSelection','resolve_selection','upload','DocumentMetadata','edit_document'}
    def parts(source):
        named={};other=[]
        for node in ast.parse(source).body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                if node.name in named:raise ValueError('Duplicate top-level definition')
                named[node.name]=node
            else:other.append(ast.dump(node,include_attributes=False))
        return named,other
    before,old_other=parts(reference);after,new_other=parts(current)
    changed={key for key in before.keys()|after.keys() if key not in before or key not in after or
        ast.dump(before[key],include_attributes=False)!=ast.dump(after[key],include_attributes=False)}
    protected_callers={key for key,node in after.items() if key not in allowed and
        any(isinstance(n,ast.Name) and n.id in changed for n in ast.walk(node))}
    return {'passed':old_other==new_other and changed<=allowed and not protected_callers,
        'changed_endpoint_definitions':sorted(changed),'protected_callers':sorted(protected_callers),
        'measured_source_sha256':hashlib.sha256(reference.encode()).hexdigest(),
        'candidate_source_sha256':hashlib.sha256(current.encode()).hexdigest()}


def build(dataset, results, output, generation_reference=None):
    cases=json.loads(dataset.read_text(encoding='utf-8')); rows=[];missing=[]
    for case in cases:
        p=results/(case['id']+'-optimized.json')
        if not p.exists():missing.append(case['id']);continue
        row=json.loads(p.read_text(encoding='utf-8'));row['category']=case['category'];row['unanswerable']=case.get('unanswerable',False);rows.append(row)
    all_scores=summary(rows);holdout=summary([r for r in rows if r['split']=='holdout'])
    def average(values):
        numbers=[v for v in values if v is not None]
        return sum(numbers)/len(numbers) if numbers else None
    before=average([r.get('baseline_evidence_metrics',{}).get('context_recall') for r in rows])
    after=all_scores['context_recall']
    refusals=[r for r in rows if r['unanswerable']]
    refusal_score=sum(r.get('judgment',{}).get('refusal_correct') is True for r in refusals)/len(refusals) if refusals else None
    generation_retries=[r['id'] for r in rows if any(a.get('stage')=='generation' for a in r.get('prior_attempts',[]))]
    judgment_retries=[r['id'] for r in rows if r.get('prior_errors') or any(a.get('stage')=='judge' for a in r.get('prior_attempts',[]))]
    annotation_revisions=[r['id'] for r in rows if r.get('prior_annotation_judgments') or r.get('annotation_revision')]
    fingerprints={r.get('fingerprint') for r in rows}
    current_source=(Path(__file__).resolve().parents[2]/'backend/company_workspace.py').read_text(encoding='utf-8')
    measured_source=generation_reference.read_text(encoding='utf-8') if generation_reference else current_source
    integration=generation_integration(measured_source,current_source)
    checks={
        'all_expected_cases_present':not missing and len(rows)==len(cases),
        'no_provider_or_judge_errors':all_scores['errors']==0,
        'no_invalid_citation_ids':all_scores['invalid_citations']==0,
        'holdout_fact_check':holdout['answer_correct'] is not None and holdout['answer_correct']>=GATES['holdout_answer_correct'],
        'holdout_faithfulness':holdout['faithful'] is not None and holdout['faithful']>=GATES['holdout_faithful'],
        'holdout_citation_support':holdout['citation_supported'] is not None and holdout['citation_supported']>=GATES['holdout_citation_supported'],
        'unanswerable_and_scope_refusals':refusal_score==GATES['unanswerable_refusal_correct'],
        'context_recall_does_not_regress':before is not None and after is not None and after+1e-12>=before,
        'every_case_bound_to_inputs_and_code':None not in fingerprints,
        'one_reviewed_generation_version':{r.get('generation_source_sha256') for r in rows}=={integration['measured_source_sha256']},
        'generation_unchanged_by_endpoint_integration':integration['passed'],
        'one_reviewed_selection_version':{r.get('selection_source_sha256') for r in rows}=={
            hashlib.sha256((Path(__file__).resolve().parents[2]/'backend/company_retrieval.py').read_text(encoding='utf-8').encode()).hexdigest()},
    }
    report={'status':'passed' if all(checks.values()) else 'not_passed','cases':len(cases),'completed':len(rows),'missing':missing,
        'gates':GATES,'checks':checks,'all':all_scores,'holdout':holdout,'baseline_context_recall':before,'optimized_context_recall':after,
        'refusal_correct':refusal_score,'categories':dict(Counter(c['category'] for c in cases)),
        'generation_retries':generation_retries,'judgment_retries':judgment_retries,'reference_annotation_revisions':annotation_revisions,
        'scope':'four original documents; 70 development / 30 held-out questions; independent automated judge, not a corpus-wide guarantee',
        'selection_comparison':'same candidate nodes; old/new selection scored per final answer; no claim of full-production A/B accuracy lift'}
    report['retrieval_modes']=sorted({r.get('retrieval_mode','live') for r in rows})
    report['generation_source_hashes']=sorted({r.get('generation_source_sha256','legacy') for r in rows})
    report['generation_integration']=integration
    output.mkdir(parents=True,exist_ok=True)
    (output/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def pct(v):return '未测' if v is None else f'{v:.1%}'
    metrics=[('原文依据进入最终上下文',before,after),('保留题自动答案核对通过率',None,holdout['answer_correct']),
        ('保留题依据忠实度',None,holdout['faithful']),('保留题引用支持程度',None,holdout['citation_supported']),
        ('无答案及范围限制题正确拒答',None,refusal_score)]
    table=''.join('<tr><td>'+escape(name)+'</td><td>'+pct(old)+'</td><td>'+pct(new)+'</td></tr>' for name,old,new in metrics)
    details=[]
    for row in sorted(rows,key=lambda r:r['id']):
        j=row.get('judgment',{});ok=not row.get('error') and all(j.get(k) is True for k in ('answer_correct','complete','faithful','citation_supported'))
        refs=''.join('<li><b>'+escape(str(r.get('title','')))+' V'+escape(str(r.get('version','')))+' [id_'+escape(str(r.get('id','')))+']</b><pre>'+escape(r.get('text',''))+'</pre></li>' for r in row.get('references',[]))
        prior=''.join('<p>参考条目修订前的答案和评分（生成回答未修改）</p><pre>'+escape(json.dumps(a,ensure_ascii=False,indent=2))+'</pre>' for a in row.get('prior_annotation_judgments',[]))
        details.append('<details><summary>'+escape(row['id']+' · '+row.get('split','')+' · '+('通过' if ok else '需查看')+' · '+row['question'])+'</summary><p>'+escape(j.get('reason',row.get('error','')))+'</p>'+prior+'<h3>参考答案</h3><pre>'+escape(row.get('expected_answer',''))+'</pre><h3>实际回答</h3><pre>'+escape(row.get('answer',''))+'</pre><h3>本轮依据</h3><ol>'+refs+'</ol></details>')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>企业知识库问答质量验收</title><style>body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#17212f;background:#f5f7fa;max-width:1100px;margin:40px auto;padding:0 24px}h1{font-size:28px}section,details{background:white;border:1px solid #dce2e9;border-radius:8px;padding:18px;margin:16px 0}table{width:100%;border-collapse:collapse}td,th{padding:12px;text-align:left;border-bottom:1px solid #e1e6ed}th{background:#edf2f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 inherit}summary{cursor:pointer}small{color:#5b687b}</style><h1>企业知识库问答质量验收</h1>'''
    html+='<p>最终状态：'+('通过' if report['status']=='passed' else '尚未通过')+'。完成 '+str(len(rows))+' / '+str(len(cases))+' 道真实原件题目。</p>'
    html+='<p>评测覆盖4份原件，70道开发题、30道保留题。事实与引用核对来自独立模型调用，仍需人工抽查；不能将本样本分数视为整个知识库的准确率。</p>'
    html+='<p>回答生成重试 '+str(len(generation_retries))+' 题；评分调用重试 '+str(len(judgment_retries))+' 题；参考条目修订 '+str(len(annotation_revisions))+' 题。原失败、原评分与回答均保留，不能理解为首次调用全部成功。</p>'
    if 'verified_candidate_replay' in report['retrieval_modes']:
        html+='<p>首轮完成真实百炼检索。日期归因修复后，本轮重放首轮已核对的原文候选，重新调用真实回答模型和评分模型，以固定证据检查修复效果。30道保留题属于修复后的回归验收，不能作为未见过问题的泛化能力估计。</p>'
    if integration['measured_source_sha256']!=integration['candidate_source_sha256']:
        html+='<p>评测期间线上另行发布部门管理。候选版本合并了部门选择、上传和元数据接口；AST检查要求只允许这五个接口定义变化，禁止问答、证据组织、范围权限准备、导入、全局常量或其调用路径变化。两个完整模块哈希及差异定义保存在JSON中，接口集成另行运行软件回归；这不等于重新进行部门功能的模型效果评测。</p>'
    html+='<section><table><tr><th>检查项</th><th>旧证据选择</th><th>最终版本</th></tr>'+table+'</table><p>旧新证据选择使用相同候选片段；事实正确率只报告最终版本，不把此前试验中的不等量样本冒充完整A/B测试。</p></section>'
    html+='<section><h2>验收条件</h2><ul>'+''.join('<li>'+escape(k)+'：'+('通过' if v else '未通过')+'</li>' for k,v in checks.items())+'</ul></section>'
    html+='<section><h2>原文复核说明</h2><p>首轮Q020、Q056按资料分别给出不同职务或价格说法，并包含参考答案要点，符合保留真实冲突的要求；首轮自动判错保留在原始记录中，后续评分明确允许有依据的冲突说明。Q088修正了参考条目索引错误，首轮问题和回答均保留，后续按同一问题验证正确参考依据。此复核由Codex完成，不代替人工业务审核。</p><p>云端表格的换行标记不作为文字丢失。召回匹配修正前的指标及所有候选证据ID均保留在原始记录中。</p></section>'
    html+='<h2>逐题记录</h2>'+''.join(details)+'</html>'
    (output/'report.html').write_text(html,encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--results',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--generation-reference',type=Path,help='Frozen measured module; only bounded department endpoint integration may differ')
    a=p.parse_args();print(json.dumps(build(a.dataset,a.results,a.output,a.generation_reference),ensure_ascii=False))
