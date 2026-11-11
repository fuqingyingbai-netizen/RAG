"""Validate paired private Ragas runs and produce a local HTML/JSON report."""
import argparse
import ast
from html import escape
import hashlib
import json
import math
from pathlib import Path
import runpy
import re

METRICS={'context_recall':'证据召回','faithfulness':'证据忠实度',
    'factual_correctness':'事实 F1','factual_recall':'原生事实 recall'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def aggregate(rows, split=None):
    result={}
    for name in METRICS:
        values=[r[name] for r in rows if (not split or r['split']==split) and name in r]
        result[name]={'count':len(values),'mean':sum(values)/len(values) if values else None}
    return result


def aggregate_probes(items):
    values=[r['value'] for r in items if r['status']=='completed']
    return {'count':len(values),'mean':sum(values)/len(values) if values else None}


def validate_generation_provenance(inputs, lock, provenance):
    if provenance.get('kind')!='controlled_same_provider':return
    assert provenance['baseline_commit']==lock['commit'],'Baseline commit changed'
    for answers in inputs.values():
        assert all(r.get('generation_config')==provenance['config'] for r in answers),'Generation provider/options changed'
        assert all(r['selection_source_sha256']==lock['selection_source_sha256'] for r in answers),'Selection code changed'
    assert {r['generation_source_sha256'] for r in inputs['baseline']}=={lock['generation_source_sha256']},'Baseline generation code changed'


def build(root, output):
    gold=read(root/'gold.json');ids=[r['id'] for r in gold]
    inputs={phase:read(root/(phase+'-answers.json')) for phase in ('baseline','improved')}
    lock=read(root/'baseline-lock.json')
    provenance=read(root/'generation-provenance.json') if (root/'generation-provenance.json').exists() else {'kind':'recorded_answers'}
    validate_generation_provenance(inputs,lock,provenance)
    manifests={p:read(root/(p+'-ragas/manifest.json')) for p in inputs}
    configs={p:{k:v for k,v in m['config'].items() if k!='runner_sha256'} for p,m in manifests.items()}
    assert configs['baseline']==configs['improved'],'Judge configuration changed'
    sources={'baseline':root/'baseline-metric-runner.py',
        'improved':Path(__file__).with_name('evaluate_company_ragas.py')}
    native_calls={};runners={}
    for phase,path in sources.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest()==manifests[phase]['config']['runner_sha256'],'Runner snapshot changed'
        runners[phase]=runpy.run_path(str(path))
        native_calls[phase]=[ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
            if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Name) and n.func.id in ('llm_factory','ContextRecall','Faithfulness','FactualCorrectness'))
                or (isinstance(n.func,ast.Attribute) and n.func.attr=='ascore'))]
    assert native_calls['baseline']==native_calls['improved'],'Native Ragas metric calls changed'
    for answer in inputs['baseline']+inputs['improved']:
        for metric in ('context_recall','faithfulness','factual_correctness'):
            assert runners['baseline']['metric_inputs'](answer,metric)==runners['improved']['metric_inputs'](answer,metric)
    rows={};retries={};citations={}
    for phase,answers in inputs.items():
        assert [r['id'] for r in answers]==ids,'Missing/reordered generation cases'
        assert manifests[phase]['answers_sha256']==hashlib.sha256((root/(phase+'-answers.json')).read_bytes()).hexdigest()
        rows[phase]=[];retries[phase]=[];citations[phase]=[]
        for case,answer in zip(gold,answers):
            assert not answer.get('error') and answer['question']==case['question']
            assert answer['expected_answer']==case['expected_answer'],'Gold reference changed'
            assert answer.get('unanswerable',False)==case.get('unanswerable',False)
            record={'id':case['id'],'split':case['split']}
            if answer.get('prior_attempts'):retries[phase].append({'id':case['id'],'kind':'generation','count':len(answer['prior_attempts'])})
            for metric in ('context_recall','faithfulness','factual_correctness'):
                if case.get('unanswerable'):continue
                score=read(root/(phase+'-ragas')/(case['id']+'-'+metric+'.json'))
                assert score['status']=='completed','Unresolved metric error: '+phase+case['id']+metric
                payload=runners[phase]['metric_inputs'](answer,metric)
                assert score['fingerprint']==runners[phase]['digest']({'config':manifests[phase]['config'],'name':metric,'input':payload}),'Score input fingerprint changed'
                assert math.isfinite(score['value']) and 0<=score['value']<=1,'Invalid metric value'
                record[metric]=score['value']
                if metric=='factual_correctness':record['factual_recall']=score['factual_recall']
                if score.get('prior_attempts'):retries[phase].append({'id':case['id'],'kind':metric,'count':len(score['prior_attempts'])})
            if case['id'] in manifests[phase]['citation_probe_ids']:
                score=read(root/(phase+'-ragas')/(case['id']+'-cited_faithfulness.json'))
                assert score['status'] in ('completed','not_applicable')
                assert score['fingerprint']==runners[phase]['digest']({'config':manifests[phase]['config'],'name':'cited_faithfulness','input':runners[phase]['metric_inputs'](answer,'cited_faithfulness')})
                citations[phase].append(score)
            rows[phase].append(record)
    assert all(a['references']==b['references'] for a,b in zip(inputs['baseline'],inputs['improved'])),'Evidence changed between arms'
    review=read(root/'business-review.json')
    assert review['answers_sha256']==hashlib.sha256((root/'improved-answers.json').read_bytes()).hexdigest(),'Review belongs to other answers'
    reviewed={r['id']:r for r in review['cases']}
    required={r['id'] for r in gold if r.get('unanswerable')}|set(manifests['improved']['citation_probe_ids'])
    assert required<=reviewed.keys(),'Missing known-case/refusal review'
    assert all(set(re.findall(r'\[id_([^\]]+)\]',r['answer']))<={str(ref['id']) for ref in r['references']}
        for r in inputs['improved']),'Invalid citation ID'
    candidate_source=Path(__file__).resolve().parents[2]/'backend/company_workspace.py'
    assert {r['generation_source_sha256'] for r in inputs['improved']}=={hashlib.sha256(candidate_source.read_bytes()).hexdigest()},'Current candidate differs from measured generation'
    report={'baseline_lock':lock,'generation_provenance':provenance,'judge':configs['baseline'],
        'runner_sha256':{p:m['config']['runner_sha256'] for p,m in manifests.items()},
        'runner_compatibility':'Native metric constructors/ascore calls and all core metric inputs are identical; improved wrapper marks uncited refusals N/A',
        'case_count':len(ids),'answerable':sum(not r.get('unanswerable') for r in gold),
        'metrics':{p:{s:aggregate(rows[p],None if s=='all' else s) for s in ('all','development','holdout')} for p in inputs},
        'same_evidence':True,'retries':retries,'citation_probes':citations,
        'citation_probe_summary':{p:aggregate_probes(v) for p,v in citations.items()},'business_review':review,
        'candidate_generation_sha256':sorted({r['generation_source_sha256'] for r in inputs['improved']}),
        'checks':{'one_candidate_version':len({r['generation_source_sha256'] for r in inputs['improved']})==1,
            'reviewed_cases_pass':all(reviewed[k]['passed'] for k in required)},
        'per_case_metrics':rows}
    output.mkdir(parents=True,exist_ok=True)
    (output/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    table=''
    for metric,label in METRICS.items():
        before=report['metrics']['baseline']['all'][metric];after=report['metrics']['improved']['all'][metric]
        table+=f'<tr><td>{label}</td><td>{before["mean"]:.4f}</td><td>{after["mean"]:.4f}</td><td>{after["mean"]-before["mean"]:+.4f}</td><td>{after["count"]}</td></tr>'
    before=report['citation_probe_summary']['baseline'];after=report['citation_probe_summary']['improved']
    table+=f'<tr><td>引用片段探针（仅4题）</td><td>{before["mean"]:.4f}</td><td>{after["mean"]:.4f}</td><td>{after["mean"]-before["mean"]:+.4f}</td><td>{after["count"]}</td></tr>'
    details=''
    for a,b in zip(inputs['baseline'],inputs['improved']):
        detail={'基线评分':next(r for r in rows['baseline'] if r['id']==a['id']),
            '修复评分':next(r for r in rows['improved'] if r['id']==a['id']),'专项复核':reviewed.get(a['id'])}
        details+=f'<details><summary>{a["id"]} · {escape(a["question"])}</summary><h3>参考要点</h3><pre>{escape(a["expected_answer"])}</pre><h3>基线回答</h3><pre>{escape(a["answer"])}</pre><h3>修复回答</h3><pre>{escape(b["answer"])}</pre><pre>{escape(json.dumps(detail,ensure_ascii=False,indent=2))}</pre><h3>固定证据</h3><pre>{escape(json.dumps(b["references"],ensure_ascii=False,indent=2))}</pre></details>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ragas 基线与修复评测</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#182534;background:#f6f8fa}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #dde3e9}details{background:white;border:1px solid #dde3e9;margin:12px 0;padding:16px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}small{color:#526172}</style><h1>Ragas 基线与修复评测</h1>'''
    page+='<p>仅更新 main，不部署。4 份资料、100 题；90 题运行原生 Ragas 指标，10 道无答案题单独核对拒答与引用。70/30 开发与保留题均为回归题，不能作为未见数据的泛化估计。</p>'
    if provenance.get('kind')=='controlled_same_provider':
        page+='<p>冻结基线代码与修复代码均通过同一个官方模型接口、相同模型与选项重新生成回答，固定题目、参考答案和逐片段相同的证据。原中转服务的历史回答与未完成评分另行存档，不混入本次对照。Ragas 0.4.3 前后使用相同评分配置；追踪关闭，原始请求及失败重试保留在私有目录。</p>'
    else:
        page+='<p>基线使用已保存的真实回答；已核对当前生成逻辑及原模型配置与记录相符。修复回答使用相同题目、参考答案和逐片段相同的证据重新生成。Ragas 0.4.3 使用既有模型服务评分，关闭外部追踪，原始请求及失败重试保留在私有目录。</p>'
    page+='<table><tr><th>原生指标（0–1）</th><th>固定基线</th><th>修复后</th><th>变化</th><th>题数</th></tr>'+table+'</table>'
    page+='<p>证据召回衡量参考事实是否在召回片段中；忠实度衡量回答事实能否被片段支持；事实 F1 对照参考答案，既惩罚遗漏也惩罚参考之外的事实。原生事实 recall 同样基于声明推断，受拆分粒度影响，不替代必要要点逐项验收。它们不是题目通过率，F1 也不等同于人工准确率，参考答案以外但有来源的扩展仍可能拉低 F1。</p>'
    page+='<p>本次生成和评分使用同一型号的 GLM，独立调用不等于独立裁判，可能有同源偏差。Faithfulness 的证据输入仅为片段正文，不含标题、版本或复核状态等元数据，涉及这些信息的来源说明需另行核对。两组证据逐片段固定，因此证据召回分数用于确认这些片段是否包含参考事实，不能代表全库实时检索召回率，也不能用来宣称本轮提高了检索召回。</p>'
    page+='<p>本题集部分参考答案仅列必要要点，省略了问题中的具体对象名称。原生声明拆分与推断可能把回答中有来源的对象名称判为参考之外的事实；拆分粒度不同也会影响同义回答的 F1。此类分数保持原样，不手动改分，需结合原文复核与忠实度、事实 recall 阅读。</p>'
    page+='<p>Ragas 0.4.3 的原生事实 recall 仍以“回答声明能否被参考支持”的数量作为 TP；因此即使参考要点能从回答中找到，也可能因参考省略对象名而给出低值。此辅助指标照录原生结果，不作为必要要点覆盖率或检索召回率使用。</p>'
    page+='<p>4 个已知问题另做引用片段探针及逐句复核。探针只把回答实际引用的片段交给原生 Faithfulness，仍不能证明每句话的引用编号正确；专项复核记录才用于判断已知错引。复核由 Codex 对照原文完成，不替代独立业务抽检。正确拒答且没有引用时探针记为不适用，不计为满分。</p>'
    if after['mean']<before['mean']:
        page+='<p>引用片段探针均分低于基线，保留该回退，不宣称引用质量全面提升。专项复核只确认所列核心事实及其对应来源。原始审计显示，引用编号被当作待验证事实、仅在标题中的对象/时间，以及“直接摘录”等不严谨说明均会影响探针；具体原因与剩余问题见下列记录。</p>'
    page+='<h2>专项复核与运行记录</h2><pre>'+escape(json.dumps({k:report[k] for k in ('checks','business_review','retries','citation_probes')},ensure_ascii=False,indent=2))+'</pre><h2>逐题对照</h2>'+details+'</html>'
    (output/'report.html').write_text(page,encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=build(a.root,a.output)
    print(json.dumps({'metrics':report['metrics'],'checks':report['checks']},ensure_ascii=False))
