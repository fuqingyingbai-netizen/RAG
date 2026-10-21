"""Question-directed selection of retained source statements, never verification.

Coverage describes available material, not a personality/credit assessment. A
template heading need not occur literally in a source for that source to help.
"""
import re
import unicodedata
from collections import Counter
from urllib.parse import urlparse
try:
    from .person_text import folded
except ImportError:
    from person_text import folded


SPECS = {
    2: [('教育与早年经历', r'毕业|学历|学位|大学|就读|学士|硕士|博士|education|university|degree'),
        ('职业时间线与职责', r'任职|任期|担任|创办|创立|历任|聘任|appointed|career|joined'),
        ('履历断点与矛盾', r'任职|任期|担任|创办|创立|历任|聘任|appointed|career|joined'),
        ('家庭健康等公开信息边界', r'(?!)')],
    3: [('责任心与事业心', r'负责|(?<!有限)责任(?!公司)|创业|辞职|放弃|承担|responsib'),
        ('诚信与利益取舍', r'诚信|利益|承诺|违约|契约|integrity|contract'),
        ('表达与风险偏好', r'表示|指出|演讲|采访|公开表达|认为|said|interview'),
        ('压力下行为与评价者立场', r'压力|困难|危机|回忆|评价|争议|conflict|pressure')],
    4: [('战略设计与行业判断', r'战略|策略|转型|布局|strategy'),
        ('执行与项目结果', r'交付|投产|量产|项目|产品|发布|研发|execution|product'),
        ('资本资源与个人职责', r'融资|筹资|资本|资产支持证券|financing|capital'),
        ('创新迭代与阶段匹配', r'研发|技术|专利|迭代|创新|innovation|technology')],
    5: [('权责与授权', r'授权|签字权|提名|聘任|任免|分工|委派|批准|delegat|appoint'),
        ('用人与关键岗位', r'人事|提名|聘任|任免|离任|离职|接班|选聘|继任|recruit|succession'),
        ('文化与冲突处理', r'文化|冲突|裁员|激励|薪酬|员工|争议|culture|conflict'),
        ('经营管控与稳定性', r'管控|内控|管理|授权|审批|审议|董事会|control|management')],
    6: [('成员履历与职责', r'任职|任期|担任|历任|董事|高管|总裁|履历|团队|executive|director|team'),
        ('产业资源与合作基础', r'曾在|历任|创办|共同|合作|工作|joined|career'),
        ('关键人员变动', r'离任|离职|变动|聘任|任免|接班|继任|辞职|resign|appoint'),
        ('团队治理与关系边界', r'兄长|亲属|共同|董事|管理|团队|关系|高管|team|board')],
    9: [('任职持股及控制关系', r'任职|任期|担任|法定代表|持股|股权|股东|控股|控制人|角色|职位|shareholder|ownership'),
        ('关联交易与利益一致性', r'关联交易|代持|利益冲突|同业竞争|关联方|related party'),
        ('司法事项及当事人身份', r'案号|诉讼|裁判|被执行|处罚|当事人|失信|lawsuit|litigation'),
        ('关系时间与透明度缺口', r'任职|任期|担任|持股|股权|股东|历史|角色|职位|ownership')],
    11: [('人物实际决策角色', r'授权|签字权|决策|控股|控制人|表决权|董事长|delegat|control'),
         ('投资方沟通与重大事项', r'投资方|重大事项|股东大会|资产支持证券|审议|批准|审批|investor|approval'),
         ('关键岗位与制度承接', r'聘任|任免|继任|接班|董事会秘书|总裁|总经理|succession|appoint'),
         ('退出路径及适用条件', r'锁定|不转让|限售|回购|退出|上市|exit|buyback|lock.up')],
    12: [('已发现的直接信号', r'风险|诉讼|处罚|失信|被执行|争议|risk|lawsuit|penalty'),
         ('关联主体间接信号', r'风险|诉讼|处罚|失信|被执行|争议|risk|lawsuit|penalty'),
         ('尚未核验及未查询事项', r'(?!)'), ('风险核查覆盖清单', r'(?!)')],
}


def normalized(text):
    return folded(str(text or ''))


def is_lockup(text):
    return bool(re.search(r'锁定|限售|每年转让|不转让|不得转让|股票上市之日', text))


