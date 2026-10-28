"""Map actual person form options to traceable questions and evidence routes.

Routes name capabilities already implemented by this application, not assumed
third-party MCP tool names. Identity clues are query seeds, not established facts.
"""
from person_identity import build_anchor

VERSION = 'person-requirements-v1'
SPECS = [
    ('biography', ['创始人底色画像（家庭/教育/履历）', '身份核验', '基础履历', '教育与履历', '个人背景'], [2],
     '哪些原文能核对目标身份、教育和历次任职，矛盾发生在哪个机构和时期？',
     '官方 简历 教育 任职 起止日期', ['official_biography', 'education_and_role_periods'],
     ['original_web', 'person_professional_identity', 'person_roles_current_and_historical']),
    ('behavior', ['人格特质与诚信评估', '公开表达与采访'], [3],
     '有哪些可定位的公开表达与具体行为，来源立场和相反材料是什么？',
     '采访 原文 公开信 具体行为 回应', ['dated_behavior', 'literal_attribution', 'counterevidence'], ['original_web']),
    ('operations', ['经营胜任力（战略/执行/创新）', '经营业绩', '企业经营与战略事件'], [4],
     '目标在具体经营或创新事件中承担何种职责，结果对应什么期间和口径？',
     '公告 职责 创新 决策 结果 报告期', ['personal_role', 'event_period', 'comparable_metrics'],
     ['original_web', 'affiliated_company_records']),
    ('management', ['识人用人与团队管控'], [5],
     '用人、授权和组织调整有哪些明确行为、权限与适用条件？',
     '授权 任免 组织调整 公告 条件', ['management_event', 'authority_and_conditions'], ['original_web']),
    ('team', ['核心管理团队背景', '团队与治理'], [6],
     '各团队成员的姓名、机构、职责及任职时期分别是什么？',
     '管理团队 董事 高管 简历 任职 期间', ['member_identity', 'member_roles_and_dates'],
     ['original_web', 'affiliated_company_records']),
    ('reputation', ['商业操守与行业口碑', '口碑与操守'], [7],
     '谁对目标作了何种具名评价，利益关系、原话、时期及目标回应是什么？',
     '具名 评价 采访 合同 履约 原文 回应', ['named_evaluator', 'relationship', 'original_quote', 'response'], ['original_web']),
    ('comparison', ['同业对标评估', '同业对标', '同业对标下综合能力与品行隐患'], [8],
     '对标人物的行业、发展阶段、职责、期间和指标是否可比？',
     '同行 创始人 董事长 同期 职责 指标 原文', ['peer_identity', 'industry_stage_role_period', 'comparable_metric'], ['original_web']),
    ('relations', ['关联利益冲突（体外公司/代持/关联交易）', '关联利益', '关联机构'], [9],
     '目标与组织的任职、持股或控制关系有何原文和有效期间，是否存在具体利益冲突？',
     '任职 持股 关联交易 披露 生效 日期', ['person_organization_relation', 'effective_period', 'conflict_event'],
     ['person_roles_current_and_historical', 'affiliated_company_records', 'original_web']),
    ('judicial', ['司法负面与诉讼核查', '司法信用', '信用与处罚'], [9, 12],
     '司法或信用记录的当事人是否为目标，角色、案号、程序、日期和结果是什么？',
     '当事人 案号 裁判文书 决定书 日期 结果', ['party_identity', 'case_number', 'procedural_role', 'disposition'],
     ['person_judicial_records', 'original_web']),
    ('personal_credit', ['个人信用与财务风险', '专项风险'], [9, 10, 12],
     '有哪些能直接归属目标的债务、担保或履约事项，哪些只是关联企业背景？',
     '本人 债务 担保 履约 协议 期间 原文', ['direct_person_obligation', 'conditions_and_period', 'company_boundary'],
     ['person_judicial_records', 'person_roles_current_and_historical', 'original_web']),
    ('governance', ['投后治理与退出风险', '投后治理及退出风险'], [11],
     '实际决策权、治理和退出条款的权利人、条件及生效期间是什么？',
     '董事会 授权 股东协议 退出 条件 生效', ['decision_authority', 'exit_terms', 'effective_conditions'], ['original_web']),
]


def requirements(intake):
    if intake.get('target_type', 'person') != 'person':
        return []
    anchor = intake.get('person_anchor') or build_anchor(intake)
    selected = intake.get('focus_modules') or []
    if isinstance(selected, str):
        selected = [selected]
    rows = []
    for key, labels, chapters, question, terms, expected, routes in SPECS:
        matches = [label for label in selected if label in labels]
        if not matches:
            continue
        rows.append({'requirement_id': 'R-P-' + key.upper(), 'origin': 'frontend_selection',
            'selected_labels': list(dict.fromkeys(matches)), 'target_name': intake.get('target_name') or '',
            'question': question, 'identity_anchors': anchor, 'query_terms': terms,
            'tool_capabilities': routes, 'expected_evidence': expected, 'chapters': chapters,
            'completion': '原文、主体、角色、有效时期及相反材料已核对；工具返回和网页命中不等于完成',
            'state': 'planned_not_verified'})
    mapped = {label for row in rows for label in row['selected_labels']}
    # An unrecognized future option remains visible rather than silently mapped
    # to a negative search or being declared complete.
    for label in selected:
        if label not in mapped:
            from person_provenance import stable_id
            rows.append({'requirement_id': stable_id('R-P-CUSTOM', str(label)),
                'origin': 'frontend_selection', 'selected_labels': [label],
                'target_name': intake.get('target_name') or '', 'question': str(label),
                'identity_anchors': anchor, 'tool_capabilities': [], 'expected_evidence': [],
                'query_terms': str(label), 'chapters': [], 'state': 'mapping_requires_review'})
    return rows


def query_rows(intake):
    result = []
    for req in requirements(intake):
        if not req['chapters']:
            continue
        anchor = req['identity_anchors']
        clue = next(iter(anchor.get('known_affiliations') or anchor.get('identity_anchors') or []), '')
        target = str(req['target_name']).replace('"', '')
        context = ' "' + str(clue).replace('"', '') + '"' if clue else ''
        result.append({'module': req['selected_labels'][0],
            'query': '"' + target + '"' + context + ' ' + req['query_terms'],
            'requirement_ids': [req['requirement_id']], 'person_chapters': req['chapters'],
            'research_question': req['question'], 'identity_context': anchor,
            'expected_evidence': req['expected_evidence'], 'tool_capabilities': req['tool_capabilities'],
            'search_tier': 'open_web', 'retrieval_reason': 'frontend_requirement_question'})
    return result


def bind_query_requirements(rows, intake):
    reqs = requirements(intake)
    for row in rows:
        matched = [r for r in reqs if row.get('module') in r['selected_labels']]
        if not matched:
            matched = [r for r in reqs if set(row.get('person_chapters') or []) & set(r['chapters'])]
        row['requirement_ids'] = list(dict.fromkeys([*(row.get('requirement_ids') or []),
                                                    *(r['requirement_id'] for r in matched)]))
    return rows
