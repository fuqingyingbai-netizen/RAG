"""Publish auditable results of the general person delivery cycle."""
import html
import argparse
import json
from pathlib import Path
import shutil
import sys
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from person_evidence import split_sections
from build_person_prose_rerun import metrics


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-version',default='v22')
    parser.add_argument('--case-versions',nargs=3,metavar=('WANG5','WANG3','ZHANG5'),
                        help='Actual run versions for the three samples, in display order.')
    parser.add_argument('--output',type=Path,default=ROOT/'deliverables/person-delivery-cycle-20261023/dist')
    args=parser.parse_args()
    work=ROOT/'work/person-delivery-cycle-20261023';out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=True);esc=lambda v:html.escape(str(v),quote=True)
    blockers=read(work/'known-blockers.json') if (work/'known-blockers.json').exists() else {'cases':{}}
    historical_blockers=blockers
    versions=args.case_versions or [args.run_version]*3
    import re
    assert all(re.fullmatch(r'v\d+',v) for v in versions),'Expected actual v-number run versions.'
    cases=[('wang5-'+versions[0],'王传福',5),('wang3-'+versions[1],'王传福',3),('zhang5-'+versions[2],'张勇',5)]
    blockers={**blockers,'cases':{k:v for k,v in blockers['cases'].items() if k in {c[0] for c in cases}}}
    rows=[];cards=[];run_data={};labels={'passed_after_targeted_repair':'循环修订后通过','passed_without_targeted_repair':'完整诊断通过','pending_review':'仍待复核'}
    phase_labels={'pending_repair_call':'补写或压缩调用失败','pending_repair_validation':'候选未通过原文、格式或长度检查',
        'pending_repair_semantics':'候选未通过语义核对','pending_final_coverage':'候选仍有原事项遗漏',
        'pending_material_diagnosis':'材料去向或覆盖仍待核查','passed_after_targeted_repair':'定向修订复核通过',
        'passed_without_content_repair':'原有事项覆盖通过','pending_review':'事项核对尚未完整返回'}
    state_labels={'analysis':'正文分析','table':'资料表','appendix':'补充附录','corroborating_appendix':'佐证附录','source_display':'正文原文','missing':'实质遗漏','pending':'待复核'}
    for key,name,n in cases:
        p=work/key;s=read(p/'summary.json');assert s['code_unchanged_during_run']
        a=read(p/'acceptance-results.json')[str(n)];c=read(p/'contract.json');audit=read(p/'audit.json')
        text=(p/'desktop_report.md').read_text(encoding='utf-8');m=metrics(split_sections(text)[n],c['chapters'][str(n)])
        dest=out/key;dest.mkdir(exist_ok=True)
        for filename in ['desktop_report.md','evidence-appendix.md','acceptance-results.json']:
            shutil.copyfile(p/filename,dest/filename)
        material=a['content_acceptance'].get('material_diagnosis',{})
        if material.get('input_records') is not None:
            actual_ids={r['evidence_id'] for r in material.get('rows',[])}
            facts_by_id={f['evidence_id']:f for f in c['facts']}
            assert len(actual_ids)==material['input_records'] and actual_ids<=set(facts_by_id)
            m['render_package_research_records']=m['research_records']
            m['research_records']=material['input_records']
            m['research_sources']=len({facts_by_id[eid]['source_url'] for eid in actual_ids})
            m['research_count_basis']='Actual complete material-diagnosis input, including bound automatic checkpoint records.'
        count=audit.get('material_accounting',{})
        if a['status'].startswith('passed'):
            assert material.get('status')=='passed' and not a['unresolved']
            assert m['analysis_chars']<=600
        row={'key':key,'name':name,'chapter':n,'status':a['status'],
            'metrics':m,'material_diagnosis_counts':material.get('counts',{}),'material_diagnosis_records':material.get('input_records'),
            'rounds':len(a['content_acceptance'].get('rounds',[])),'stop_reason':a['content_acceptance'].get('stop_reason'),
            'literal_material_display_proposals':sum(len(x['added']) for x in a['content_acceptance'].get('material_display_repairs',[])),
            'full_report_delivery_status':audit.get('automatic_delivery_status','pending'),
            'complete_annex_records':count.get('appendix_record_count'),
            'professional_records':count.get('professional_records'),'professional_records_in_body':count.get('professional_records_in_body')}
        safe_summary={k:s[k] for k in ['sources_sha256','generation_code_sha256','code_unchanged_during_run','model_requests',
            'model_requests_returned','model_requests_failed','new_search_calls','new_fetch_calls','new_professional_calls',
            'exact_input_responses_reused','actual_cost_available','elapsed_seconds','scope','results']}
        safe_summary['recorded_transport_failures_replayed']=s.get('recorded_transport_failures_replayed',0)
        safe_summary['new_call_model_context']=s.get('model_context',{})
        safe_summary['restored_material_checkpoint']=s.get('restored_material_checkpoint',{})
        rows.append(row);run_data[key]={'summary':safe_summary,'acceptance':a,'accounting':count,
            'source_field_exclusions':[r for r in c.get('source_material_audit',[])
                if r.get('reason')=='provider_metadata_not_company_fact'],
            'full_report_gate':audit.get('delivery_gate',{})}
        rounds=[]
        for r in a['content_acceptance'].get('rounds',[]):
            rounds.append('<li>第'+str(r['round'])+'轮：'+esc(phase_labels.get(r['status'],r['status']))+
                ('（'+esc(r['exception_type'])+'）' if r.get('exception_type') else '')+
                '；材料去向 '+esc(r.get('material_diagnosis',{}).get('counts',{}))+'；问题 '+esc(r.get('issues',[]))+'</li>')
        records=[]
        for r in material.get('rows',[]):
            records.append('<tr><td>'+esc(r['evidence_id'])+'</td><td>'+esc(state_labels.get(r['disposition'],r['disposition']))+'</td><td>'+esc(r.get('reason',''))+'</td></tr>')
        cards.append('<section><h2>'+esc(name)+f' 第{n}章</h2><p>'+esc(labels[a['status']])+f"；修订诊断 {row['rounds']} 轮。"+'</p><ul>'+''.join(rounds)+'</ul>'
            +('<p><strong>'+esc(blockers['cases'][key]['summary'])+'</strong> <a href="known-blockers.json">实际拒绝依据与失败请求</a></p>' if key in blockers['cases'] else '')+
            '<p><a href="'+key+'/desktop_report.md">完整报告底稿</a> · <a href="'+key+'/evidence-appendix.md">完整原文与采用去向附录</a> · <a href="'+key+'/acceptance-results.json">逐轮验收依据</a></p>'
            '<p>本轮模型配置：'+esc(s.get('model_context',{}).get('model','未记录'))+
            '，新增调用 '+str(s['model_requests'])+' 次；恢复检查点的运行配置模型：'+esc(s.get('restored_material_checkpoint',{}).get('origin_model_context',{}).get('model','无'))+
            '。检查点可能包含更早版本继承的结论，来源记录见完整统计。既有诊断仅在材料、正文、任务及表格指纹匹配时复用；改变的内容仍重新核查。</p>'
            '<details><summary>逐条材料去向与理由</summary><div class="scroll"><table><tr><th>证据</th><th>去向</th><th>具体理由</th></tr>'+''.join(records)+'</table></div></details>'
            '<details><summary>本章当前正文</summary><pre>'+esc(split_sections(text)[n])+'</pre></details></section>')
    stats={'cases':rows,'runs':run_data,'tests':read(work/'test-results.json'),
        'scope':'Archived automatic drafts, complete material diagnostics and targeted correction; no new search/fetch/provider extraction. Partial chapter checks cannot certify all chapters.',
        'status_counts':dict(Counter(r['status'] for r in rows))}
    if blockers['cases']:
        stats['known_blockers']=blockers
        (out/'known-blockers.json').write_text(json.dumps(blockers,ensure_ascii=False,indent=2),encoding='utf-8')
    stats['historical_source_review_findings']=historical_blockers
    integrations=list(work.glob('integration-manifest-v*.json'))
    integration=max(integrations,key=lambda p:int(p.stem.rsplit('v',1)[1])) if integrations else None
    if integration is not None:
        stats['implementation']=read(integration)
        stats['unchanged_retention_regression']=read(work/'exact-retention-actual-proof.json')
        if (work/'feedback-payload-actual-proof.json').exists() and 'writer_repair_feedback' in (ROOT/'backend/person_content_acceptance.py').read_text(encoding='utf-8'):
            stats['feedback_payload_regression']=read(work/'feedback-payload-actual-proof.json')
        conditional_proofs=list(work.glob('v*-actual-conditional-proof.json'))
        if conditional_proofs and 'conditional_contribution_errors' in (ROOT/'backend/person_source_boundaries.py').read_text(encoding='utf-8'):
            stats['conditional_commitment_regression']=read(max(conditional_proofs,key=lambda p:int(p.name.split('-',1)[0][1:])))
        if (work/'v75-actual-forecast-proof.json').exists() and 'attributed_forecast' in (ROOT/'backend/person_records.py').read_text(encoding='utf-8'):
            stats['attributed_forecast_regression']=read(work/'v75-actual-forecast-proof.json')
        if (work/'v76-actual-meeting-year-proof.json').exists() and 'annual_meeting_year_errors' in (ROOT/'backend/person_source_boundaries.py').read_text(encoding='utf-8'):
            stats['annual_meeting_year_regression']=read(work/'v76-actual-meeting-year-proof.json')
        if (work/'v76-actual-local-capacity-proof.json').exists() and 'repeated_local_coverage_capacity_failure' in (ROOT/'backend/person_content_acceptance.py').read_text(encoding='utf-8'):
            stats['local_coverage_capacity_regression']=read(work/'v76-actual-local-capacity-proof.json')
        if (work/'v42-checkpoint-source-pool-proof.json').exists():
            stats['checkpoint_source_pool_regression']=read(work/'v42-checkpoint-source-pool-proof.json')
        if (work/'v77-actual-checkpoint-rebase-proof.json').exists():
            stats['authenticated_review_resume_regression']=read(work/'v77-actual-checkpoint-rebase-proof.json')
            stats['resume_context_offline_regression']=read(work/'v77-resume-context-offline-proof.json')
        if (work/'v78-actual-source-name-proof.json').exists():
            stats['numeric_source_name_regression']=read(work/'v78-actual-source-name-proof.json')
        if (work/'v79-actual-tight-scope-proof.json').exists():
            stats['tight_scope_regression']=read(work/'v79-actual-tight-scope-proof.json')
    history=[]
    for p in sorted(work.iterdir()):
        if not p.is_dir():continue
        stop=p/'controller-stop.json';summary=p/'summary.json';status=p/'request-status.json'
        if (p/'smoke-results.json').exists():
            history.append({'run':p.name,'state':'completed_scope_smoke','input_records':read(p/'smoke-results.json')['input_records'],
                'status':read(p/'smoke-results.json')['status'],'client_requests':len(read(status))})
        elif summary.exists():
            recorded=read(summary)
            if 'model_requests' in recorded and 'results' in recorded:
                history.append({'run':p.name,'requests':recorded['model_requests'],'state':'completed','results':recorded['results'],
                    **({'subsequent_source_review':historical_blockers['cases'][p.name]} if p.name in historical_blockers['cases'] else {})})
            else:
                history.append({'run':p.name,'state':'model_probe_not_delivery_acceptance',
                    **{k:recorded[k] for k in ('status','model_context','elapsed_seconds','exception_type') if k in recorded}})
        elif stop.exists():
            accounting=p/'controller-accounting.json'
            history.append({'run':p.name,**read(accounting if accounting.exists() else stop)})
        elif status.exists():history.append({'run':p.name,'state':'unfinished','requests_finished':len(read(status))})
    stats['run_history']=history
    stats['global_routing']={name:read(work/('global-routing-'+name+'-v4')/'routing-audit.json') for name in ['wang','zhang']}
    provider_review=work/'longai-quota-review/diagnosis.json'
    if provider_review.exists():
        provider=read(provider_review)
        stats['provider_status_at_check']={k:provider[k] for k in ['checked_utc','account_at_check','configured_model','probes','conclusion','billing_scope']}
    professional_audit=work/'professional-table-retention-audit.json'
    if professional_audit.exists():
        stats['professional_field_retention']=read(professional_audit)
        assert not any(r.get('is_staged_implementation') for r in stats['professional_field_retention'].values()),'Integrate and re-audit production code before packaging.'
    smoke=work/'smoke-v53-source-scope'
    if (smoke/'smoke-results.json').exists():
        packet=json.loads(read(smoke/'input-1.json')['prompt'].splitlines()[-1])
        stats['scope_smoke']={'status':read(smoke/'smoke-results.json')['status'],
            'requested_records':len(packet['facts']),'body_reference_records':len(packet.get('source_display_quotes',[])),
            'raw_returned_reviews':len(json.loads((smoke/'response-1.txt').read_text(encoding='utf-8'))['material_reviews']),
            'client_requests':len(read(smoke/'request-status.json')),
            'elapsed_seconds':sum(r['elapsed_seconds'] for r in read(smoke/'request-status.json'))}
    (out/'metrics.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    tr=[]
    for r in rows:
        m=r['metrics'];tr.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [r['name']+f" 第{r['chapter']}章",labels[r['status']],
            str(m['research_records'])+'/'+str(m['research_sources']),str(m['analysis_records'])+'/'+str(m['analysis_sources']),str(m['body_records'])+'/'+str(m['body_sources']),m['analysis_chars'],m['displayed_original_chars'],r['rounds']])+'</tr>')
    base='<script>if((location.protocol==="https:"||location.protocol==="http:")&&!location.pathname.endsWith("/")&&!location.pathname.endsWith(".html")){history.replaceState(null,"",location.pathname+"/"+location.search+location.hash);}</script>'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人物报告通用交付循环验证</title>'+base+'''<style>body{max-width:1280px;margin:24px auto;padding:0 20px;background:#f2f5f3;color:#213d33;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}section,header{background:white;border:1px solid #d2dfd7;border-radius:8px;padding:22px;margin:18px 0}h1,h2{color:#205a45}a{color:#176247}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f4;padding:16px}table{width:100%;border-collapse:collapse}td,th{border:1px solid #d2dfd7;padding:9px;text-align:left;overflow-wrap:anywhere}.scroll{overflow-x:auto}summary{cursor:pointer}</style></head><body>'''
    page+='<header><h1>人物报告：完整材料去向与自动交付诊断</h1><p>修复通用流程：全部合格材料研读 → 按章节写作 → 逐条采用诊断 → 定向修订 → 原文、语义、事项与长度复核 → 再诊断。通过才标记交付；没有进展、调用失败或到达轮次上限时保留失败原因，不标为交付通过。</p><p>正文分析每章最多600字符；代表性来源原文合计最多1600字符。其余原文随完整证据附录交付。附录保留、表格展示和分析采用分别统计，不能把存入附录称为全部用于分析。</p><p>本页是章节样本验证，整份报告仍须通过全部章节闸门。记录数量不等于独立信息或独立来源；未进行来源真实性认证。</p><p><a href="metrics.json">完整统计、诊断及试跑历史</a></p></header>'
    if stats.get('unchanged_retention_regression'):
        proof=stats['unchanged_retention_regression']
        page+=('<section><h2>本次修复与实际依据</h2><p>取消分析条数和原文条数上限，保留章节篇幅限制。全部合格材料逐条登记采用去向；实际未采用的材料保留具体理由和完整原文。</p>'
            '<p>已修复同文不同来源漏展示、月份后数量被误识别为日期，以及原正文和引用逐字保留却被模型判为遗漏的问题。实际回归中发现 '
            +str(len(proof['previously_missing_but_physically_retained']))+
            ' 条此类保留误判。现在仅对正文完全一致、原引用全部保留且引用仍合格的情形直接确认“已保留”；来源和语义校验继续独立执行。</p>'
            '<p>代码保存在独立修复分支，尚未合入主工作目录。本轮未重新检索或抓取平台数据。</p></section>')
    if stats.get('feedback_payload_regression'):
        proof=stats['feedback_payload_regression']
        page+=('<section><h2>减少重复诊断反馈</h2><p>实际补写请求中，历史诊断占 '+str(proof['before_feedback_chars'])+
            ' 字符。移除已通过核对的重复解释后，传给补写模型的诊断为 '+str(proof['after_feedback_chars'])+
            ' 字符。完整历史仍在台账；来源卡片、待核事项、失败反馈和候选原文保留。</p>'
            '<p>这是请求内容的实测变化，不能据此断言接口错误已消失或章节已通过。</p></section>')
    if stats.get('attributed_forecast_regression'):
        page+=('<section><h2>补充信息与预期陈述</h2><p>新材料优先在章节剩余字数内补充；空间不足以形成句子、实际局部补写超长或反复因局部容量失去事实时，重新分配整章篇幅。</p>'
            '<p>实际候选中，有明确来源和时间的未来预期曾被误当成作者新作的数据比较。现按来源预期核对，时间、指标、说话人和事实状态仍须一致。作者新作比较、将预期写成已实现等情形继续检查。</p>'
            '<p>留存候选只证明比较检查的误拒已纠正，不能代替整段来源、语义或最终章节验收。</p></section>')
    if stats.get('local_coverage_capacity_regression'):
        page+=('<section><h2>反复遗漏时重新分配篇幅</h2><p>真实运行给一组旧事实只剩19字符，连续两次候选虽通过来源与语义校验，仍丢失月份及机构、职务全称。现在仅在同一来源的事项连续两次覆盖失败、待补片段又长于局部空间时，允许重新分配整章篇幅。</p>'
            '<p>第一轮仍优先局部补写；扩大范围后，全部原段落加入保留要求，来源、语义、旧事项和600字符限制继续验收。触发范围调整本身不表示章节已经通过。</p></section>')
    if stats.get('checkpoint_source_pool_regression'):
        proof=stats['checkpoint_source_pool_regression']
        page+=('<section><h2>自动候选恢复时保留研究池</h2><p>实际检查点静态复核：原章节研究池 '+str(proof['previous_full_material_pool'])+
            ' 条，恢复后 '+str(proof['new_full_material_pool'])+' 条；少掉的原研究记录 '+str(len(proof['dropped_previous_evidence_ids']))+
            ' 条。这是研究输入保留检查，不是全部记录均已用于分析的声明。</p></section>')
    if stats.get('authenticated_review_resume_regression'):
        page+=('<section><h2>精确承接已完成的材料判断</h2><p>真实上一轮已有167条材料判断完成、1条未闭合。新检查点与已校验正文和原文展示完全相同，旧规则却因起始检查点文件哈希不同而拒绝续跑。</p>'
            '<p>现在额外核对真实请求来源、上一轮代码快照、原始资料、逐字正文及原文展示，再按来源、任务、正文、表格与展示的完整指纹校验每条判断。离线验证确认167条上下文完全相同；pending记录仍须真实重试，篇幅超限仍不能通过。</p></section>')
    if stats.get('numeric_source_name_regression'):
        page+=('<section><h2>来源名中的数字与完整语义复验</h2><p>实际修订明确了公司研发投入的主体，却因“21经济网”中的21被误当成新增事实数字而遭拒。现在仅对来源元数据明确支持、且用于来源归属的数字媒体名作区分；正文中的其他日期、金额与数量照常核对，网页标题数字不能借作事实。</p>'
            '<p>复验脚本在来源修订后检查整份候选，与生产流程保持一致；通过来源检查的未改段落也接受语义检查。修正数字误拦不等于该段或整章已经验收通过。</p></section>')
    if stats.get('tight_scope_regression'):
        page+=('<section><h2>纠正极小补写空间与失真压缩</h2><p>真实运行曾给新事项只留2字符，模型生成“担税”词条，该章仍未通过材料验收。另一组事实连续两次塞满47字符，限定条件与年份发生失真，均被语义检查拒绝。</p>'
            '<p>现在新事项剩余不足8字符即重新分配章内篇幅；连续两次写满同一较小局部空间、仍因相同来源的事实或语义问题被拒绝时，也允许扩大修订范围。38字符的首次补写仍先局部尝试。连接失败、单次失败、无关来源和格式错误本身不触发扩大。</p>'
            '<p>所有解锁段落进入保留要求，来源、语义、材料覆盖以及600/1600字符验收继续执行。触发规则的离线回归与真实样本结果分别列示。</p></section>')
    if stats.get('annual_meeting_year_regression'):
        page+=('<section><h2>会议年度与发生年份</h2><p>真实补写把“2025年度股东会”写成“2025年股东会”，模型语义核对曾漏过这一差别。新增检查阻止把会议报告年度换成发生年份；明确记载的发生日期仍可使用。</p>'
            '<p>原候选、原文与误判回执保留在统计中；拒绝旧候选的回归证明不等于新章节已经修正通过。</p></section>')
    if stats.get('conditional_commitment_regression'):
        page+=('<section><h2>阻止把附条件承诺写成欠缴事实</h2><p>一次旧版模型自动验收曾放行社保、公积金表述。直接核对所引法律意见书后发现，原文是如在指定期间未按时足额缴纳而受损时承担责任的附条件承诺，不能据此断言该期间实际欠缴。</p>'
            '<p>已增加通用程序校验：按原文的承诺、期间和缴纳事项检查条件；仅在有相应主体、期间和事项的直接事件证据时允许陈述已发生。另一个税收条件不能代替前述条件。真实旧句已被程序拦下，全部原文保留。历史自动结果与后续原文复核结果分别保存在完整统计中。</p></section>')
    route_rows=[]
    for name,key in [('王传福','wang'),('张勇','zhang')]:
        routing=stats['global_routing'][key]
        count=routing.get('counts',{})
        route_rows.append('<p>'+esc(name)+'：原先未分配 '+str(routing['initially_unassigned_records'])+
            ' 条；现分配至章节 '+str(count.get('chapter',0))+' 条；有具体理由留附录 '+
            str(count.get('appendix',0))+' 条。</p>')
    page+='<section><h2>全报告未分配材料复核</h2><p>原先未进入任何章节研究池的记录，已结合具体委托问题逐条复核。分配不等于正文采用或章节验收；不提高来源等级或个人推断权限。</p>'+''.join(route_rows)+'</section>'
    if stats.get('professional_field_retention'):
        lines=[]
        for name,key in [('王传福','wang'),('张勇','zhang')]:
            r=stats['professional_field_retention'][key]
            lines.append('<p>'+esc(name)+'：合格平台记录 '+str(r['qualified_professional_records'])+
                ' 条；当前完整表格引用 '+str(r['table_cited_records'])+' 条；另有 '+
                str(r['same_wording_records_retained_in_annex'])+' 条与表内原文相同、来源单独保留；遗漏不同字段记录 '+
                str(len(r['missing_distinct_field_records']))+' 条。</p>')
        page+=('<section><h2>平台原字段专项检查</h2>'+''.join(lines)+
            '<p>以上检查当前通用表格生成逻辑。相同原文不代表相同来源或独立核实，也不能代替旧报告其他章节的完整验收。</p></section>')
    replay_note=('<p>最终代码使用真实模型运行的同输入原始回执复验；来源、语义、事项及篇幅校验重新执行。历史接口异常的回放与新模型调用分别计数，真实调用记录保留在完整统计与试跑历史中。</p>'
        if any(r['summary']['scope'].startswith('controlled_') for r in run_data.values()) else '')
    page+='<section><h2>真实留存材料试跑</h2>'+replay_note+'<div class="scroll"><table><tr><th>样本</th><th>状态</th><th>研究记录/来源</th><th>分析引用记录/来源</th><th>正文引用记录/来源</th><th>分析字符</th><th>原文字符</th><th>轮次</th></tr>'+''.join(tr)+'</table></div></section>'+''.join(cards)
    page+='<section><h2>验证范围</h2><p>人物报告相关测试 '+str(stats['tests']['passed'])+' 项通过，包含300条不同记录不丢失、来源陈述不被误当成个人推断、无旧稿时自动补漏、第二轮定向修订、全报告闸门不能由单章通过替代。</p><p>已作静态文件与链接检查；未进行浏览器视觉验收。没有新增检索、发布网站或改动主工作目录。<a href="static-qa-results.json">静态核验结果</a></p></section></body></html>'
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({'output':str(out),'counts':stats['status_counts']},ensure_ascii=False))


if __name__=='__main__':main()