def judicial_party_material(fact):
    """A lawsuit keyword next to a founder's name is not a party record."""
    text = folded(fact.get('fact', ''))
    if fact.get('claim_type') == 'person_platform_record':
        return bool(re.search(r'案号|案件编号|执行案号|决定书文号|执行法院|被执行人姓名|失信被执行人姓名', text))
    name = re.escape(folded(fact.get('subject') or ''))
    if not name:
        return False
    return bool(re.search(r'案号|案件编号|决定书文号|执行案号', text) or
                re.search(name + r'[^。；;\n]{0,35}(?:作为|系|为|被列为).{0,12}(?:原告|被告|被执行人|当事人|申请人|上诉人)', text) or
                re.search(name + r'[^。；;\n]{0,25}(?:被.{0,12}起诉|提起.{0,12}诉讼|涉及.{0,12}诉讼|受到.{0,12}处罚|被.{0,8}执行|被.{0,8}处罚)', text))


def prospective_company_risk(fact):
    text = folded(fact.get('fact', ''))
    return bool(re.search(r'控股股东.{0,15}控制风险|实际控制人控制风险|管理风险', text) and
                re.search(r'本公司|本集团|招股|公司', text))


def material_matches(fact, chapter, view):
    text = folded(str(fact.get('fact') or ''))
    scope = fact.get('subject_scope')
    if chapter == 5 and is_lockup(text):
        return False
    if chapter == 5 and re.search(r'管理风险|控股股东.{0,15}控制风险', text) and not re.search(r'授权|聘任|提名|任免|审批', text):
        return False
    if chapter == 5 and re.search(r'丰富.{0,10}管理经验|充足时间和精力|资格|不得担任', text) and not re.search(r'授权|聘任|提名|任免|审批', text):
        return False
    if chapter == 6:
        # A news item mentioning an external CEO is not a management-team bio.
        team = (scope == 'other_person' and (bool(fact.get('team_member_name') and fact.get('team_affiliation_name')) or bool(re.search(r'本公司|本集团|其团队|管理团队|核心团队|共同创办|共同创立|团队成员|同属', text)))) or (scope == 'affiliated_company' and 6 in fact.get('person_chapters', []))
        if not team:
            return False
        if fact.get('team_role_literal') and view == '成员履历与职责':
            return True
        if '不得担任' in text and not re.search(r'现任|担任本|任职|共同创办', text):
            return False
    if chapter == 4 and re.search(r'控股股东.{0,15}控制风险|管理风险|重大经营及人事决策', text):
        return False
    if chapter == 4 and re.search(r'成功.{0,25}努力|创新精神|丰富.{0,10}管理经验|行业资源', text) and not re.search(r'负责|主导|研发|项目|创办|投资|交付', text):
        return False
    if chapter == 9 and view == '司法事项及当事人身份':
        return judicial_party_material(fact)
    if chapter == 9 and fact.get('literal_roster_row') and view in {'任职持股及控制关系', '关系时间与透明度缺口'}:
        return True
    if chapter == 12:
        # A comparison about another enterprise's risk appetite is not a
        # negative event involving the target, even if it contains "风险".
        if (re.search(r'回避风险|风险偏好|风险承担|敢于冒险', text)
                and not judicial_party_material(fact)
                and not re.search(r'被调查|受.{0,8}处罚|违约|舞弊|贪腐|失信记录|重大亏损|管理风险|控制风险', text)):
            return False
        prospective = prospective_company_risk(fact)
        if view == '已发现的直接信号':
            if scope != 'person' or prospective:
                return False
            if re.search(r'诉讼|裁判|对簿公堂', text) and not judicial_party_material(fact):
                return False
        if view == '关联主体间接信号' and scope != 'affiliated_company' and not prospective:
            return False
    pattern = dict(SPECS.get(chapter, [])).get(view)
    return bool(pattern and re.search(pattern, text, re.I))


