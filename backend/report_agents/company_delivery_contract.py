"""A verifiable release contract for every company, independent of its name.

Unknowns are allowed in a bounded public-information report. Missing identity,
missing actual business evidence, failed generation, unreviewed assertions and
failed export cannot be relabelled as a successful delivery.
"""
import hashlib
import io
import json
import re
import zipfile
import unicodedata
from collections import Counter
from xml.etree import ElementTree as ET

from .company_editorial import VERSION as EDITORIAL_VERSION, fingerprint, record_payload, compact, package_errors

VERSION = 'company-delivery-v2-reviewed-main-and-complete-evidence'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
CHAPTER_KEYS = ('summary','governance','history','operations','reputation','business',
                'management','people','judicial','diligence','risk_register','assessment')
MISSING_EVIDENCE_ERRORS = {
    'governance': {'第二章没有主体匹配的字段或历史事件证据'},
    'history': {'第三章没有可核对事件或成长数据'},
    'operations': {'第四章没有可核对的治理及运行记录'},
    'reputation': {'第五章没有可核对的评价及对标材料'},
    'business': {'第六章没有可核对的经营数据'},
    'management': {'第七章尚无可核对的管理团队记录'},
    'people': {'第八章尚无可核对的文化与人员记录'},
    'judicial': {'第九章尚无可核对记录'},
    'diligence': {'第十章尚无具体证据触发的专项核查对象'},
    'risk_register': {'尚未形成具体可追溯风险事项，需要补充原件核查'},
    'assessment': {'尚无可按原件和锚点评价的公司分项，需人工复核'},
}
CHAPTER_MATERIALS = {
    2:'对应目标法人的登记档案、股东名册、公司章程及变更原件',
    3:'按日期排列的设立、变更、业务节点原件，以及同口径经营数据',
    4:'组织架构、授权矩阵、议事规则及对应的会议和执行记录',
    5:'具名评价原件、调查方法、样本范围与同期间同口径行业比较数据',
    6:'具体业务、产品、产销、交付及收入披露，区分计划与实际结果',
    7:'正式任免公告、岗位与生效日期、履历及明确关联关系原件',
    8:'按人员范围、岗位和期间区分的人资统计、制度及执行记录',
    9:'精确主体标识、查询平台与时间范围、文书或查询原始回执',
    10:'具体交易对象、合同、用途、对价及履行凭证，区分收款人与付款人',
    11:'具体事项原件、事件主体和日期、程序状态及后续处理记录',
    12:'固定评分锚点要求的公司指标、期间、单位与原始计算依据',
}
QUESTION_MATERIALS = {
    '主体工商信息表':'目标适用司法辖区的登记档案或发行人身份原件、注册编号及登记日期',
    '股权与治理信息表':'股东名册、权益披露、表决权安排、公司章程及生效日期',
    '股东/实控人/关联方关系网图':'逐条持股、表决、任职或关联关系的原件与对应主体标识',
    '治理底盘判断':'治理章程、表决安排、关联交易审批及实际执行记录',
    '历史工商变更':'逐次登记变更档案、核准日期、变更前后字段及生效凭证',
    '业务发展历程与关键节点':'产品或服务发布、上线、投产、交付及终止原件和日期',
    '同口径成长质量核对':'相同主体、业务范围、币种和会计期间的经营指标及比较期原表',
    '历史遗留事项与核验边界':'具体历史事项的原始决定、履行/处理结果及后续状态',
    '组织架构合理性':'组织架构、部门与岗位职责、汇报层级及业务分工原件',
    '决策机制':'议事规则、权限划分、会议议案、表决及决议执行记录',
    '权责划分':'岗位责任、授权矩阵、审批权限及实际授权/审批样本',
    '执行流程':'业务与内控流程、控制测试、审计发现和整改闭环记录',
    '内部激励':'薪酬/股权激励方案、授予与归属记录、业绩条件和实际考核结果',
    '企业应变能力':'应急或业务连续预案、具体应对事件的决策时间线与执行结果',
    '组织创新能力':'研发立项、跨部门协作机制、项目评审、阶段验收及成果转化记录',
    '员工评价':'具名或可说明样本与时期的员工调查、原始评价及调查方法',
    '竞品评价':'具名竞品原始表述、评测方法、产品/版本、条件与发布时间',
    '合作方评价':'具名合作方的原始表述、合作范围、履约记录及可核对评价',
    '行业地位':'行业统计原件、统计机构、样本、地域、品类、期间及指标定义',
    '技术实力':'产品/技术版本、测试方法、基准条件、结果及可复现实验记录',
    '综合软实力':'可追溯品牌、合作、人才与组织评价的具体原件及其适用范围',
    '同业对标':'明确可比企业、产品/服务范围、同期间同口径指标及各自原始披露',
    '分部门业务运营数据核验表':'部门/业务分部定义、年度或期间经营披露、研发成果与销售或服务交付记录',
    '核心业务板块运营进展核验表':'具体产品或服务的发布、测试、上线、商用、验收及交付原件',
    '关键经营事实与风险研判':'业务分部披露、经营指标定义、客户或用户数据、收入及履约/回款依据',
    '视觉/图谱证据说明':'原图、坐标与标签、底层数据、来源页码及可复核的生成关系',
    '管理层履历与岗位配置':'正式人员名册、岗位、生效日期、任免原件及逐项履历依据',
    '任职变动与时间线':'任免/换届原件、候选与正式生效条件、岗位及日期',
    '产业资源及明确关联关系':'具名任职、投资、合作关系原件及关系有效期间',
    '管理能力与团队掌控力评估':'明确岗位职责、期前批准目标、原考核权重及同期实际执行记录',
    '派系斗争、人事动荡与商业腐败信号':'具体人员与事件的调查、决定或裁判原件和后续状态，区分指控与结论',
    '本章待核验事项':'管理团队待确认人员、岗位、来源冲突与需要补齐的任免/履历原件',
    '内部文化价值观与文化践行引导':'公开文化表述、具体制度、实施样本及可核对的员工反馈',
    '团队激励与人才结构现状':'岗位/职能/地区人员结构、招聘状态、薪酬与激励实施原始记录',
    '人才储备、培养与梯队建设':'培训对象、人数/人次/时数定义、培养计划、梯队配置及实施记录',
    '销售/研发/技术等核心岗位人员流失情况':'分岗位离职统计、人数、分母、原计算公式、统计范围与期间',
    '核验判断与具体缺口':'人员指标的口径说明及与具体判断有关的缺失原始统计或执行记录',
    '核心事实汇总':'目标主体标识、案号或事项编号、角色、程序状态及原始文书',
    '风险事项分类核查表':'文书全文、请求/裁判/执行阶段、金额性质与后续履行结果',
    '视觉证据/图谱证据':'司法原件页码、关系依据及逐节点证据，不能由聚合计数生成责任关系',
    '结论与行动建议':'具体事项的责任性质、履行结果及足以判断影响范围的公司或交易数据',
    '融资情况':'目标作为收款方的融资协议、完成状态、净额或实际到账凭证',
    '资金使用合规性':'明确资金来源、用途条款、授权/审批、实际支付及使用凭证',
    '战略布局':'具名投资、合作或布局原件、目标、完成条件与实际进展',
    '业务真实性':'具体产品/服务、合同、交付/验收、发票及回款之间的对应记录',
    '大额资金往来':'付款人、收款人、交易背景、合同、银行凭证、币种及期间',
    '客户指定专项':'委托方明确的专项问题、对象、范围与需要达到的验收条件',
    '技术/供应商/资金往来穿透':'具名技术/供应商关系、采购或研发合同、交付及资金往来对应凭证',
    '组织与管理风险':'具体治理或管理事件、权责主体、发生日期和处理结果',
    '业务与运营风险':'具体产品/服务、履约、质量或资金事件及影响和后续处理依据',
    '行业特殊风险':'与目标实际业务相关的监管要求、具体事项和原件，不能将模板问题当事件',
    '具体事项与有边界的判断':'具名事项的事件原件、适用范围、程序与执行状态及影响判断依据',
    '75项核查目录及扩展事项':'按每个适用问题需要的事件原件、查询范围及后续状态记录',
}


