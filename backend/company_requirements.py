"""Company-only, versioned questions and routes for the existing UI choices.

Routes describe implemented adapters, never assert live provider availability.
No score or legal responsibility is inferred from a tool result or an edge.
"""
from __future__ import annotations
import hashlib
import json

VERSION = 'company-question-contract-v1'
DISCLOSURE_DOMAINS = ['cninfo.com.cn', 'sse.com.cn', 'szse.cn', 'hkexnews.hk']
# key: (chapters, question, original fields, query terms, implemented routes)
QUESTIONS = {
    'identity': ([2, 3], '{target} 的全称、信用代码、登记主体及历史变更是否一致，集团与子公司如何区分？',
        ['企业全称', '统一社会信用代码', '登记状态', '注册资本及单位', '变更前后值', '变更/生效日期'],
        ['统一社会信用代码 登记 股东 公司章程 原文', '历史沿革 工商变更 生效 日期'], ['qcc_registration', 'qcc_profile', 'tyc_profile', 'xiniu_basic']),
    'judicial': ([9, 11], '{target} 在具体案件中是什么角色，谁承担何项义务，请求、裁判、申请和实际程序结果分别是什么？',
        ['案号', '当事人及角色', '义务承担主体', '请求金额与单位', '判赔金额与单位', '程序状态', '事件日期及含义', '相反信息'],
        ['案号 当事人 裁判文书 判项 执行 原文', '行政处罚决定 监管措施 整改 后续 原文'], ['qcc_risk', 'qcc_penalty', 'xiniu_risk']),
    'reputation': ([5, 8, 9, 11], '{target} 的负面或正面评价来自谁、涉及哪个主体和时期，是否有原件与后续回应？',
        ['被评价主体', '发布者', '发生/发布/回应日期', '评价原文', '事实依据', '反向信息', '调查/访谈方法'],
        ['投诉 评价 事件 回应 后续 原文', '员工 客户 满意度 调查 口径 报告'], ['xiniu_risk']),
    'ownership': ([2, 4, 7], '{target} 的股东、控制与任职关系在什么时期有效，关系本身与具体法律义务如何分别证明？',
        ['两端主体', '关系类型', '持股比例及精度', '任职角色', '有效起止日', '控制依据', '独立义务证据'],
        ['股东名册 实际控制人 表决权 持股比例 任期 原文'], ['qcc_shareholders', 'qcc_people', 'tyc_group']),
    'funding': ([3, 10, 12], '{target} 的融资是计划、签约、发行还是完成，毛额、费用、实际净额与到账主体和日期如何核对？',
        ['融资主体', '发行/签约/完成状态', '毛额', '费用', '实际净额', '币种单位', '收款主体', '日期含义', '使用用途'],
        ['融资 发行 配售 募集资金净额 费用 实际使用 原文'], ['xiniu_funding']),
    'management': ([4, 7, 8], '{target} 管理人员的身份、履历、任期及变动是否有具名原件，组织和人员指标是什么口径？',
        ['姓名及同名识别', '职务', '履历来源', '任职起止', '变动原因', '人员指标及范围', '实际义务主体'],
        ['董事 高管 任期 履历 换届 辞任 原文', '员工流失率 统计范围 计算公式 培训 报告'], ['qcc_people', 'tyc_people', 'xiniu_team']),
    'founder': ([3, 7], '{target} 创始人的身份、创业及任职经历由什么原件支持，与公司实际控制是否存在时间和主体差别？',
        ['姓名及身份锚点', '创业事件及日期', '任职及有效期', '控制关系来源', '同名/关联边界'],
        ['创始人 招股书 履历 历史沿革 实际控制人 原文'], ['qcc_people', 'tyc_people']),
    'competition': ([5, 6], '{target} 与哪些同行在何产品、地区和时期可比，市场份额和技术指标的方法及分母是什么？',
        ['同行主体', '产品/地区/期间', '统计口径及分母', '指标值及单位', '样本及方法', '来源立场'],
        ['同业 竞争 市场份额 统计口径 年度报告 产品 对标'], ['xiniu_market']),
    'business': ([6, 10], '{target} 的业务、客户和供应商关系是否有合同或披露原件，订单、交付、验收与回款如何区分？',
        ['合同两端主体', '产品/业务实质', '客户/供应商', '合同范围', '签约/交付/验收状态', '回款及期间', '关联关系'],
        ['主要客户 供应商 关联交易 合同 交付 验收 回款 年度报告'], ['qcc_profile', 'xiniu_basic']),
    'finance': ([3, 6, 10, 12], '{target} 收入、利润、现金流与偿债指标对应什么会计期间、币种、合并范围及调整口径，比较数是否一致？',
        ['会计期间', '合并/母公司范围', '币种及单位', '收入', '利润及扣非/调整口径', '经营现金流', '偿债项目', '重述比较数', '附注限定'],
        ['年度报告 半年度报告 财务报表 经营活动现金流量净额 比较数 附注 原文'], []),
    'policy': ([5, 11], '{target} 相关政策适用于哪个地区、行业和主体，生效与修订状态如何，是否已发生具体监管事件？',
        ['发布机关', '适用主体/地区', '文件原文', '发布/生效/修订日期', '适用条件', '具体事件与义务'],
        ['行业 政策 监管 适用范围 生效 修订 原文'], []),
    'risk': ([2, 6, 9, 10, 11, 12], '{target} 的治理、经营、财务、司法监管及关联责任分别有什么证据，缺证和采集失败如何保留？',
        ['风险维度', '证据是否存在', '证据可靠程度', '严重程度及依据', '责任主体', '事件及期间', '相反信息', '缺失项'],
        ['风险 经营异常 处罚 裁判 债务 现金流 关联交易 原文'], ['qcc_risk', 'qcc_penalty', 'xiniu_risk']),
    'technology': ([5, 6], '{target} 的知识产权、技术版本、测评及商业兑现分别由谁在什么条件下证明？',
        ['权利/技术主体', '专利或版本标识', '权利有效状态', '测评方法及样本', '商业收入及期间', '许可限制'],
        ['专利 知识产权 技术 测评 方法 商业化 年度报告'], ['tyc_patents']),
}
MODULE_KEYS = {
    '公司背景': 'identity', '诉讼/制裁': 'judicial', '负面新闻': 'reputation', '股东高管': 'ownership',
    '融资情报': 'funding', '管理团队': 'management', '创始人背景': 'founder', '竞品公司': 'competition',
    '上下游业务': 'business', '竞品情况': 'competition', '收入情况': 'finance', '行业政策': 'policy',
    '舆情': 'reputation', '行业市场': 'competition', '风险核查': 'risk', '技术实力': 'technology',
    '主体工商基本信息核查股东关系与治理底盘': 'identity', '历史沿革与成长质量': 'finance',
    '组织治理与运营管理评估': 'management', '主营业务真实经营情况核验': 'business',
    '核心管理团队（深度/基础）风险研判': 'management', '核心管理团队风险研判': 'management',
    '企业文化及人员流失情况': 'management', '企业司法负面核查': 'judicial',
    '定向穿透专项尽职调查': 'funding', '行业口碑、产品认可度与同业竞争地位研判': 'competition',
}
ROUTES = {
    'qcc_registration': ('qcc', 'get_company_registration_info', 'searchKey', None),
    'qcc_profile': ('qcc', 'get_company_profile', 'searchKey', None),
    'qcc_shareholders': ('qcc', 'get_shareholder_info', 'searchKey', None),
    'qcc_people': ('qcc', 'get_key_personnel', 'searchKey', None),
    'qcc_risk': ('qcc', 'get_company_risk_scan', 'searchKey', None),
    'qcc_penalty': ('qcc', 'get_administrative_penalty', 'searchKey', None),
    'tyc_profile': ('tyc', 'get_company_basic_profile', 'company_name', None),
    'tyc_people': ('tyc', 'get_company_people', 'company_name', None),
    'tyc_group': ('tyc', 'get_company_group_profile', 'company_name', None),
    'tyc_patents': ('tyc', 'search_patents', 'applicant', None),
    'xiniu_basic': ('xiniu', 'get_company_info', 'firm_name', '企业基本信息'),
    'xiniu_funding': ('xiniu', 'get_company_info', 'firm_name', '融资状况分析'),
    'xiniu_team': ('xiniu', 'get_company_info', 'firm_name', '团队人物及招聘分析'),
    'xiniu_market': ('xiniu', 'get_company_info', 'firm_name', '市场与行业分析'),
    'xiniu_risk': ('xiniu', 'get_company_info', 'firm_name', '风险评估'),
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def question_spec(module):
    return QUESTIONS.get(MODULE_KEYS.get(module, ''))


def build_requirements(modules, intake):
    target = str(intake.get('canonical_company_name') or intake.get('target_name') or '').strip()
    scope = {'target_name': target, 'official_identifier': str(intake.get('official_identifier') or ''),
             'as_of_date': str(intake.get('as_of_date') or '')}
    rows = []
    for module in dict.fromkeys(modules):
        key = MODULE_KEYS.get(module)
        if not key:
            rows.append({'requirement_id': 'CR-CUSTOM-' + fingerprint(module)[:16], 'module': module,
                         'version': VERSION, 'scope': scope, 'scope_sha256': fingerprint(scope),
                         'state': 'requires_specific_question', 'routes': [],
                         'question': f'{target} 的“{module}”需要明确核验事项和预期原件；不将标签等同可回答的问题。'})
            continue
        chapters, question, fields, terms, routes = QUESTIONS[key]
        planned = []
        for route in routes:
            provider, tool, argument, aspect = ROUTES[route]
            parameters = {argument: target}
            if aspect:
                parameters['aspect'] = aspect
            if route == 'tyc_patents':
                parameters.update(query=target, page=1, page_size=20)
            planned.append({'provider': provider, 'tool': tool, 'arguments': parameters,
                            'adapter_implemented': True, 'availability': 'requires_live_verification',
                            'result_is_not_original_or_answer_by_default': True})
        domains = (['court.gov.cn', 'wenshu.court.gov.cn', 'zxgk.court.gov.cn', 'creditchina.gov.cn', 'samr.gov.cn']
                   if key == 'judicial' else ['gov.cn', 'csrc.gov.cn', 'samr.gov.cn'] if key == 'policy'
                   else list(DISCLOSURE_DOMAINS))
        row = {'requirement_id': 'CR-' + key.upper() + '-' + fingerprint(module)[:8],
               'question_key': key, 'module': module, 'version': VERSION,
               'scope': scope, 'scope_sha256': fingerprint(scope), 'state': 'planned',
               'question': question.format(target=target), 'expected_original_fields': list(fields),
               'chapters': list(chapters), 'routes': planned,
               'authority_domains': domains, 'query_terms': list(terms),
               'route_order': ['professional_platform_and_authoritative_originals', 'gap_driven_public_web'],
               'acceptance': ['主体及期间绑定', '原文定位与字段单位完整', '限定和相反信息保留', '独立复核通过'],
               'stop_conditions': ['已回答且原件/冲突核验完整', '有界预算耗尽并保留缺口', '相同输入无进展则先诊断'],
               'budget_exhaustion_is_not_acceptance': True}
        row['input_sha256'] = fingerprint(row)
        rows.append(row)
    return rows


def bind_queries(rows, requirements):
    result = []
    for row in rows:
        key = MODULE_KEYS.get(row.get('module'))
        matching = [r for r in requirements if r['module'] == row.get('module') or
                    (key and r.get('question_key') == key)]
        if matching:
            row = {**row, 'company_requirement_ids': sorted({r['requirement_id'] for r in matching}),
                   'company_requirement_version': VERSION,
                   'company_requirement_scope_sha256': matching[0]['scope_sha256'],
                   'query_purpose': '；'.join(dict.fromkeys(r['question'] for r in matching))}
        result.append(row)
    return result


def platform_requirement_ids(requirements, provider, tool, arguments, *, planned=False):
    aspect=''
    # The existing Xiniu audit labels each get_company_info invocation by its
    # requested aspect; the underlying MCP tool retains its ordinary name.
    if provider=='xiniu' and tool.startswith('get_company_info:'):
        tool,aspect=tool.split(':',1)
        if not planned and arguments.get('aspect')!=aspect:return []
    return sorted({r['requirement_id'] for r in requirements for route in r.get('routes', [])
                   if route['provider'] == provider and route['tool'] == tool and
                   (not aspect or route['arguments'].get('aspect')==aspect) and
                   (planned or all(arguments.get(k) == v for k, v in route['arguments'].items()))})


def resume_gap_intake(intake, queries, requirements):
    """One bounded pass of proven gaps; existing coverage is not acceptance."""
    selected = []
    seen = set()
    for row in bind_queries(queries, requirements):
        key = fingerprint(row)
        if key not in seen:
            selected.append(dict(row))
            seen.add(key)
    return {**intake, 'company_resume_gap_queries': selected, 'max_search_rounds': 1}
