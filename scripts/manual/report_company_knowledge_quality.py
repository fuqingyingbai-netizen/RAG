"""Build a private HTML/JSON acceptance report without calling any model."""
import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from company_quality import summary

# Set before inspecting final holdout results. These are project gates, not
# claims that a 100-question sample establishes population-wide accuracy.
GATES={'holdout_answer_correct':.90,'holdout_faithful':.95,'holdout_citation_supported':.95,
       'unanswerable_refusal_correct':1.0,'max_errors':0,'max_invalid_citations':0}


def build(dataset, results, output):
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
    fingerprints={r.get('fingerprint') for r in rows}
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
    }
    report={'status':'passed' if all(checks.values()) else 'not_passed','cases':len(cases),'completed':len(rows),'missing':missing,
        'gates':GATES,'checks':checks,'all':all_scores,'holdout':holdout,'baseline_context_recall':before,'optimized_context_recall':after,
        'refusal_correct':refusal_score,'categories':dict(Counter(c['category'] for c in cases)),
        'scope':'four original documents; 70 development / 30 held-out questions; independent automated judge, not a corpus-wide guarantee',
        'selection_comparison':'same candidate nodes; old/new selection scored per final answer; no claim of full-production A/B accuracy lift'}
    output.mkdir(parents=True,exist_ok=True)
    (output/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def pct(v):return '未测' if v is None else f'{v:.1%}'
    metrics=[('原文依据进入最终上下文',before,after),('保留题事实正确率',None,holdout['answer_correct']),
        ('保留题依据忠实度',None,holdout['faithful']),('保留题引用支持程度',None,holdout['citation_supported']),
        ('无答案及范围限制题正确拒答',None,refusal_score)]
    table=''.join('<tr><td>'+escape(name)+'</td><td>'+pct(old)+'</td><td>'+pct(new)+'</td></tr>' for name,old,new in metrics)
    details=[]
    for row in sorted(rows,key=lambda r:r['id']):
        j=row.get('judgment',{});ok=not row.get('error') and all(j.get(k) is True for k in ('answer_correct','complete','faithful','citation_supported'))
        refs=''.join('<li><b>'+escape(str(r.get('title','')))+' V'+escape(str(r.get('version','')))+' [id_'+escape(str(r.get('id','')))+']</b><pre>'+escape(r.get('text',''))+'</pre></li>' for r in row.get('references',[]))
        details.append('<details><summary>'+escape(row['id']+' · '+row.get('split','')+' · '+('通过' if ok else '需查看')+' · '+row['question'])+'</summary><p>'+escape(j.get('reason',row.get('error','')))+'</p><h3>参考答案</h3><pre>'+escape(row.get('expected_answer',''))+'</pre><h3>实际回答</h3><pre>'+escape(row.get('answer',''))+'</pre><h3>本轮依据</h3><ol>'+refs+'</ol></details>')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>企业知识库问答质量验收</title><style>body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#17212f;background:#f5f7fa;max-width:1100px;margin:40px auto;padding:0 24px}h1{font-size:28px}section,details{background:white;border:1px solid #dce2e9;border-radius:8px;padding:18px;margin:16px 0}table{width:100%;border-collapse:collapse}td,th{padding:12px;text-align:left;border-bottom:1px solid #e1e6ed}th{background:#edf2f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 inherit}summary{cursor:pointer}small{color:#5b687b}</style><h1>企业知识库问答质量验收</h1>'''
    html+='<p>最终状态：'+('通过' if report['status']=='passed' else '尚未通过')+'。完成 '+str(len(rows))+' / '+str(len(cases))+' 道真实原件题目。</p>'
    html+='<p>评测覆盖4份原件，70道开发题、30道保留题。事实与引用核对来自独立模型调用，仍需人工抽查；不能将本样本分数视为整个知识库的准确率。</p>'
    html+='<section><table><tr><th>检查项</th><th>旧证据选择</th><th>最终版本</th></tr>'+table+'</table><p>旧新证据选择使用相同候选片段；事实正确率只报告最终版本，不把此前试验中的不等量样本冒充完整A/B测试。</p></section>'
    html+='<section><h2>验收条件</h2><ul>'+''.join('<li>'+escape(k)+'：'+('通过' if v else '未通过')+'</li>' for k,v in checks.items())+'</ul></section>'
    html+='<h2>逐题记录</h2>'+''.join(details)+'</html>'
    (output/'report.html').write_text(html,encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--results',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.dataset,a.results,a.output),ensure_ascii=False))