def question_materials(chapter,aspect):
    return QUESTION_MATERIALS.get(aspect,CHAPTER_MATERIALS[chapter])


# Layout labels are not company questions. Their evidence belongs to the
# substantive rows (or the existing deterministic score/checklist tables).
PRESENTATION_ASPECTS={'视觉/图谱证据说明','视觉证据/图谱证据','本章待核验事项',
    '核验判断与具体缺口','结论与行动建议','具体事项与有边界的判断','75项核查目录及扩展事项'}
QUESTION_LABELS={
    '分部门业务运营数据核验表':'各业务分部的收入、成本及经营成果能否按同一期口径比较',
    '核心业务板块运营进展核验表':'主要产品或服务在报告期达到何种实际交付状态',
    '主体工商信息表':'目标法人的登记身份与当前状态能否确认',
    '股权与治理信息表':'股东权益与表决权分别由谁持有',
    '股东/实控人/关联方关系网图':'持股、控制、任职及关联关系分别有哪些原件依据',
}
QUESTION_ACTIONS={
    '主体工商信息表':('向适用登记机关或发行人披露渠道取得登记或身份原件，逐项比对名称、编号、状态及生效日期。','主体身份未闭合，不能把相近名称的记录归于目标法人。'),
    '股权与治理信息表':('向公司秘书及适用披露渠道取得股东名册、权益和表决权文件，分别列明直接持有人、比例及日期。','不能把最大股东等称谓等同于登记持股比例或实际控制。'),
    '股东/实控人/关联方关系网图':('逐边登记持股、表决、任职或交易关系及其原件；无法定位的关系不进入图谱。','关系链未闭合，不能据相同姓名或合并口径穿透控制人。'),
    '治理底盘判断':('取得章程、审批权限及关联交易决议，抽取具体事项核对授权与实际执行。','制度存在与执行有效性需分别判断。'),
    '历史工商变更':('按登记机关档案逐次列出核准日期与变更前后字段，再核对是否已生效。','无法重建法人及股权的完整变更时间线。'),
    '业务发展历程与关键节点':('按公司历史披露与产品原页逐项登记发布、投产、交付或终止日期，分别标明计划与完成。','不能把发布计划当作已实现的成长节点。'),
    '同口径成长质量核对':('从年度及期间原表提取本期与比较期数据，先对齐合并范围、业务、币种与会计政策，再计算变化。','现有零散数值不能支持同口径增长判断。'),
    '历史遗留事项与核验边界':('按具体历史事项调取原始决定及后续处理凭证，核对是否履行、撤销或仍在持续。','不能把历史事件直接当作当前未解决风险。'),
    '组织架构合理性':('向公司取得架构及岗位职责文件，沿具体业务流程核对部门分工、汇报层级与责任空档。','无法判断组织配置与实际业务的匹配程度。'),
    '决策机制':('调取议事规则及具体会议议案、表决、决议与执行记录，逐步核对权限及生效条件。','不能仅凭规则名称认定决策机制有效。'),
    '权责划分':('比对岗位责任和授权矩阵，抽查同一事项的申请、审批及执行责任人。','无法判断职责是否重叠、缺失或越权。'),
    '执行流程':('按具体流程调取控制测试、审计发现和整改记录，追踪发现、责任人、期限及闭环证据。','流程文件不能代替执行有效性结论。'),
    '内部激励':('调取激励方案、授予及归属记录，逐项比对对象、条件、考核结果与实际兑现。','不能由福利或培训表述推断股权激励及激励效果。'),
    '企业应变能力':('选取已披露的具体应对事件，调取预案、决策时间线和执行结果；没有事件样本时不评价实效。','应急预案不能单独证明实际应变能力。'),
    '组织创新能力':('沿具体项目核对立项、跨部门评审、阶段验收和成果转化记录。','研发活动或投入不能单独证明组织创新结果。'),
    '员工评价':('取得具名原始评价或可说明样本与期间的调查，核对样本来源和调查方法后区分个案与整体。','无法由零散评价代表全体员工。'),
    '竞品评价':('定位具名竞品的原始评价，记录产品版本、测试条件、方法及发布时间。','不能从无来源评论推出产品优劣。'),
    '合作方评价':('定位具名合作方的原始表述，并与合作范围及履约记录对应核对。','合作公告不能替代合作方对实际履约的评价。'),
    '行业地位':('向原统计发布机构取得原始报告，核对品类、地域、样本、期间和指标定义，再判断能否排序。','自述排名及覆盖率不能替代可比市场地位结论。'),
    '技术实力':('取得对应版本的测试方法、基准条件和原始结果，区分发布主张、第三方测试及可复现结果。','不能把功能宣传直接当作技术领先或商业贡献。'),
    '综合软实力':('分别定位品牌、合作及人才评价的具名原件，说明每项评价的对象、样本与期间。','不同评价不能无定义地合并为整体实力评级。'),
    '同业对标':('先按实际产品或服务选择可比对象，再取得双方同期间同口径指标；条件不一致的项目单列。','未对齐范围的数据不能形成排名。'),
    '分部门业务运营数据核验表':('定位目标适用的年度或期间报告及分部附注，先确认分部定义，再核对各分部当期与比较期收入、成本及经营结果。','无法判断集团总量来自哪些分部，也不能把集团增长分配给单一业务。'),
    '核心业务板块运营进展核验表':('按公司实际披露的产品或服务逐项建立状态表，分别定位发布、测试、商业使用及验收交付原件和日期。','不能由平台定位或产品发布推定实际商用、验收或收入。'),
    '关键经营事实与风险研判':('将公司披露的指标定义、数据期与合并范围对应到原表，再核对合同、履约或回款依据；未获内部凭证的环节单列。','自述用户、客户或收入数据不能自动形成经营真实性闭环。'),
    '管理层履历与岗位配置':('从正式管理层名册及任免披露确认人员、岗位与生效日，再逐项核对履历原件。','无法判断当前岗位配置及履历真实性。'),
    '任职变动与时间线':('对照任免或换届决议逐次列出候选、批准、生效和离任日期。','候选提名不能当作已经任职。'),
    '产业资源及明确关联关系':('逐项定位人员任职、投资或合作文件，核对具名主体和关系有效期间。','背景相似或履历不能证明有效资源或关联关系。'),
    '管理能力与团队掌控力评估':('取得期前批准的责任目标、原权重及同期间实际执行结果，按原目标体系核对兑现情况。','高管观点、任期或股权不能替代管理执行评分。'),
    '派系斗争、人事动荡与商业腐败信号':('按具名人员与具体事件查找调查、决定或裁判原件，并追踪后续状态，分别标明指控与确认结论。','任职变更本身不能证明内斗或腐败，缺少记录也不构成排除。'),
    '内部文化价值观与文化践行引导':('将公司公开价值观与具体制度逐条对应，再取得实施样本和可核对员工反馈。','文化口号与实际践行需分别判断。'),
    '团队激励与人才结构现状':('向公司取得岗位、职能、地区及用工性质的人数分表，并核对激励方案的适用对象和兑现记录。','总体员工数不能说明人才结构或激励覆盖情况。'),
    '人才储备、培养与梯队建设':('取得培训计划、实际参加统计及梯队配置，分开核对人数、人次、时数和完成情况。','培训投入或招聘计划不能等同于人才储备成果。'),
    '销售/研发/技术等核心岗位人员流失情况':('取得分岗位离职人数、平均在册分母、期间和原计算公式，复算流失率并区分主动离职与其他变动。','不能用总人数变化推算核心岗位离职率。'),
    '核心事实汇总':('使用精确法人标识在适用司法或监管平台查询，保存平台、日期、范围、案号、角色及文书回执。','未完成对应范围查询前，不能认定有或无司法负面。'),
    '风险事项分类核查表':('逐案读取文书全文，分开列示请求、裁判与执行金额及当前程序状态，再查后续履行。','聚合数量和涉案金额不能当作败诉、损失或未履行金额。'),
    '融资情况':('从融资协议或发行披露核对收款主体、签署、交割、净额及到账状态。','意向、投资方出资和目标实际到账不能互相替代。'),
    '资金使用合规性':('沿明确资金来源比对用途条款、审批、支付及实际使用凭证。','公开融资用途不能证明资金已按用途支出。'),
    '战略布局':('按具名投资或合作逐项核对目标、完成条件及实际进展，不以签约替代完成。','不能从布局意向推出经营成效。'),
    '业务真实性':('按具体交易对应合同、交付验收、发票与回款，标明公开披露和待内部核验的环节。','产品存在与真实交易收入需分别验证。'),
    '大额资金往来':('向公司调取具名交易双方、合同及银行凭证，逐笔核对背景、币种、期间与支付方向。','不能将合同总额视作已收款或净流入。'),
    '客户指定专项':('先由委托方明确专项对象、范围与验收条件，再据此列出所需原件及核对步骤。','未确定委托问题时不声称已完成专项。'),
    '技术/供应商/资金往来穿透':('按具名供应商或技术关系对应采购或研发合同、交付、付款人与收款凭证。','技术合作或供应关系不能自动证明实际采购和资金流向。'),
    '组织与管理风险':('按具体治理事件定位责任主体、授权依据、发生日期与处理结果；无事件原件时仅保留核查问题。','模板问题不构成已发生的管理风险。'),
    '业务与运营风险':('按具体产品、履约、质量或资金事件核对原件、影响与后续处理。','无法仅凭经营宣传或一般行业风险给公司定级。'),
    '行业特殊风险':('按目标实际业务确认适用监管要求，再定位具体合规事项、决定及处理状态。','一般监管要求不等于目标存在违规。'),
}


