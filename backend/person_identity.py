"""Keep intake clues separate from independently sourced identity evidence."""
import re

VERSION = 'person-identity-v6-article-and-actor-context'
ROLES = r'联合创始人|创始人|董事长|副董事长|总经理|副总经理|执行董事|董事|监事|合伙人|法定代表人|研究员|教授|工程师|员工|高管|CEO|CFO|CTO|COO|President|Founder|Partner|Chairman'
SCHOOL = re.compile(r'大学|学院|University|College|School', re.I)


def discovery_index(title, content=''):
    """A namesake news index cannot confer one identity on all its items."""
    title = str(title or '')
    intro = str(content or '')[:700]
    strong_title = re.search(r'最新新闻报道|最新新聞報道|新闻聚合|搜索结果|search results',title,re.I)
    listing_intro = re.search(r'为您提供.{0,35}(?:最新新闻报道|相关消息)|為您提供.{0,35}(?:最新新聞|相關消息)',intro)
    related_title = re.search(r'相关新闻|相關新聞|相关消息|相關消息',title)
    dated_items = len(re.findall(r'(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}',str(content or '')[:6000]))
    return bool(strong_title or listing_intro or related_title and dated_items>=3)


def relation_actor_is_target(text, relation_start, target):
    """Require a local actor link, rather than the name anywhere on the page."""
    try:
        from .person_text import folded
        from .person_records import observation
    except ImportError:
        from person_text import folded
        from person_records import observation
    before = text[:relation_start]
    start = max(before.rfind('。'),before.rfind('；'),before.rfind(';'),before.rfind('\n'))+1
    clause = text[start:relation_start+50]
    local = before[max(start,len(before)-180):]
    headings = list(re.finditer(r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})(?:先生|女士)[，,\s]',before))
    if headings and relation_start-headings[-1].start()<2000:
        if folded(headings[-1][1]) != folded(target):
            # A joint founder can be a co-actor, but a partner's subsequent
            # appointments cannot transfer to the target.
            return bool(folded(target) in folded(local) and re.search(r'(?:与|和)' + re.escape(target) + r'(?:先生|女士)?\s*(?:共同|联合)?$',local)
                        and re.match(r'共同创办|联合创办|创办|创立',text[relation_start:]))
        return True
    return folded(target) in folded(local) and observation({'fact':clause},target)['subject_scope'] == 'person'


def pieces(value):
    return [s.strip() for s in re.split(r'[/／|｜、,，;；\n]+', str(value or '')) if s.strip()]


def affiliations(value):
    """Legacy slash-separated companies also accept roles, schools and dates."""
    result = []
    for part in pieces(value):
        part = re.sub(r'^(?:机构|公司|任职机构|曾任机构|关联机构)\s*[:：]\s*', '', part)
        part = re.sub(r'^(?:现任|曾任|前任|原任|目前)\s*', '', part)
        part = re.sub(r'\b(?:19|20)\d{2}(?:\s*[-—至]\s*(?:(?:19|20)\d{2}|至今))?年?', '', part).strip()
        if SCHOOL.search(part) or re.match(r'^(?:学历|教育|毕业|地区|所在地|出生|年龄|职责|备注|身份)\s*[:：]', part):
            continue
        part = re.split(r'(?:担任|任职为|任职|职位[:：]|职务[:：])', part, maxsplit=1)[0]
        part = re.sub(r'(?:' + ROLES + r').*$', '', part, flags=re.I).strip(' ：:()（）-— ')
        part = re.sub(r'(?:等|相关公司)$', '', part).strip()
        if 2 <= len(part) <= 100 and not re.fullmatch(r'[\d\W]+', part) and part not in result:
            result.append(part)
    return result[:12]


def build_anchor(intake):
    target = str(intake.get('target_name') or '').strip()
    names = [target, *intake.get('person_aliases', [])]
    latin = re.sub(r'[^A-Za-z ]', '', target).strip()
    chinese = ''.join(re.findall(r'[\u4e00-\u9fff]', target))
    names.extend([latin, chinese])
    raw = str(intake.get('affiliation_raw', intake.get('affiliation')) or '')
    context = str(intake.get('person_context') or '')
    explicit = pieces(intake.get('identity_anchors'))
    # Only labeled companies from long supplementary prose become query subjects.
    labeled = re.findall(r'(?:任职机构|关联机构|公司|机构)\s*[:：]\s*([^\n；;，,]+)', context)
    orgs = list(intake.get('affiliations') or affiliations(raw))
    for org in affiliations('/'.join(labeled)) + affiliations(intake.get('associated_company')):
        if org not in orgs:
            orgs.append(org)
    clues = explicit[:]
    uploaded = list(intake.get('uploaded_identity_clues') or [])
    for row in uploaded:
        fields = row.get('fields') or {}
        for clue in pieces(fields.get('identity_anchors')):
            if clue not in clues:
                clues.append(clue)
        for org in affiliations(fields.get('affiliation')):
            if org not in orgs:
                orgs.append(org)
    for value in pieces(raw) + pieces(context):
        if SCHOOL.search(value) or re.match(r'^(?:学历|教育|毕业|资格|地区|所在地)\s*[:：]', value):
            value = re.sub(r'^[^:：]{2,8}[:：]\s*', '', value)
            if value not in clues:
                clues.append(value[:160])
    clues = [s for s in clues if len(s) >= 2 and not re.fullmatch(ROLES, s, re.I)]
    return {'target_person': target, 'aliases': list(dict.fromkeys(n.strip() for n in names if n.strip())),
            'known_affiliations': orgs[:12], 'identity_anchors': clues[:24],
            'roles': list(dict.fromkeys(re.findall(ROLES, raw + '\n' + context, re.I))),
            'raw_context': raw, 'supplementary_context': context,
            'focus_questions': list(intake.get('focus_questions') or []),
            'special_requirements': str(intake.get('special_requirements') or ''),
            'uploaded_identity_clues': list(intake.get('uploaded_identity_clues') or []),
            'provenance': 'user_supplied_clues_not_verified_facts',
            'anchor_status': 'user_seeded' if target else 'missing_target', 'version': VERSION}
