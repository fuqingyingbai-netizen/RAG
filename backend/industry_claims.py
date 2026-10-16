"""Deterministic delivery checks. Passing these checks is not semantic proof."""
import re
from urllib.parse import urlsplit


def public_source_type(url):
    """Authority follows the actual host, never a regulator word in a title."""
    try:
        host = (urlsplit(str(url or '')).hostname or '').lower().rstrip('.')
    except ValueError:
        return 'web_search'
    def domain(value):
        return host == value or host.endswith('.' + value)
    if any(domain(x) for x in ('qcc.com', 'tianyancha.com', 'aiqicha.baidu.com', 'qixin.com')):
        return 'business_database'
    if any(domain(x) for x in ('cninfo.com.cn', 'sse.com.cn', 'szse.cn', 'hkexnews.hk', 'sec.gov')):
        return 'filing'
    if any(domain(x) for x in ('court.gov.cn', 'courts.gov.cn')):
        return 'court'
    if any(domain(x) for x in ('csrc.gov.cn', 'pbc.gov.cn', 'nfra.gov.cn', 'samr.gov.cn', 'creditchina.gov.cn')):
        return 'regulatory'
    if any(domain(x) for x in ('gov.cn', 'gov', 'gov.uk', 'gov.au', 'go.jp', 'europa.eu')):
        return 'government'
    return 'web_search'


def claim_contract_issues(text, facts):
    from industry_research import EVIDENCE_ID_PATTERN, numeric_mentions, numeric_supported
    issues = []
    by_id = {f['evidence_id']: f for f in facts if f.get('evidence_id')}
    for line in text.splitlines():
        ids = set(re.findall(EVIDENCE_ID_PATTERN, line, re.I))
        rows = [f for eid, f in by_id.items() if eid in ids]
        numeric = {f['evidence_id']: {'context': f.get('numeric_context') or {},
                   'validation': f.get('numeric_validation') or {}} for f in rows}
        def add(code, message):
            issues.append({'code': code, 'message': message, 'evidence_ids': sorted(ids)})
        assertion = re.search(r'已验证|已核验|证据充分|高确定性', line)
        negated = assertion and re.search(r'未|无|不|尚待|待', line[max(0, assertion.start()-5):assertion.start()])
        if assertion and not negated:
            numbers = numeric_mentions(line)
            if (not rows or '待核验' in line or (numbers and any(
                    not any(numeric_supported(n, eid, numeric) for eid in numeric) for n in numbers))):
                add('evidence_status_conflict', '已验证、证据充分或高确定性声明与该行待核验状态或授权数值不一致。')
        if re.search(r'(?:供给端|行业|市场|竞争格局).{0,12}(?:高度碎片化|高度分散|集中度(?:较|很|极)低)', line):
            if not re.search(r'不能|不代表|不足以|是否|假设', line):
                concentration = [f for f in rows if f.get('eligible_for_risk_scoring') is not False
                    and f.get('evidence_scope') in {'industry_level', 'segment_level'}
                    and (f.get('numeric_validation') or {}).get('passed') is True
                    and re.search(r'集中度|CR[235]|HHI|市场份额|市占率', str((f.get('numeric_context') or {}).get('metric', '')), re.I)]
                if not concentration:
                    add('concentration_inference_unsupported', '企业数量不能证明行业集中度或高度碎片化，需适用的份额或集中度指标。')
        if re.search(r'高于|低于|超过.*均值', line) and re.search(r'增速|增长|同比', line) and not re.search(r'不可比|不能比较|假设', line):
            rates = [n for n in numeric_mentions(line) if '%' in n or '％' in n]
            cards = [f for f in rows if any(numeric_supported(n, f['evidence_id'], numeric) for n in rates)]
            periods = {str((f.get('numeric_context') or {}).get('period') or '') for f in cards}
            if len(rates) >= 2 and (len(periods) > 1 or any(not any(numeric_supported(n, eid, numeric) for eid in numeric) for n in rates)):
                add('growth_comparison_unsupported', '增速比较缺少同期间的已校验指标，不能借用原文中的其他数字。')
        if re.search(r'政策原文|法规原文', line) and rows and all(public_source_type(f.get('source_url')) not in {'government', 'regulatory'} for f in rows):
            if not re.search(r'非|不是|不等于|待核验|需核对', line):
                add('policy_primary_source_missing', '政策原文声明只引用了解读或其他非官方网页，需回到发布机关原文。')
        if re.search(r'AI\s*Act|人工智能法案', line, re.I) and re.search(r'高风险.{0,70}7\s*[%％]', line):
            if not re.search(r'禁止|第\s*5\s*条|不能|不等于', line):
                add('policy_penalty_scope_conflict', '7%罚款档不能泛化为高风险系统的一般违规，需核对适用违法类型和原始条款。')
        if re.search(r'口径(?:混乱|不一致)|统计不可比', line) and re.search(r'增长可持续性存疑|需求不振|经营风险高', line):
            if not re.search(r'不代表|不能|不足以', line):
                add('evidence_gap_as_business_risk', '统计口径缺口不能直接证明实际增长、需求或经营风险恶化。')
    # Reviewed against CAC 2025-03-14 release and European Commission's
    # enforcement-ai-act page. These are narrow known-error checks, not a
    # complete legal interpretation or a substitute for dated primary text.
    if re.search(r'人工智能生成合成内容标识|GB\s*45438', text) and re.search(r'2025\s*年\s*3\s*月(?:份)?(?:起|开始|即)?(?:施行|实施|生效)', text):
        issues.append({'code': 'policy_effective_date_conflict', 'message': '标识办法及配套强制标准于2025年9月1日起施行，不能将3月发布日期当成施行日期。'})
    return issues


def industry_gap_plan(item):
    if re.search(r'政策|监管|标准|专利|知识产权|准入', item):
        return ('现有记录不足以核对原始文件及适用范围。', '核对发布机关或专利主管部门原文，分别记录发布、生效日期和统计定义。', '高', '正式文件编号、原始链接、适用地域与时间；专利统计方法。')
    if re.search(r'技术|路线|性能|成本|推理|算力', item):
        return ('现有资料未形成同条件的技术比较。', '核对原始测试报告、配置、负载和测试方法；必要时访谈技术负责人。', '高', '测试环境、版本、性能与单位成本表、方法说明。')
    if re.search(r'规模|增长|增速|口径|统计|集中度|份额|CR[235]|HHI', item, re.I):
        return ('统计期间、地域、定义或分母仍需对应原始资料核对。', '核对统计机构原报告和数据表，分别记录实际值与预测值；转载按原始来源去重。', '高', '原始统计表、期间、地域、行业定义、样本和分母。')
    return ('本轮证据尚不足以形成该项判断。', '先核对公开原始披露；仍缺证时经确认补充客户资料或访谈。', '中', '对应原始披露、待确认问题及可联系的核验对象。')