def question_plan(chapter,aspect):
    action,impact=QUESTION_ACTIONS.get(aspect,('取得'+question_materials(chapter,aspect)+'，分别记录原件出处、适用主体、数据期及实际状态。',
        '该问题尚不能形成直接判断。'))
    return {'question':QUESTION_LABELS.get(aspect,aspect),'materials':question_materials(chapter,aspect),
            'action':action,'impact':impact}


def split_sections(report):
    return {int(m[1]): m[0].strip() for m in re.finditer(
        r'(?ms)^##\s*(\d+)[.、．][^\n]*\n.*?(?=^##\s*\d+[.、．]|\Z)', report or '')}


def report_hash(report):
    return hashlib.sha256((report or '').encode()).hexdigest()


def stamp_research_date(project,sections):
    result=dict(sections)
    cutoff=str((getattr(project,'company_research_intake',{}) or {}).get('as_of_date') or '')
    if cutoff and 1 in result:
        result[1]=re.sub(r'(?m)^研究截至日为\d{4}-\d{2}-\d{2}。资料原始时点以各条引用为准。\n*','',result[1])
        marker='研究截至日为'+cutoff+'。资料原始时点以各条引用为准。\n\n'
        result[1]=re.sub(r'(### 报告概述\s*\n)',lambda m:m[0]+'\n'+marker,result[1],count=1)
    return result


