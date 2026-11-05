"""A chapter writer's placements, reviewed with the same native evidence."""
import html


def placements(answer,rows):
    supplied=answer.get('placements',[]) if isinstance(answer,dict) else []
    lookup={r['information_id']:r for r in rows};result={};errors=[]
    if not isinstance(supplied,list):return {},['invalid_placements']
    for item in supplied:
        if not isinstance(item,dict):errors.append('invalid_placement');continue
        iid=item.get('information_id')
        if iid not in lookup or iid in result:errors.append('unknown_or_repeated_placement');continue
        if item.get('destination') not in {'main','annex','exclude'} or not str(item.get('reason') or '').strip():
            errors.append('invalid_placement_reason');continue
        result[iid]=dict(item)
    return result,errors


def main_records(answer,rows):
    chosen,errors=placements(answer,rows)
    return [r for r in rows if chosen.get(r['information_id'],{}).get('destination','main')=='main'],chosen,errors


def placement_audit(rows,chosen,audit):
    if not chosen:return []
    verdicts=audit.get('placements') if isinstance(audit,dict) else None
    if not isinstance(verdicts,list):return ['missing_placement_review']
    by_id={v.get('information_id'):v for v in verdicts if isinstance(v,dict)}
    if set(by_id)!=set(chosen) or len(by_id)!=len(verdicts):return ['incomplete_placement_review']
    errors=[]
    for iid,p in chosen.items():
        v=by_id[iid]
        if v.get('destination')!=p['destination'] or v.get('supported') is not True or not str(v.get('reason') or '').strip():
            errors.append('unsupported_placement:'+iid)
        if p['destination']!='main' and v.get('critical_to_conclusion') is not False:
            errors.append('critical_or_unreviewed_information_outside_main:'+iid)
    return errors


def placement_prompt(chosen):
    import json
    if not chosen:return ''
    return ('\n本章写作者在同一次写作中提出以下去向。独立核对主文的重要性取舍，不能因为排到附件就默认通过。'
        '所有原文仍完整提供。关键限制、相反证据、会改变结论的条件不得转附件或排除；'
        '发现这类信息必须supported=false、critical_to_conclusion=true并说明。'
        'main信息仍执行全部双向事实与命题审稿；annex原句会原样保存在附件，exclude仅记录不采用理由。'
        'information数组只包含main去向的记录，这两类不放information、不要求复制到正文的spans，但必须在placements逐项核对其用途及重要性。'
        '另返回placements:[{information_id,destination,supported:true/false,critical_to_conclusion:true/false,reason}]，'
        'ID及去向须与提出的去向逐条对应；不明确是否重要就不能批准移出主文。提出去向：'+json.dumps(list(chosen.values()),ensure_ascii=False))


def accounted_ids(package):
    return {i for b in package.get('batches',[]) if b.get('accepted') for i in b.get('information_ids',[])}


def appendix_html(usage,editorial):
    lookup={r['information_id']:r for r in usage.get('records',[])};parts=[]
    for b in editorial.get('batches',[]):
        if not b.get('accepted'):continue
        for p in b.get('placements',[]):
            if p['destination']!='annex':continue
            r=lookup[p['information_id']]
            parts.append('<article id="'+html.escape(r['information_id'])+'"><h2>第'+str(b['chapter'])+'章补充资料</h2>'
                '<p>'+html.escape(p['reason'])+'</p><pre>'+html.escape(r['text'])+'</pre><p>'+html.escape(str(r.get('context') or {}))+'</p><p>'
                +html.escape('；'.join(r.get('evidence_ids',[])))+'</p></article>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>章节证据附件</title><style>body{max-width:960px;margin:40px auto;font:16px/1.7 sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-bottom:1px solid #ddd;padding:20px}</style><h1>章节证据附件</h1>'+''.join(parts)+'</html>') if parts else ''
