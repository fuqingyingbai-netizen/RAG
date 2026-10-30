"""Required proposal fields, distinct from research and commercial completion.

The deterministic tables form a content contract. Validation compares their
fields in the correct chapter, not keywords found anywhere in the document.
It does not certify the research conclusions or approve business commitments.
"""
import hashlib
import json
import re

VERSION = 'industry-proposal-content-v1-required-fields'


def _cell(value):
    import html
    # Intake and task labels are data, never new Markdown rows or headings.
    return html.escape(re.sub(r'\s+', ' ', str(value or '待确认')), quote=False).replace('|', '／')


def _table(key, chapter, title, headers, rows, pending=False):
    return dict(key=key, chapter=chapter, title=title, headers=headers, rows=rows, pending=pending)


def proposal_tables(scope=None, tasks=None):
    scope, tasks = scope or {}, tasks or []
    company = bool(scope.get('named_companies'))
    capital = scope.get('capital_market') == 'summary'
    research = [
        ('市场边界与需求', '在约定地域和截止日内核对规模、增速、渗透率；按实际业务区分ToB/ToC及其分母，全球对照范围另行确认。',
         '分市场数据与口径表', '逐项列定义、期间、地域、单位、原始出处；缺失与不适用分别说明。'),
        ('竞争与商业模式', '比较头部、腰部、初创与海外玩家的产品定位、收入结构、商业模式和用户粘性；份额与集中度另核分母。',
         '玩家比较及商业模式表', '比较对象与维度一致；企业样本不得代表行业总体。'),
        ('产品与技术', '比较功能、技术路线、部署形态、质量评测、性能、成本、迭代及成熟度；涉及模型时核对模型策略。',
         '同条件产品技术对比表', '列版本、环境、负载和测量方法；不具可比条件的项目单独说明。'),
        ('商业化指标', '按收费模式确认定价、付费率、ARPU（每用户平均收入）及留存率的适用性；不适用须说明原因。',
         '适用指标与定义清单', '列客户/用户范围、分母、观察期及收入成本口径；缺失不能填零。'),
        ('政策及情景', '核对具体义务、政策适用对象与施行日期；分析需求驱动、制约因素和可能情景。',
         '政策影响与情景条件表', '事实、来源预测与条件推论分列；新增情景金额须有计算依据。'),
        ('风险及综合判断', '识别行业、业务、技术及合规风险，说明作用对象、触发条件和影响；综合已有信息给出有边界的初步判断。',
         '风险矩阵及综合判断', '判断绑定依据与推理；缺证保持未知，评分不等于发生概率。'),
    ]
    if company:
        research += [
            ('指定企业经营', '仅对已指定企业核对工商股权、收入客户、供应链、研发新品、融资关系及合规诉讼。',
             '企业专项材料清单', '逐企业列出处和核验边界，与行业整体分析分开。'),
            ('指定企业管理层', '在授权范围内核对职责分工、管理风格、合作基础、历史贡献、口碑及潜在利益冲突。',
             '管理层待核事项表', '区分公开事实、受访观点和未证实线索，不把拟访谈写成已完成。'),
        ]
    if capital:
        research += [('资本市场专项', '在启用范围内核对融资、投资人、IPO路径、并购、估值和交易情绪。',
                      '资本事件与口径表', '注明日期、币种、轮次、估值口径和出处；不混入关闭的市场。')]

    groups = [('市场与产业链', {2, 4, 5}, '定义及统计口径确认后交付市场表与产业链分工'),
              ('政策与监管', {3}, '取得适用原文后交付义务与政策影响清单'),
              ('竞争与商业化', {6, 10, 11}, '确认样本和指标适用性后交付比较表及条件判断'),
              ('产品与技术', {7}, '取得版本、测试条件及成本材料后交付比较表')]
    if company:
        groups += [('指定企业专项', {12}, '企业清单及授权确认后交付专项核验结果')]
    if capital:
        groups += [('资本市场专项', {8, 9}, '期间及市场范围确认后交付资本事件表')]
    groups += [('风险与综合复核', {13, 14}, '完成前述核对后交付风险矩阵和综合判断'),
               ('其他专项及来源复核', set(), '按附录A的完成条件复核，保留来源定位')]
    bindings = {label: [] for label, _, _ in groups}
    for task in tasks:
        tid = str(task.get('task_id') or task.get('key') or '')
        if not tid:
            continue
        from industry_delivery import verification_task_chapters
        chapters = set(verification_task_chapters(task))
        label = next((label for label, numbers, _ in groups if chapters & numbers), groups[-1][0])
        if tid not in bindings[label]:
            bindings[label].append(tid)
    schedule = [(label, ('、'.join(bindings[label]) or '按本轮研究范围核对') + '；' + dependency,
                 '待确认', '待确认') for label, _, dependency in groups
                if label != groups[-1][0] or bindings[label]]
    schedule.insert(0, ('总周期与里程碑', '综合分项工作、资料提供和渠道等待后确认总体起止日期及交付节点', '待确认', '待确认'))

    resources = [
        ('国内公开资料', '官方统计、政策、公告、协会及可追溯研究报告', '拟使用；具体清单及可用性待核验', '资料负责人待确认；保留出处和截止日'),
        ('海外渠道', '境外原文及授权数据；仅在约定地域范围内或确认扩展后启用', '适用性、访问条件及授权待确认', '负责人待确认；范围变更须确认'),
        ('商业数据库', '行业统计、市场、专利等适用数据库', '可查询范围、授权及采购预算待确认', '获授权及预算批准后使用'),
        ('行业专家库', '针对本轮技术、商业化及政策问题筛选专家', '名单、专长、可联系性及利益冲突待确认', '联系人待确认；落实保密与记录安排'),
        ('上下游及客户访谈', '拟核对交易、应用场景、性能成本及实际需求', '受访对象、联系渠道及同意情况待确认', '实际开展后形成纪要，观点单列'),
    ]
    if company:
        resources += [('企业专项渠道', '工商、司法及授权经营资料；拟联系相关现/离职人员或合作方',
                       '查询权限、对象及联系渠道待确认', '仅限指定企业与授权内容')]
    deliverables = [
        ('中期简报', '可选；启动时确认是否交付及节点', '阶段发现、分歧与后续安排'),
        ('最终行业报告', '按约定研究范围交付；未解决问题保留状态', '正文、原始来源索引、适用数据及比较表、后续任务'),
        ('访谈纪要', '仅在实际完成且获允许的访谈后交付', '对象角色、日期、主题、观点归属与记录限制'),
        ('风险矩阵与评分', '风险矩阵区分信号与未知；仅对有效评估的维度给分', '总分须全部启用维度有效；未完成不得补分'),
    ]
    if company:
        deliverables += [('企业专项结果', '仅限已指定企业及确认范围', '独立证据清单、核验结果及局限')]
    if capital:
        deliverables += [('资本专项结果', '仅限本轮启用的资本市场范围', '事件、估值及交易数据的来源与统计口径')]

    return [
        _table('project', 1, '项目需求确认', ('确认事项', '当前内容', '确认要求'), [
            ('研究用途', scope.get('purpose') or '待委托方确认', '核对拟支持的业务决策'),
            ('核心动因', '待委托方确认', '说明启动调研的原因及优先解决的问题'),
            ('重点产品与对象', '以已选赛道和指定企业为起点；具体产品待确认', '确认产品、企业及排除项，避免自行扩大范围'),
        ], True),
        _table('methods', 2, '分析方法与本轮问题', ('分析层次', '方法与对象', '本轮使用方式'), [
            ('一般性分析', '产业链拆解、市场口径核对、竞争与政策比较、情景分析', '围绕已确认目的组织材料、比较与初步判断'),
            ('特殊性分析', '结合细分赛道、发展阶段、产品和敏感问题选择核验方法', '按下列本轮任务及附录A的动作、材料和完成条件执行'),
        ]),
        _table('research', 3, '具体研究要求与完成条件', ('研究事项', '具体内容与适用范围', '预期产物', '完成条件'), research),
        _table('resources', 4, '拟使用渠道与资源确认', ('渠道', '拟核验内容', '当前状态', '责任及启用条件'), resources, True),
        _table('schedule', 5, '分项工作与排期确认', ('研究工作包', '关联任务、依赖及交付节点', '预计工作日及起止日期', '负责人及确认人'), schedule, True),
        _table('deliverables', 5, '交付内容与适用条件', ('交付项', '适用条件', '验收内容'), deliverables),
        _table('team', 6, '拟任人员确认表', ('项目角色', '姓名及职位', '从业经验及擅长领域', '职责与投入'), [
            ('项目负责人', '待确认', '待确认', '范围、沟通及验收协调；投入工时待确认'),
            ('行业研究员', '待确认', '待确认', '资料核对、比较分析及拟开展访谈；投入工时待确认'),
            ('数据分析人员', '待确认', '待确认', '指标口径与数据核验；投入工时待确认'),
            ('行业专家', '待确认', '待确认', '技术与商业判断复核；参与方式及工时待确认'),
            ('质量复核人员', '待确认', '待确认', '来源、推理与交付内容复核；投入工时待确认'),
        ], True),
        _table('fees', 7, '报价确认表', ('费用项目', '计量单位及数量', '单价、金额及税费', '是否包含及批准人'), [
            (label, '待确认', '待确认', '待确认') for label in
            ('人员投入', '数据采购', '专家及渠道访谈', '差旅', '翻译及其他专项')
        ], True),
        _table('terms', 7, '商务与保密事项确认', ('确认事项', '待确认内容', '当前状态'), [
            ('报价汇总', '总金额、币种、含税与否、费用包含及排除项', '待双方确认'),
            ('付款安排', '付款节点、预付比例、支付期限及验收条件', '待双方确认'),
            ('变更与审批', '新增样本、范围或访谈的费用和周期，预算批准人', '待双方确认'),
            ('保密与资料管理', '无论是否形成委托，未经书面许可不向第三方披露；双方同等保密，确认访问权限、保管及归档删除安排', '条款待双方确认'),
        ], True),
    ]