def delivery_requirements(intake):
    # An operator can add chapter requirements without hard-coding companies
    # or sectors. Identity and real operations are the minimum for this report.
    requested = intake.get('required_chapters') or []
    chapters = sorted({2, 6} | {int(i) for i in requested if str(i).isdigit() and 2 <= int(i) <= 12})
    scoring=intake.get('scoring_required')
    if type(scoring) is not bool:
        request=str(intake.get('special_requirements') or '')
        request=re.sub(r'(?:不需要|无需|不要求|不用|不必)[^。；\n]{0,16}(?:评分|评级|打分)','',request)
        scoring=bool(re.search(r'(?:必须|需要|要求|务必|完整|给出)[^。；\n]{0,12}(?:评分|打分|评级)|(?:评分|评级)[^。；\n]{0,10}(?:不得留空|必须完整|不允许缺项)',request))
    return {'required_chapters': chapters, 'scoring_required': scoring,
            'scope': '公开资料桌面研究；未取得的访谈、流水、现场及内部验证不声明已完成。'}


def evidence_repair_queries(target, contract, outline):
    queries = []
    for task in contract.get('repair_tasks', []):
        chapter = task.get('chapter')
        if type(chapter) is not int or not 2 <= chapter <= 12: continue
        topic = task.get('question') or outline[chapter-1][0]
        query = '"' + target.replace('"', '') + '" ' + topic + ' 原始披露 原文'
        queries.append({'query': query, 'module': outline[chapter-1][0], 'search_tier': 'authority_first',
                        'authority_required': 1, 'preferred_providers': ['tavily','exa','serper','bocha'],
                        'delivery_repair_chapter': chapter})
    return list({q['query']:q for q in queries}.values())[:4]


def unreviewed_chapters(usage,editorial):
    chapters={b['chapter'] for b in editorial.get('batches',[]) if not b.get('accepted')}
    for row in usage.get('records',[]):
        if row.get('decision',{}).get('status') not in {'use','exclude'}:
            chapters.update(n for n in row.get('chapters',[]) if type(n) is int)
    return chapters