def useful_for_chapter(fact, chapter):
    text = fact.get('fact', '')
    if chapter == 3 and re.search(r'(?:儿子|女儿|孩子).{0,25}(?:优点|善良|聪明)|(?:评价|谈到).{0,12}(?:儿子|女儿)', folded(text)):
        return False
    if (all(word in folded(text) for word in ('真实','准确','完整')) and '法律责任' in text
            and not re.search(r'案号|判决|处罚|执行法院|授权|聘任|任免',text)):
        return False
    if fact.get('source_text_issue') == 'possible_revision_overlap':
        return False
    from company_ocr import native_text_issue
    if native_text_issue(text) in {'mixed_script_character_map', 'broken_character_map'}:
        return False
    # Date/title feeds are discovery leads, not the body of any one article.
    if len(re.findall(r'(?:19|20)\d{2}-\d{2}-\d{2}', text)) >= 3 and not re.search(r'[。！？]', text):
        return False
    if len(text) < 260 and len(re.findall(r'(?:19|20)\d{2}-\d{2}-\d{2}', text)) >= 2 and '。' not in text:
        return False
    if (len(text) < 300 and re.search(r'详细简历.{0,20}请参见|简历具体情况请参见|具体情况请参见|具体内容请参见|相关简历请参见|^人物\s+冲突积怨|^.*?欢迎访问.*?官网[！!]$', text)):
        return False
    return chapter not in SPECS or any(material_matches(fact, chapter, view) for view, _ in SPECS[chapter])


def question_priority(fact, chapter, view):
    text = folded(fact['fact'])
    if chapter == 2 and view == '教育与早年经历':
        return 3 * bool(re.search(r'毕业|就读|学位|graduat|degree', text, re.I)) + bool(fact.get('observation', {}).get('source_events'))
    if chapter in {5, 11}:
        return (6 * (fact.get('claim_type') == 'person_management_event')
                + 4 * bool(re.search(r'授权|委派|delegat', text, re.I))
                + 2 * bool(re.search(r'重大事项|资产支持证券|聘任|任免', text)))
    if chapter == 9:
        return 2 * bool(fact.get('observation', {}).get('role_date_fields') or fact.get('observation', {}).get('metrics'))
    return 0


def quality_key(fact):
    grade = {'A': 4, 'B': 3, 'C': 2, 'D': 1}.get(str(fact.get('source_grade') or '').upper(), 0)
    original = bool(fact.get('original_excerpt_match'))
    clean = not bool(re.search(r'更多>>|点击浏览|欢迎访问|在线留言|当前位置|上一篇|下一篇', fact.get('fact', '')))
    return (grade, original, clean, -len(fact.get('fact', '')))


def prioritize_sentences(sentences, matches_name):
    """Reserve distinct research questions across a complete retained source.

    Ordering affects a bounded fact-card extractor, never source retention.
    Later education, appointment or authorization events must not lose every
    slot to repeated early mentions of the same name in a long annual report.
    """
    rows, seen = [], set()
    for text in sentences:
        text = re.sub(r'\s+', ' ', text).strip(' -•\t')
        key = normalized(text)
        if key in seen or not 24 <= len(text) <= 1200 or not matches_name(text):
            continue
        seen.add(key)
        rows.append(text)
    reserved = []
    for chapter in (2, 5, 9, 11, 12, 3, 4):
        for _, pattern in SPECS[chapter]:
            candidates = [t for t in rows if re.search(pattern, t, re.I) and t not in reserved]
            if candidates:
                selected = max(candidates, key=lambda t: (bool(re.search(r'授权|聘任|毕业|案号|决定书|任职日期', t)),
                    bool(re.search(r'(?:19|20)\d{2}', unicodedata.normalize('NFKC', t))), -len(t)))
                reserved.append(selected)
    return reserved + [t for t in rows if t not in reserved]