def render_tables(scope=None, tasks=None):
    result = {}
    for spec in proposal_tables(scope, tasks):
        rows = [spec['headers'], ['---'] * len(spec['headers']), *spec['rows']]
        result[spec['key']] = '### ' + spec['title'] + '\n\n' + '\n'.join(
            '| ' + ' | '.join(_cell(v) for v in row) + ' |' for row in rows)
    return result


def _sections(proposal):
    result = {}
    for match in re.finditer(r'(?ms)^## (\d+)\. [^\n]+\n(.*?)(?=^## |\Z)', proposal):
        result[int(match[1])] = match[2]
    return result


def validate_proposal(proposal, scope=None, tasks=None):
    from .industry_template import INDUSTRY_PROPOSAL_OUTLINE
    headings = re.findall(r'^## (\d+)\. (.+)$', proposal, re.M)
    expected = [(str(i), title) for i, (title, _) in enumerate(INDUSTRY_PROPOSAL_OUTLINE, 1)]
    errors = []
    if headings != expected:
        errors.append({'code': 'chapter_structure', 'chapter': 0, 'message': '七章编号、顺序或标题不完整。'})
    sections = _sections(proposal)
    # Standalone callers lack the project scope. Infer which optional blocks to
    # inspect, but never claim this verifies the user's actual scope selection.
    effective_scope = scope if scope is not None else {
        'named_companies': ['待核对'] if '| 指定企业经营 |' in sections.get(3, '') else [],
        'capital_market': 'summary' if '| 资本市场专项 |' in sections.get(3, '') else 'none'}
    specs = proposal_tables(effective_scope, tasks)
    coverage, pending = [], []
    for spec in specs:
        blocks = list(re.finditer(r'(?ms)^### ' + re.escape(spec['title']) + r'\n(.*?)(?=^### |\Z)', sections.get(spec['chapter'], '')))
        rows = []
        for line in (blocks[0][1].splitlines() if blocks else []):
            if line.strip().startswith('|'):
                rows.append([c.strip() for c in line.strip().strip('|').split('|')])
            elif rows:
                break  # A later, unrelated table cannot fill this table's gaps.
        table_errors = []
        if len(blocks) > 1:
            table_errors.append('duplicate_requirement_table')
        if len(rows) < 2 or rows[0] != list(spec['headers']):
            table_errors.append('missing_table_or_columns')
        elif len(rows[1]) != len(spec['headers']) or not all(re.fullmatch(r':?-{3,}:?', c) for c in rows[1]):
            table_errors.append('invalid_table_separator')
        actual = {}
        for row in rows[2:]:
            if len(row) != len(spec['headers']):
                table_errors.append('row_column_mismatch')
                continue
            if row[0] in actual:
                table_errors.append('duplicate_requirement_row')
            actual[row[0]] = row
        for expected_row in spec['rows']:
            label = _cell(expected_row[0])
            row = actual.get(label)
            code = ''
            if row is None:
                code = 'missing_requirement_row'
            else:
                for column, value in enumerate(expected_row[1:], 1):
                    # Scope purpose and task links are checked against current
                    # context when supplied; free-standing checks report limits.
                    context_unknown = (scope is None and spec['key'] == 'project' and label == '研究用途' and column == 1
                        or tasks is None and spec['key'] == 'schedule' and column == 1)
                    if not row[column] or (not context_unknown and row[column] != _cell(value)):
                        code = 'incomplete_or_changed_required_field'
                        break
            coverage.append({'id': spec['key'] + ':' + label, 'chapter': spec['chapter'], 'requirement': label,
                'content_status': 'missing_or_changed' if code or table_errors else 'present',
                'completion_status': 'pending_confirmation' if spec['pending'] else 'planned_not_completed'})
            if code:
                errors.append({'code': code, 'chapter': spec['chapter'], 'requirement': label,
                               'message': f'第{spec["chapter"]}章“{label}”的内容或确认字段不完整。'})
            if spec['pending']:
                pending.append({'chapter': spec['chapter'], 'requirement': label})
        for code in dict.fromkeys(table_errors):
            errors.append({'code': code, 'chapter': spec['chapter'], 'message': f'第{spec["chapter"]}章“{spec["title"]}”表格结构不完整或重复。'})
    excluded = []
    for enabled, label, keys in (
            (bool(effective_scope.get('named_companies')), '企业与管理层专项', ('指定企业经营', '指定企业管理层', '企业专项渠道', '企业专项结果')),
            (effective_scope.get('capital_market') == 'summary', '资本市场专项', ('资本市场专项', '资本专项结果'))):
        if not enabled:
            excluded.append({'requirement': label, 'status': 'not_applicable', 'reason': '本轮未启用'})
            if scope is not None and any(re.search(r'(?m)^\| ' + re.escape(key) + r' \|', proposal.split('## 附录A', 1)[0]) for key in keys):
                errors.append({'code': 'disabled_scope_included', 'chapter': 3, 'message': f'本轮未启用的{label}仍被列为工作或交付。'})
    task_ids = list(dict.fromkeys(str(t.get('task_id') or t.get('key')) for t in (tasks or []) if t.get('task_id') or t.get('key')))
    return {'version': VERSION, 'passed': not errors, 'scope_verified': scope is not None,
        'task_binding_verified': tasks is not None, 'proposal_sha256': hashlib.sha256(proposal.encode()).hexdigest(),
        'scope_sha256': hashlib.sha256(json.dumps(effective_scope, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'errors': errors, 'requirements': coverage, 'pending_confirmations': pending, 'not_applicable': excluded,
        'task_ids': task_ids, 'requirement_count': len(coverage),
        'covered_count': sum(r['content_status'] == 'present' for r in coverage),
        'research_completion_status': 'not_evaluated', 'confirmation_status': 'pending'}


def quality_warning(diagnostic):
    messages = list(dict.fromkeys(e['message'] for e in diagnostic['errors']))
    return '；'.join(messages[:5]) + ('；其余缺项见建议书内容诊断。' if len(messages) > 5 else '')