def fill_evidence_gaps(sections, editorial, outline, *, usage=None):
    """Answer unavailable questions with specific scope and an executable plan."""
    from .company_governance import _table
    result = dict(sections)
    present = {f['chapter'] for f in editorial.get('findings', [])}
    pending=unreviewed_chapters(usage or {},editorial)
    for chapter in range(2,13):
        if chapter in pending:
            notice='### 正文核对尚未完成'
            result[chapter]=result.get(chapter,f'## {chapter}. '+outline[chapter-1][0]).split(notice,1)[0].rstrip()+\
                '\n\n'+notice+'\n\n本章信息用途或正文语义核对尚未完成。已解析的原始字段与事件记录保留供复核，当前稿件不能作为验收通过的正文；核对失败不代表公司没有相关事项。'
            continue
        if chapter in present or chapter==12: continue
        title, aspects = outline[chapter-1]
        lines = [f'## {chapter}. {title}', '', '### 公开资料判断条件', '',
                 '本轮已接纳原文尚不足以就下列问题形成直接判断；该范围限制不代表公司不存在相关事项，也不据此给公司定风险等级。', '']
        rows = []
        for aspect in aspects:
            if aspect in PRESENTATION_ASPECTS:continue
            plan=question_plan(chapter,aspect)
            rows.append([plan['question'],plan['impact'],plan['action']])
        lines += _table(['需回答的问题','目前判断范围','核验动作'], rows)
        if chapter in {11,12}:
            # Preserve deterministic risk checklists and the null-score rubric.
            result[chapter] = result.get(chapter,'').split('### 公开资料判断条件',1)[0].rstrip() + '\n\n' + '\n'.join(lines[2:])
        else: result[chapter] = '\n'.join(lines)
    return result


def followup_chapter(project,outline):
    """List concrete unresolved questions, without quotas or stale generic gaps."""
    from .company_governance import _table
    editorial=getattr(project,'company_editorial_package',{}) or {}
    covered={(f['chapter'],f['aspect']) for f in editorial.get('findings',[])}
    required=delivery_requirements(getattr(project,'company_research_intake',{}) or {})
    rows=[]
    for chapter in range(2,12):
        for aspect in outline[chapter-1][1]:
            if (chapter,aspect) in covered or aspect in PRESENTATION_ASPECTS:continue
            plan=question_plan(chapter,aspect)
            rows.append([f'第{chapter}章 '+plan['question'],plan['impact'],plan['action'],
                '高' if chapter in required['required_chapters'] else '中'])
    for dimension in (getattr(project,'company_assessment_package',{}) or {}).get('dimensions',[]):
        if dimension.get('score') is not None:continue
        from .company_assessment import SCORE_FOLLOWUP
        rows.append(['第12章 '+str(dimension.get('name') or dimension.get('id') or '未命名分项'),
            ('评分权重'+str(dimension['weight'])+'%；' if dimension.get('weight') is not None else '原权重未载；')+
            '未评分原因：'+str(dimension.get('reason') or '原始评分定义待恢复，不能计算'),
            SCORE_FOLLOWUP.get(dimension.get('id'),'恢复原始评分定义后再取得原件，不填默认分。')+
            (' 按第12章该分项原锚点核验。' if dimension.get('anchors') else ' 原始锚点待恢复，不计算。'),
            '高' if required['scoring_required'] else '中'])
    for conflict in editorial.get('conflicts',[]):
        rows.append([f'第{conflict["chapter"]}章 '+conflict['entity']+' '+conflict['field']+' '+conflict['period'],
            '同一显式口径原值有差异，正文保留各自来源，尚未择一认定。',
            '逐份比对原件的主体、数据期、单位、修订版本与后续更正；取得解释前不平均或合并。','高'])
    lines=['## 14. 后续研究建议','',
        '以下为下一阶段建议事项，本轮未开展现场、访谈或银行流水核验。高优先级用于核心必答项及已发现的原值差异，中优先级用于扩展判断和非必需评分；不代表公司风险等级。','']
    if rows:lines+=_table(['待核验问题','当前判断边界','下一步动作及所需原件','优先级'],rows)
    else:lines+=['当前已接纳原文未形成额外的结构化补证任务；不据此认定全面尽调完成。']
    return '\n'.join(lines)


def diagnostic_requires_review(project, key, report):
    diagnostic = getattr(project,'company_'+key+'_diagnostic',{}) or {}
    if not diagnostic.get('degraded'): return False
    errors = diagnostic.get('errors') or []
    if not errors or not set(errors) <= MISSING_EVIDENCE_ERRORS.get(key,set()): return True
    contract = getattr(project,'company_delivery_contract',{}) or {}
    review = getattr(project,'company_document_review',{}) or {}
    if contract.get('status') != 'passed' or review.get('status') != 'passed' or review.get('report_sha256') != report_hash(report):
        return True
    chapter = CHAPTER_KEYS.index(key)+1
    editorial = getattr(project,'company_editorial_package',{}) or {}
    # A general semantic parser can recover relevant records missed by a
    # specialized table parser, but only checked, present narrative counts.
    if any(f['chapter']==chapter for f in editorial.get('findings',[])): return False
    if chapter in contract.get('requirements',{}).get('required_chapters',[]): return True
    section = split_sections(report).get(chapter,'')
    if chapter==12:
        # The existing rubric already gives the exact dimension, weight,
        # unscored reason and anchor. Do not add self-referential gap rows.
        from .company_assessment import RUBRIC
        dimensions=(getattr(project,'company_assessment_package',{}) or {}).get('dimensions',[])
        return not ([d.get('id') for d in dimensions]==[d['id'] for d in RUBRIC] and
            all(d.get('score') is None and d.get('reason') and d.get('anchors') and
                compact(d['name']) in compact(section) and compact(d['reason']) in compact(section) and
                compact(d['anchors']) in compact(section) for d in dimensions) and '未评分' in section)
    return not ('### 公开资料判断条件' in section and '| 核验动作 |' in section)


