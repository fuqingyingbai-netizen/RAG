"""Identical native evidence scope for the producer and independent reviewer."""
import hashlib
import re
from .company_evidence import source_body


def make_evidence_context(rows, originals=(), max_full_chars=48000):
    """Full small originals or explicit bounded excerpts, never fake full scope.

    The character budget only controls supplementary prompt context. All selected
    records remain in the normal payload and all originals remain in the task.
    """
    available={}
    for source in originals or ():
        get=source.get if isinstance(source,dict) else lambda k,d=None:getattr(source,k,d)
        available[str(get('id'))]=source
        available[str(get('url',''))]=source
    grouped={};raw_by_key={};remaining=max_full_chars
    for row in rows:
        for proof in row.get('provenance',[]):
            key=str(proof.get('source_id') or proof.get('source_url') or proof.get('evidence_id'))
            if key not in grouped:
                source=available.get(key) or available.get(str(proof.get('source_url')))
                raw,origin=source_body(source) if source is not None else ('','')
                raw_by_key[key]=raw if origin!='discovery_summary' else ''
                complete=bool(raw and origin!='discovery_summary' and len(raw)<=remaining)
                item={'source_id':proof.get('source_id'),'source_url':proof.get('source_url'),
                    'source_title':proof.get('source_title'),'source_kind':proof.get('source_kind'),
                    'visible_scope':'complete_original' if complete else 'bounded_native_excerpts',
                    'original_sha256':hashlib.sha256(raw.encode()).hexdigest() if raw else row.get('context',{}).get('original_sha256'),
                    'original_chars':len(raw) if raw else None,'native_excerpts':[]}
                if complete:item['complete_original']=raw;remaining-=len(raw)
                grouped[key]=item
            item=grouped[key]
            context=row.get('context') or {}
            excerpt={'information_id':row['information_id'],'selected_text':row['text'],
                'native_context':context.get('context_quote',''),'original_offset':proof.get('original_offset'),
                'reading_receipt':context.get('source_reading_coverage',{})}
            if excerpt not in item['native_excerpts']:item['native_excerpts'].append(excerpt)
    for key,item in grouped.items():
        raw=raw_by_key.get(key,'')
        if not raw or item['visible_scope']=='complete_original' or remaining<256:continue
        ranges=[]
        for excerpt in item['native_excerpts']:
            offset=excerpt['original_offset']
            if type(offset) is not int or not 0<=offset<len(raw):continue
            end=offset+len(excerpt['selected_text'])
            ranges.append((max(0,offset-1800),min(len(raw),end+1800)))
            # These are native header candidates, never inferred table bindings.
            headers=list(re.finditer(r'单位\s*[:：]|增减\s*[（(]%[）)]|币种\s*[:：]',raw[max(0,offset-8000):offset]))
            if headers:
                start=max(0,offset-8000)+headers[-1].start()
                ranges.append((max(0,start-250),min(len(raw),start+1000)))
        merged=[]
        for start,end in sorted(ranges):
            if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else:merged.append((start,end))
        slices=[]
        for start,end in merged:
            end=min(end,start+remaining)
            if end<=start:break
            slices.append({'start':start,'end':end,'text':raw[start:end]});remaining-=end-start
        if slices:item['surrounding_original_slices']=slices
    return {'sources':list(grouped.values()),'scope_rule':
        '阅读回执不等于本批看到了全文。只有visible_scope=complete_original且提供complete_original时可核对该原件整体；'
        '其他来源只可对所引片段及相邻上下文作判断。表头、单位、期间、指代与跨页续表须结合native_context；'
        '缺少关系时列具体缺字段，不能因每个单元格没重复单位就否定表头已给出的单位。'
        '不能把所引片段未列示写成公司或全库没有披露；不能把摘要称作全文。'
        '原文只给出“不适用”等栏目状态而未解释原因时，只写“该栏标注不适用”，不要扩写为“不存在”“未发生”或“未披露”。'
        '原文另有明确解释时可直接复述其解释；不能仅凭勾选状态推断控制权、变更、债券存续或表决权情况。'
        '全文用于定位、表源与完整性核对，新增实质结论须列明实际支持的信息ID；跨记录结论须列齐支持ID。'}


def attach_evidence_context(prompt, packet, marker):
    prefix,payload=prompt.rsplit(marker,1)
    import json
    return prefix+'\n写作与审稿共用的原文范围和表格语境：\n'+json.dumps(packet,ensure_ascii=False)+'\n'+marker+payload
