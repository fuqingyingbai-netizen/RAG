"""Structured material-disposition reply for offline workflow test doubles."""
import json


def material_response(packet):
    rows=[]
    for f in packet['facts']:
        indices=[i for i,c in enumerate(packet.get('draft',[])) if f['evidence_id'] in c['evidence_ids']]
        rows.append({'evidence_id':f['evidence_id'],'disposition':'analysis' if indices else 'appendix',
            'matched_claim_indices':indices,
            'reason':'该原文已被测试草稿直接引用。' if indices else '该条作为原始来源的补充记录保留，未强加个人推论。'})
    return json.dumps({'material_reviews':rows},ensure_ascii=False)