def assess_delivery(project, report):
    usage = getattr(project, 'company_information_usage_package', {}) or {}
    editorial = getattr(project, 'company_editorial_package', {}) or {}
    review = getattr(project, 'company_document_review', {}) or {}
    intake = getattr(project, 'company_research_intake', {}) or {}
    requirements = delivery_requirements(intake); errors = []; tasks = []
    corpus_review=getattr(project,'company_source_review_package',{}) or {}
    material_review_complete=corpus_review.get('diagnostic',{}).get('all_candidate_windows_reviewed') is True
    records = [r for r in usage.get('records', []) if r.get('decision', {}).get('status') == 'use']
    reading_format=getattr(project,'company_reading_mode','detailed')
    if reading_format not in {'detailed','analysis_with_annex'}:errors.append('报告阅读形式无效，不能完成交付验收')
    if reading_format=='analysis_with_annex':
        from .company_presentation import package_errors as presentation_errors,main_usage,presentation_scope,annex_errors
        presentation=getattr(project,'company_presentation_package',{}) or {}
        issues=presentation_errors(presentation,usage,str(project.target_name),presentation_scope(project))
        if issues:errors.append('正文与证据附件取舍回执未通过：'+'、'.join(issues))
        annex=getattr(project,'company_evidence_annex_html','') or ''
        manifest=getattr(project,'company_evidence_annex_manifest',{}) or {}
        if (manifest.get('sha256')!=hashlib.sha256(annex.encode('utf-8')).hexdigest() or
                manifest.get('native_input_sha256')!=fingerprint([record_payload(r) for r in usage.get('records',[])]) or
                manifest.get('information_records')!=len(usage.get('records',[]))):
            errors.append('完整证据附件与当前原文或内容哈希不一致')
        if not annex or annex_errors(usage,annex,presentation):errors.append('完整证据附件存在原文缺失、改写、范围出处变动或重复编号')
        from .company_main_focus import package_errors as focus_errors
        focus=getattr(project,'company_main_focus_package',{}) or {}
        issues=focus_errors(focus,usage,presentation,str(project.target_name),presentation_scope(project))
        if issues:errors.append('正文关键事实与限定条件取舍回执未通过：'+'、'.join(issues))
        records=main_usage(usage,presentation,focus)['records']
    if editorial.get('version') != EDITORIAL_VERSION:
        errors.append('缺少本轮逐信息语义精编与独立审稿结果')
    if editorial.get('input_sha256') != fingerprint([record_payload(r) for r in records]):
        errors.append('精编依据与当前原文、归因或用途决定不一致')
    receipt_errors=package_errors(editorial,records,str(project.target_name))
    if receipt_errors:
        errors.append('正文精编回执复验未通过：'+'、'.join(receipt_errors))
    if usage.get('diagnostic', {}).get('pending_information_ids'):
        errors.append('仍有信息未完成用途审查')
    if editorial.get('diagnostic', {}).get('pending_information_ids') or editorial.get('diagnostic', {}).get('failed_batches'):
        errors.append('仍有信息未通过正文语义保留核对')
    if not records or not editorial.get('findings'):
        errors.append('没有形成可核对的正文实质内容')
    represented = {i for f in editorial.get('findings', []) for i in f['information_ids']}
    if represented != {r['information_id'] for r in records}:
        errors.append('实际精编段落未覆盖全部应进入正文的信息' if reading_format=='analysis_with_annex' else '实际精编段落未覆盖全部已接纳可用信息')
    sections = split_sections(report)
    body='\n\n'.join(text for chapter,text in sections.items() if 2<=chapter<=12)
    for row in usage.get('records',[]):
        if row.get('decision',{}).get('status')!='exclude':continue
        ctx=row.get('context') or {};field=ctx.get('field') or ctx.get('metric');value=ctx.get('value')
        literal=len(compact(row.get('text','')))>=12 and any(compact(row['text']) in compact(paragraph) and
            any(eid in paragraph for eid in row.get('evidence_ids',[]))
            for paragraph in body.split('\n\n'))
        table=bool(field and value is not None and any(str(field) in line and
            any(compact(str(value))==compact(c) or (ctx.get('unit') and compact(str(value))+compact(ctx['unit'])==compact(c))
                for c in line.strip().strip('|').split('|')) and
            any(eid in line for eid in row.get('evidence_ids',[])) and
            (not ctx.get('period') or '未载' in str(ctx['period']) or str(ctx['period']) in line)
            for line in body.splitlines() if line.lstrip().startswith('|')))
        if literal or table:errors.append('排除清单与实际正文出现冲突：'+row['information_id'])
    for f in editorial.get('findings', []):
        if compact(f['text']) not in compact(sections.get(f['chapter'], '')):
            errors.append('核对通过的段落在最终正文中丢失或被改写：' + f['finding_id'])
    for chapter in requirements['required_chapters']:
        direct = [r for r in records if r['decision'].get('chapter') == chapter
                  and r.get('context', {}).get('scope') not in {'industry_context', 'unrelated', 'related_background'}
                  and r.get('evidence_ids')]
        if not direct:
            errors.append(f'第{chapter}章缺少回答核心问题的目标主体证据')
            if material_review_complete:tasks.append({'chapter': chapter, 'priority': 'high',
                'question': '确认目标法人及登记/发行人身份' if chapter == 2 else '确认目标公司具体产品、服务及实际经营状态',
                'action': '定向获取对应主体原件并重跑材料接纳、成稿及验收，不能以章节占位通过。',
                'source_types': ['登记机关或交易所发行人原件'] if chapter == 2 else ['公司产品原页', '年度/期间经营披露', '可追溯业务记录']})
    assessment = getattr(project, 'company_assessment_package', {}) or {}
    dimensions = assessment.get('dimensions', [])
    unscored = [d.get('id') for d in dimensions if d.get('score') is None]
    if requirements['scoring_required'] and (not dimensions or unscored):
        errors.append('委托要求完整评分，但评分原始指标不足')
        if material_review_complete:tasks.append({'chapter': 12, 'priority': 'high', 'question': '补齐评分锚点对应的原始指标',
                      'dimensions': unscored, 'action': '按固定权重和原锚点定向补原件；不得用材料数量或默认分填补。'})
    source_map = usage.get('source_map', {}).get('diagnostic', {})
    if source_map.get('unmapped_accepted_passages') or source_map.get('literal_offset_failures'):
        errors.append('原文定位或已接纳片段的使用映射未通过')
    if review.get('status') != 'passed' or review.get('report_sha256') != report_hash(report):
        errors.append('最终正文缺少对应相同字节内容的全文审稿通过记录')
    if review.get('issues'):
        errors.append('最终全文仍有未解决的审稿问题')
    for conflict in editorial.get('conflicts', []):
        section = sections.get(conflict['chapter'], '')
        if conflict['boundary'] not in section or any(str(v['value']) not in section for v in conflict['values']):
            errors.append('同口径差异未在实际交付章节保留：' + conflict['conflict_id'])
    errors = list(dict.fromkeys(errors))
    return {'version': VERSION, 'target_name': str(project.target_name), 'report_sha256': report_hash(report),
            'reading_format':reading_format,
            'editorial_input_sha256': editorial.get('input_sha256'), 'status': 'passed' if not errors else 'needs_repair',
            'errors': errors, 'repair_tasks': tasks, 'requirements': requirements,
            'unscored_dimensions': unscored, 'scope': requirements['scope'],
            'export_status': 'not_checked', 'delivery_ready': False}