def select_material(ranked, chapter, commissioned=(), commission_matches=None, limit=12):
    """Build relevant material; an optional limit governs presentation only.

    ``limit=None`` retains every distinct eligible statement for research.
    Source/domain/peer/member quotas must never truncate that research pool.
    """
    eligible, audit, families = [], [], {}
    for score, fact in ranked:
        if not useful_for_chapter(fact, chapter):
            audit.append({'evidence_id': fact['evidence_id'], 'status': 'not_selected', 'reason': fact.get('source_text_issue') or 'not_chapter_material'})
            continue
        family = (normalized(fact['fact']), fact.get('subject_scope'), fact.get('comparison_subject', ''), fact.get('team_member_name', ''))
        previous = families.get(family)
        if previous is not None:
            winner, duplicate = (fact, previous[1]) if quality_key(fact) > quality_key(previous[1]) else (previous[1], fact)
            if winner is fact:
                eligible.remove(previous)
                item = (score, fact)
                eligible.append(item)
                families[family] = item
            audit.append({'evidence_id': duplicate['evidence_id'], 'status': 'not_selected', 'reason': 'same_source_statement', 'same_statement_as': winner['evidence_id']})
            continue
        item = (score, fact)
        families[family] = item
        eligible.append(item)
    # Material quality precedes accidental hash ordering among equal topics.
    eligible.sort(key=lambda pair: (not bool(pair[1].get('team_member_name')) if chapter == 6 else False,
                                    not bool(pair[1].get('biography_excerpt')) if chapter == 8 else False,
                                    not bool(pair[1].get('primary_disclosure')) if chapter == 8 else False,
                                    not bool(pair[1].get('individual_peer_page')) if chapter == 8 else False,
                                    tuple(-x for x in quality_key(pair[1])), -pair[0], pair[1]['evidence_id']))
    reserved = []
    if chapter in SPECS:
        for view, _ in SPECS[chapter]:
            candidates = [r for r in eligible if material_matches(r[1], chapter, view) and r not in reserved]
            candidate = max(candidates, key=lambda r: (question_priority(r[1], chapter, view), quality_key(r[1]), r[0])) if candidates else None
            if candidate:
                reserved.append(candidate)
    if chapter == 6:
        named = []
        seen_names = set()
        for candidate in eligible:
            name = normalized(candidate[1].get('team_member_name') or candidate[1].get('subject'))
            if name and name not in seen_names:
                seen_names.add(name)
                named.append(candidate)
        reserved = named + [r for r in reserved if r not in named]
    if chapter == 10 and commission_matches:
        for requirement in commissioned:
            candidate = next((r for r in eligible if commission_matches(r[1], requirement) and r not in reserved), None)
            if candidate:
                reserved.append(candidate)
    if chapter == 8:
        names = sorted({r[1].get('comparison_subject') for r in eligible if r[1].get('comparison_subject')})
        for name in names:
            for kind in ('profile', 'nomination_basis'):
                candidate = next((r for r in eligible if r[1].get('comparison_subject') == name and r[1].get('comparison_record_kind') == kind and r not in reserved), None)
                if candidate:
                    reserved.append(candidate)
    if chapter in {9, 10}:
        # A biography or lockup cannot answer a dated appointment query.
        # Reserve distinct record questions, not a quota per provider or URL.
        topics = {r['topic'] for r in commissioned} if chapter == 10 else {'career', 'ownership'}
        questions = ([('appointment', False), ('appointment', True)] if 'career' in topics else [])
        questions += [('holding', None)] if 'ownership' in topics else []
        for relation, historical in questions:
            candidates = []
            for pair in eligible:
                f, obs = pair[1], pair[1].get('observation') or {}
                if (f.get('claim_type') != 'person_platform_record' or f.get('subject_scope') != 'person'
                        or not obs.get('direct_person_link') or not obs.get('issuer')
                        or relation not in obs.get('relations', [])):
                    continue
                old = bool(re.search(r'；历史记录；|曾担任角色|结束时间:\s*(?:19|20)\d{2}', f['fact']))
                if historical is not None and (old != historical or not obs.get('role_date_fields')):
                    continue
                if relation == 'holding' and not obs.get('metrics'):
                    continue
                candidates.append(pair)
            if candidates:
                def record_key(pair):
                    f, obs = pair[1], pair[1].get('observation') or {}
                    seed = re.search(r'查询定位机构：([^；]+)', f['fact'])
                    dates = [d for row in obs.get('role_date_fields', []) for d in re.findall(r'(?:19|20)\d{2}-\d{2}-\d{2}', row['source_value'])]
                    return (bool(seed and normalized(seed[1]) == normalized(obs['issuer'])),
                            max(dates, default=''), quality_key(f), pair[0], f['evidence_id'])
                candidate = max(candidates, key=record_key)
                if candidate not in reserved:
                    reserved.append(candidate)
    ordered = reserved + [r for r in eligible if r not in reserved]
    if limit is None:
        for _, fact in ordered:
            audit.append({'evidence_id': fact['evidence_id'], 'status': 'selected', 'reason': 'complete_research_material'})
        return [fact for _, fact in ordered], audit
    selected, sources, domains, members, peer_counts = [], Counter(), Counter(), Counter(), Counter()
    peer_names = {f.get('comparison_subject') for _, f in eligible if f.get('comparison_subject')}
    peer_cap = max(2, (limit + len(peer_names) - 1) // len(peer_names)) if peer_names else limit
    for _, fact in ordered:
        url = fact['source_url']
        domain = urlparse(url).netloc or url
        member = normalized(fact.get('team_member_name') or fact.get('subject')) if chapter == 6 else ''
        reason = ('chapter_capacity' if len(selected) >= limit else 'same_member_profile' if member and members[member] else
                  'peer_concentration' if chapter == 8 and fact.get('comparison_subject') and peer_counts[fact['comparison_subject']] >= peer_cap else
                  'source_concentration' if sources[url] >= 3 and (_, fact) not in reserved else
                  'domain_concentration' if domains[domain] >= 4 and (_, fact) not in reserved else '')
        if reason:
            audit.append({'evidence_id': fact['evidence_id'], 'status': 'not_selected', 'reason': reason})
            continue
        selected.append(fact)
        sources[url] += 1
        domains[domain] += 1
        if member:
            members[member] += 1
        if fact.get('comparison_subject'):
            peer_counts[fact['comparison_subject']] += 1
        audit.append({'evidence_id': fact['evidence_id'], 'status': 'selected', 'reason': 'question_material'})
    return selected, audit


def management_event(text, forms, orgs):
    from person_evidence import name_in_text
    if not 40 <= len(text) <= 1200 or not any(name_in_text(n, text) for n in forms if n):
        return False
    if not any(normalized(org) in normalized(text) for org in orgs if len(org) >= 3):
        return False
    # A comparison mentioning a namesake at another employer needs its own
    # attribution. Page-level identity cannot establish this paragraph's actor.
    if re.search(r'比如|例如|相比|相较|such as|compared', text, re.I):
        return False
    if re.search(r'善良|性格|人格|感性|柔软|脾气|人品', text):
        return False
    return bool(re.search(r'裁撤|裁员|组织变革|制度创新|授权|签字权|任免|聘任|接班|继任|重组|计件工资|激励|分配|任期|restructur|appoint|delegat|succession', text, re.I))


def retained_management_events(sources, intake):
    """Recover exact locally anchored events from feedback-discovery originals.

    Collection purpose is not a ban on other research questions. These typed
    records route only to management/event chapters, never personal credit.
    """
    target = str(intake.get('target_name') or '')
    anchor = intake.get('person_anchor') or {}
    forms = [target, *anchor.get('aliases', [])]
    orgs = [re.sub(r'(?:股份有限公司|有限责任公司|有限公司)$', '', str(v))
            for v in anchor.get('known_affiliations', []) if len(str(v)) >= 3]
    rows = []
    for source in sources:
        meta, body = source.source_metadata or {}, source.content or ''
        if (not meta.get('person_feedback_only') or meta.get('identity_confidence') not in {'high', 'medium'}
                or meta.get('identity_status') == 'quarantined' or meta.get('person_discovery_only')
                or meta.get('content_kind') in {'summary_only', 'low_content', 'empty_content'}
                or meta.get('fetch_status') in {'failed', 'blocked', 'empty', 'skipped', 'challenge'}):
            continue
        paragraphs = list(re.finditer(r'\S[\s\S]*?(?=\n\s*\n|\Z)', body))
        for index, paragraph in enumerate(paragraphs):
            quote = paragraph[0].strip()
            if not management_event(quote, forms, orgs):
                continue
            # Keep an immediately adjacent response/result paragraph. A bounded
            # event card must not say feedback is absent when the next original
            # paragraph reports dissent or a different decision-maker's action.
            if index+1 < len(paragraphs) and re.search(r'裁撤|裁员|计件工资|重组|任免|restructur', quote, re.I):
                following = paragraphs[index+1]
                context = following[0].strip()
                if (len(quote)+len(context) <= 1800 and any(normalized(org) in normalized(context) for org in orgs)
                        and re.search(r'不满|不接受|辞职|开除|反馈|反对|执行|结果|反应|resign|oppos|reaction', context, re.I)):
                    quote = body[paragraph.start():following.end()].strip()
            rows.append({'fact': quote, 'evidence_quote': quote, 'source_url': source.url, 'source_title': source.title,
                'claim_type': 'person_management_event', 'person_chapters': [4, 5, 11],
                'identity_match': 'confirmed', 'identity_confidence': meta['identity_confidence'],
                'source_grade': meta.get('source_grade') or 'C',
                'event_identity_context': {'known_affiliations': orgs},
                'provider': meta.get('provider'), 'retrieved_at': meta.get('retrieved_at', ''),
                'extraction_method': 'retained_local_management_event'})
    return rows


def dimension_coverage(chapter, facts, queries=()):
    rows = []
    for view, _ in SPECS.get(chapter, []):
        matches = [f for f in facts if material_matches(f, chapter, view)]
        state = 'partial' if matches else 'missing'
        if chapter == 2 and view == '家庭健康等公开信息边界':
            state, status = 'scope_limited', '仅使用与委托有关且明确公开的信息；未披露不作为风险，不扩张检索私密信息。'
        elif chapter == 12 and view in {'尚未核验及未查询事项', '风险核查覆盖清单'}:
            state = 'query_recorded' if queries else 'missing'
            status = (f'已记录{len(queries)}项专业查询状态，逐项区分返回记录、空结果、失败及未查询；不作为无风险证明。' if queries else '尚缺可核对的专业查询覆盖记录，不能推定已经查全或无风险。')
        elif matches:
            if chapter == 2 and view == '教育与早年经历':
                status = '已取得教育经历线索；学校、专业、毕业时间及原始出处仍须核对。'
            elif chapter == 2 and view == '履历断点与矛盾':
                status = '已有履历记录；连续性、任期衔接和疑似冲突须逐时点核实。'
            elif chapter == 3:
                status = '已取得本人行为或公开表达线索；尚不足以据此判定人格、诚信或风险偏好。'
            elif chapter == 4:
                status = '已取得职责、事件或结果线索；个人贡献、对应时期及因果关系仍待核实。'
            elif chapter == 6:
                status = '已取得团队其他成员或团队结构资料；实际职务、任期及关系仍需核对，不归因目标本人。'
            elif chapter == 11 and view == '退出路径及适用条件':
                status = '已取得锁定、转让或退出相关原词；须核对历史时期、现行协议及触发条件，不推定当前退出权。'
            elif chapter == 12:
                status = ('已取得公司披露的潜在治理或控制风险因素；不代表风险已经发生，也不认定个人违法或失信。'
                          if view == '关联主体间接信号' and all(prospective_company_risk(f) for f in matches) else
                          '已取得对应归属的来源信号；事项性质、个人责任和处理结果仍需核实。')
            else:
                status = '已取得对应问题的原文线索；主体、时期、适用条件与结论仍待逐项核实。'
        else:
            status = '当前入选材料尚不能回答该问题，需核查留存原文或有针对性补证。'
        rows.append({'view': view, 'state': state, 'status': status,
                     'evidence_ids': [f['evidence_id'] for f in matches],
                     'completion': 'available_source_material_is_not_verified_conclusion'})
    return rows


def document_issuer(source):
    """Use a retained cover's explicit company name, never a product logo."""
    meta = source.source_metadata or {}
    pages = meta.get('document_pages') or []
    cover = next((p for p in pages if p.get('page') == 1), {})
    text = str(cover.get('ocr_text') or cover.get('text') or '')
    # A cover can be absent while body starts at a contents page. Do not
    # manufacture an issuer from whichever company occurs most often.
    for line in text.splitlines()[:25]:
        match = re.search(r'([\u4e00-\u9fff]{2,35}(?:股份|控股)?有限公司)', folded(line))
        if match:
            return match[1]
    return ''


def team_source_facts(sources, intake, audit=None):
    """Recover exact colleague bios missed by target-name-only extraction.

    Only retained full documents with the supplied company anchor, target name
    and an explicit management-bio heading are eligible. This is not a search
    or a statement that the appointments remain current.
    """
    target = str(intake.get('target_name') or intake.get('company_name') or '')
    anchor = intake.get('person_anchor') or {}
    orgs = [str(org) for org in anchor.get('known_affiliations', []) if len(str(org)) >= 3]
    forms = {normalized(n) for n in [target, *anchor.get('aliases', [])] if n}
    if not target or not orgs:
        return []
    rows = []
    for source in sources:
        meta, body = source.source_metadata or {}, source.content or ''
        if (meta.get('identity_confidence') not in {'high', 'medium'} or meta.get('person_discovery_only')
                or meta.get('identity_status') == 'quarantined' or meta.get('content_kind') in {'summary_only', 'low_content', 'empty_content'}
                or meta.get('fetch_status') in {'failed', 'blocked', 'empty', 'skipped', 'challenge'}):
            continue
        compact_body = normalized(body)
        org = next((org for org in orgs if normalized(org) in compact_body), '')
        if not org or normalized(target) not in compact_body or not re.search(r'高级管理人员简历|董事.*?高级管理人员|管理层简历|directors and senior management|executive biographies', body, re.I):
            continue
        issuer = document_issuer(source)
        if issuer and not any(normalized(org) in normalized(issuer) for org in orgs):
            if audit is not None:
                audit.append({'source_url': source.url, 'status': 'not_main_company_team_material',
                    'reason': 'document_issuer_differs_from_target_affiliation', 'document_issuer': issuer,
                    'requested_affiliations': orgs, 'boundary': 'retained_for_other_questions_not_deleted_from_source_corpus'})
            continue
        headings = list(re.finditer(r'(?m)^\s*(?:([\u4e00-\u9fff]{2,4})(?:先生|女士)[，,]|(?:Mr\.?|Ms\.?)\s+([A-Z][A-Za-z\'-]+(?:\s+[A-Z][A-Za-z\'-]+){1,4})\s*[,，])', body))
        document_count = 0
        for index, heading in enumerate(headings):
            name = heading[1] or heading[2]
            prefix = body[:heading.start()].rstrip()
            if heading[1] and prefix and re.fullmatch(r'[\u4e00-\u9fff]', prefix.rsplit('\n', 1)[-1].strip()):
                # A preceding isolated surname indicates a wrapped name; keep
                # that ambiguous record out rather than invent a short name.
                continue
            if normalized(name) in forms:
                continue
            end = headings[index+1].start() if index+1 < len(headings) else len(body)
            excerpt = body[heading.start():end].strip()
            remainder = body[heading.end():end].lstrip()
            if re.match(r'以及|及|、|和|and\b', remainder, re.I) or not re.search(r'出生|国籍|学历|毕业|加入|现任|历任|担任|born|graduat|director|chief|officer|president', remainder[:140], re.I):
                continue
            # Finish at an actual sentence boundary, not a fabricated summary.
            if len(excerpt) > 1800:
                last = max(excerpt.rfind('。', 0, 1800), excerpt.rfind('. ', 0, 1800))
                if last < 120:
                    continue
                excerpt = excerpt[:last+1]
            employer = r'(?:本公司|本集团|thecompany|thegroup|' + re.escape(normalized(org)) + r')'
            role = r'(?:副总裁|董事|总裁|总经理|财务总监|首席|秘书|director|chief|officer|president)'
            if len(excerpt) < 60 or not re.search(employer + r'.{0,50}' + role + '|' + role + r'.{0,20}' + employer, normalized(excerpt), re.I):
                continue
            rows.append({'fact': excerpt, 'evidence_quote': excerpt, 'source_url': source.url, 'source_title': source.title,
                         'identity_match': 'confirmed', 'identity_confidence': meta['identity_confidence'],
                         'claim_type': 'person_team_member_record', 'person_chapters': [6],
                         'team_member_name': name, 'team_affiliation_name': org,
                         'provider': meta.get('provider'), 'source_grade': meta.get('source_grade', ''),
                         'retrieved_at': meta.get('retrieved_at', ''), 'published_at': meta.get('published_at', '')})
            document_count += 1
        if audit is not None:
            audit.append({'source_url': source.url, 'status': 'retained_team_candidates',
                'document_issuer': issuer, 'candidate_count': document_count})
    return rows
