"""Person diagrams use selected, actor-bound records, never page-wide noun guesses."""
import json
import re

try:
    from .person_records import payload
    from .person_identity import relation_actor_is_target
    from .person_text import folded
except ImportError:
    from person_records import payload
    from person_identity import relation_actor_is_target
    from person_text import folded


def graph_nodes(project, cleaned_json):
    contract=getattr(project,'person_evidence_contract',None)
    if isinstance(contract,dict):
        chapters=contract.get('chapters',{})
        facts=(chapters.get(9) or chapters.get('9') or {}).get('facts',[])
        basis='chapter9_selected_source_statements'
    else:
        try:
            facts=json.loads(cleaned_json or '{}').get('facts',[])
        except (ValueError,AttributeError):
            facts=[]
        basis='legacy_direct_actor_statements_pending_review'
    intake=getattr(project,'person_research_intake',None) or {}
    organizations=(intake.get('person_anchor') or {}).get('known_affiliations',[])
    target=str(project.target_name or '')
    nodes={}
    generic={'本公司','公司','本集团','集团','该公司','其公司','企业','管理集团','主要工作经历'}
    def add(name,relation,eid='',typed=False):
        name=str(name or '').strip(' ，,。；;：:')
        if len(name)<3 or name in generic or folded(name)==folded(target):return
        if not typed and re.search(r'本公司|本集团|先生|女士|负责|担任|其控制的|的实体|在公开|因服务|基于|接任|辞任|主要工作经历',name):return
        if len(name)>65:return
        key=folded(name)
        if key not in nodes:
            nodes[key]=(name,relation+'（待核验）',eid or '用户定位线索')
    for fact in facts:
        if not isinstance(fact,dict) or fact.get('subject_scope','person')!='person' or fact.get('source_text_issue'):continue
        text=str(fact.get('fact') or '')
        eid=str(fact.get('evidence_id') or '')
        data=payload(text)
        if fact.get('claim_type')=='person_platform_record' and data.get('企业名称'):
            role=data.get('职位') or data.get('角色') or data.get('职务') or '关联记录'
            role='、'.join(map(str,role)) if isinstance(role,list) else str(role)
            add(data['企业名称'],('历史' if '历史记录' in text else '来源所列')+role[:12],eid,typed=True)
            continue
        if fact.get('literal_roster_row'):
            pattern=r'(?<![\u4e00-\u9fff])([\u4e00-\u9fffA-Za-z0-9·（）()]{3,45}?(?:股份有限公司|有限责任公司|有限公司|基金会|研究院|集团|基金|大学|学院))'
            for match in re.finditer(pattern,text):
                role=re.match(r'\s*(董事长|副董事长|执行董事|董事|理事长|副理事长|理事|总裁|总经理)',text[match.end():])
                if role:add(match[1],'来源所列'+role[1],eid)
        relation=r'(?P<relation>共同创办|联合创办|创立|创办|任职于|就职于|供职于|担任|出任|投资于|投资)\s*了?(?P<org>[\u4e00-\u9fffA-Za-z0-9·（）()]{2,40}?(?:股份有限公司|有限责任公司|有限公司|基金会|研究院|集团|基金|大学|学院))'
        for match in re.finditer(relation,text):
            if relation_actor_is_target(text,match.start(),target):
                add(match['org'],'来源所列'+match['relation'],eid)
        for organization in organizations:
            if folded(organization) not in folded(text):continue
            if folded(target) not in folded(text):continue
            if re.search(r'董事|股东|持股|持有|创办|创立|founder|chairman|director',text,re.I):
                add(organization,'来源所列关联',eid,typed=True)
    for organization in organizations:
        add(organization,'输入定位',typed=True)
    selected=list(nodes.values())[:10]
    project.person_relationship_graph_audit={'basis':basis,'nodes':[{'name':n,'relation':r,'evidence_id':e if e.startswith('E-') else None,'note':e} for n,r,e in selected],
        'verification':'source_statements_or_explicit_input_clues_not_independently_verified'}
    return selected