def validate_docx(docx_payload, report, outline):
    """Verify the actual bytes to be saved, including all prose and citations."""
    errors = []; text = ''; hyperlinks = 0
    try:
        from docx_exporter import _clean_inline_markdown
        with zipfile.ZipFile(io.BytesIO(docx_payload)) as archive:
            if archive.testzip() is not None: errors.append('docx_corrupt_zip')
            root = ET.fromstring(archive.read('word/document.xml'))
            paragraphs = [''.join(t.text or '' for t in p.iter(W + 't')) for p in root.iter(W + 'p')]
            text = '\n'.join(paragraphs)
            hyperlinks = len(list(root.iter(W + 'hyperlink')))
            # The same citation projection must apply on both sides. A native
            # hyperlink can sit before a page locator or a substantive clause;
            # leaving its [E-ID] in XML text breaks an otherwise exact match.
            # Only explicit citation markers disappear, never trailing prose,
            # quantities, conditions, page locators or ordinary identifiers.
            citation_pattern = r'\[E-[A-Z0-9-]{6,}\]'
            normalized = compact(re.sub(citation_pattern, '', text, flags=re.I))
            heading_numbers=[]
            for p in root.iter(W+'p'):
                style=p.find('./'+W+'pPr/'+W+'pStyle')
                if style is None or style.get(W+'val')!='Heading1':continue
                heading=''.join(t.text or '' for t in p.iter(W+'t'))
                m=re.match(r'\s*(\d+)[.、．]',heading)
                if m:heading_numbers.append(int(m[1]))
            if heading_numbers!=list(range(1,len(outline)+1)):errors.append('docx_chapter_order_or_count')
            def visible(value):
                # Only explicit citation markers are formatting. A native
                # hyphenated name (e.g. Remote-Northstar) is company content.
                value=re.sub(citation_pattern, '', value,flags=re.I)
                return compact(_clean_inline_markdown(value))
            actual_rows=[[visible(''.join(t.text or '' for t in tc.iter(W+'t'))) for tc in tr.findall(W+'tc')]
                         for tr in root.iter(W+'tr')]
            for number, (title, _) in enumerate(outline, 1):
                if compact(title) not in normalized: errors.append('docx_missing_chapter:' + str(number))
            sections = split_sections(report)
            for number, section in sections.items():
                if number==13: continue
                # XML structure changes line/table layout, never prose content.
                for line in section.splitlines():
                    if not line.strip() or line.lstrip().startswith(('#', '!', '>')): continue
                    if line.lstrip().startswith('|'):
                        cells=[c.strip() for c in line.strip().strip('|').split('|')]
                        if all(re.fullmatch(r'[-: ]*',c) for c in cells):continue
                        expected_row=[visible(c) for c in cells]
                        if not any(len(actual)>=len(expected_row) and all(not e or e==actual[i] for i,e in enumerate(expected_row))
                                   for actual in actual_rows):
                            errors.append('docx_table_row_changed:'+str(number))
                    else:cells=[line]
                    for cell in cells:
                        plain = visible(cell).lstrip('- ')
                        if len(plain) >= (4 if len(cells)>1 else 12) and plain not in normalized:
                            errors.append(('docx_missing_table_cell:' if len(cells)>1 else 'docx_missing_prose:') + str(number))
                            break
            cited={eid.upper() for n,section in sections.items() if 1<=n<=12 for eid in re.findall(r'\[(E-[A-Z0-9-]{6,})\]',section,re.I)}
            expected={'evidence_'+re.sub(r'[^A-Za-z0-9_]','_',eid) for eid in cited}
            actual={h.get(W+'anchor') for h in root.iter(W+'hyperlink')}
            bookmarks={b.get(W+'name') for b in root.iter(W+'bookmarkStart')}
            if expected-actual or expected-bookmarks:
                errors.append('docx_missing_native_citation_links')
    except Exception as exc:
        errors.append('docx_integrity:' + type(exc).__name__)
    return {'docx_integrity_status': 'passed' if not errors else 'failed', 'docx_integrity_errors': list(dict.fromkeys(errors)),
            'docx_sha256': hashlib.sha256(docx_payload).hexdigest(), 'docx_native_hyperlinks': hyperlinks}


