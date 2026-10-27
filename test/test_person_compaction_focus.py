"""Offline focused/adaptive compaction regressions; final guards still required."""
import json
import person_prose_budget as module


def test_compaction_keeps_all_originals_conservation_and_actual_body_but_not_old_unaccepted_tasks():
    original='若公司受损，由本人承担费用并放弃追索权。'
    data={'chapter':9,'facts':[{'evidence_id':'E-PFOCUSONE','original':original},
        {'evidence_id':'E-PFOCUSTWO','original':'另一条完整原文，仍然保留。'}],
        'prior_draft_analyses_not_evidence':[{'analysis':original,'evidence_ids':['E-PFOCUSONE']}],
        'existing_body_representations':{'literal_source_excerpts':[{'evidence_id':'E-PFOCUSONE','quote':original}]},
        'missing_items':[{'source_question':'UNVALIDATED_REPAIR_TASK'}],
        'previous_repair_diagnostics':[{'raw_revision':'UNACCEPTED_OLD_CANDIDATE'}]}
    seen=[]
    def invoke(role,prompt,emit):
        packet=json.loads(prompt.splitlines()[-1]);seen.append(packet)
        assert 'missing_items' not in packet and 'previous_repair_diagnostics' not in packet
        assert packet['facts']==data['facts'] and packet['existing_body_representations']==data['existing_body_representations']
        assert packet['prior_draft_analyses_not_evidence']==data['prior_draft_analyses_not_evidence']
        return json.dumps({'claims':[{'analysis':original,'evidence_ids':['E-PFOCUSONE']}]})
    answer=json.dumps({'claims':[{'analysis':original+'。'*90,'evidence_ids':['E-PFOCUSONE']}]})
    result,calls=module.compact_draft(answer,'离线压缩','',data,invoke,None,{},max_chars=100)
    assert calls==1 and seen and json.loads(result)['claims'][0]['analysis']==original
    assert data['missing_items'] and data['previous_repair_diagnostics']


def test_measured_overshoot_lowers_the_next_target_without_raising_the_budget():
    sizes=iter([130,90]);packets=[];audit={}
    def invoke(role,prompt,emit):
        packets.append(json.loads(prompt.splitlines()[-1]))
        return json.dumps({'claims':[{'analysis':'文'*next(sizes),'evidence_ids':['E-PFOCUSONE']}]})
    original=json.dumps({'claims':[{'analysis':'文'*150,'evidence_ids':['E-PFOCUSONE']}]})
    result,calls=module.compact_draft(original,'离线压缩','',{'chapter':9,'facts':[]},invoke,None,audit,max_chars=100)
    assert calls==2 and packets[1]['target_analysis_chars']<packets[0]['target_analysis_chars']
    assert audit['compression']['max_analysis_chars']==100
    assert audit['compression']['attempts'][1]['requested_target_analysis_chars']==packets[1]['target_analysis_chars']
    assert len(json.loads(result)['claims'][0]['analysis'])==90