def audit_pdf_layout(pdf_payload, docx_payload):
    """Check actual rendered text, page bounds and extraction glyph failures."""
    errors = []; pages = 0; rendered_chars=[]
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_payload)) as pdf:
            pages = len(pdf.pages)
            if not pages: errors.append('rendered_pdf_has_no_pages')
            for number, page in enumerate(pdf.pages, 1):
                chars = page.chars
                if not chars and not page.images: errors.append('blank_rendered_page:' + str(number))
                if any(c['x0'] < -1 or c['top'] < -1 or c['x1'] > page.width + 1 or c['bottom'] > page.height + 1 for c in chars):
                    errors.append('rendered_text_outside_page:' + str(number))
                baselines={}
                for char in chars:
                    if str(char.get('text','')).strip():baselines.setdefault(round(char['top']),[]).append(char)
                for line in baselines.values():
                    line.sort(key=lambda c:c['x0'])
                    for a,b in zip(line,line[1:]):
                        width=min(a['x1']-a['x0'],b['x1']-b['x0'])
                        if width>1 and min(a['x1'],b['x1'])-max(a['x0'],b['x0'])>.65*width and a['text']!=b['text']:
                            errors.append('rendered_text_overlap:' + str(number));break
                text = page.extract_text() or ''
                if '\ufffd' in text: errors.append('rendered_replacement_glyph:' + str(number))
                rendered_chars.extend(c.get('text','') for c in chars)
        with zipfile.ZipFile(io.BytesIO(docx_payload)) as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
            # PDF line order interleaves table columns and page continuations.
            # Compare rendered Unicode inventories, alongside XML row equality
            # and geometry, rather than falsely requiring contiguous cell text.
            expected=[];field_depth=0
            dynamic_simple_text={id(t) for f in root.iter(W+'fldSimple')
                if re.match(r'\s*(?:PAGE|PAGEREF|NUMPAGES|TOC)\b',f.get(W+'instr',''),re.I)
                for t in f.iter(W+'t')}
            for element in root.iter():
                if element.tag==W+'fldChar':
                    kind=element.get(W+'fldCharType')
                    if kind=='begin':field_depth+=1
                    elif kind=='end':field_depth=max(0,field_depth-1)
                elif element.tag==W+'t' and not field_depth and id(element) not in dynamic_simple_text:
                    expected.append(element.text or '')
            def inventory(parts):
                return Counter(c for c in unicodedata.normalize('NFKC',''.join(parts))
                               if not c.isspace() and unicodedata.category(c)!='Cf')
            if inventory(expected)-inventory(rendered_chars):
                errors.append('docx_text_missing_from_rendered_pdf')
    except Exception as exc:
        errors.append('pdf_layout_check:' + type(exc).__name__)
    return {'docx_layout_status': 'passed' if not errors else 'failed',
            'docx_layout_errors': list(dict.fromkeys(errors)), 'docx_render_page_count': pages,
            'docx_render_text_check':'unicode_inventory_excluding_dynamic_fields'}


def finalize_export(metadata, contract, render_metadata):
    """Export success cannot erase a content failure (or the reverse)."""
    errors = list(contract.get('errors', []))
    if metadata.get('quality_warning'): errors.append(str(metadata['quality_warning']))
    if contract.get('status') != 'passed': errors.append('content_contract_not_passed')
    if contract.get('version') != VERSION:errors.append('content_contract_version_changed')
    if metadata.get('docx_integrity_status') != 'passed': errors.append('docx_integrity_not_passed')
    if render_metadata.get('docx_render_status') != 'passed': errors.append('docx_render_not_passed')
    if metadata.get('docx_layout_status') != 'passed': errors.append('docx_layout_not_passed')
    if contract.get('reading_format')=='analysis_with_annex':
        if metadata.get('evidence_annex_status')!='passed':errors.append('complete_evidence_annex_not_exported')
        if metadata.get('delivery_bundle_status')!='passed':errors.append('complete_delivery_bundle_not_exported')
    ready = not errors
    result = {**contract, 'export_status': 'passed' if ready else 'needs_repair',
              'delivery_ready': ready, 'errors': list(dict.fromkeys(errors))}
    return {'company_delivery_contract': result, 'delivery_status': 'final_candidate' if ready else 'review_draft',
            'requires_human_review': not ready,
            **({'quality_warning': '；'.join(result['errors'])} if errors else {})}
