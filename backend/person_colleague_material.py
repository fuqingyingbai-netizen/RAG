"""Recover explicit company/name/role links from retained article originals."""
import re

try:
    from .person_text import folded
except ImportError:
    from person_text import folded


def explicit_colleague_roles(sources, intake, audit=None):
    target = str(intake.get('target_name') or '')
    anchor = intake.get('person_anchor') or {}
    orgs = [str(x) for x in anchor.get('known_affiliations', []) if len(str(x)) >= 3]
    forms = {folded(x) for x in [target, *anchor.get('aliases', [])] if x}
    result, seen = [], set()
    role = r'(?:首席执行官|首席运营官|首席财务官|执行董事|董事长|总经理|副总裁|总裁|ceo|coo|cfo)'
    stop = r'(?=[，,。；;：:“”"（(\s]|在|于|则|曾|已|将|也|还|后|并|对|均|都|分别|称|说|表示|指出|接受|接任|辞任|加入|接棒|负责|统筹|从|做|的|和|与|、|及|也是|$)'
    surname = '赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻窦章云苏潘葛范彭郎鲁韦马苗方俞任袁柳唐罗薛雷贺倪汤滕殷毕郝邬安常乐于傅卞齐康伍余元卜顾孟黄穆萧尹姚邵汪祁毛狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季贾路娄危江童颜郭梅盛林钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫房裘缪解应宗丁宣邓杭洪包诸左石崔龚程邢裴陆荣翁荀羊甄曲封芮储靳焦侯仲秋宫宁仇栾甘戎厉戎符刘景詹束龙叶黎耿满弘匡国文寇广禄阙东欧利师巩聂晁勾苟敖冷辛简饶曾毋沙养鞠丰巢关蒯相查后荆红游竺权盖益桓公仉司上官诸葛欧阳夏侯'
    name = '[' + surname + r'][\u4e00-\u9fff]{1,3}?'
    denied_names = {'任职', '表示', '已经', '正式', '团队', '公司', '集团', '管理', '方面', '前任', '共同', '相关', '服务', '战略'}
    for source in sources:
        meta = source.source_metadata or {}
        body = str(source.content or '')
        if (meta.get('identity_confidence') not in {'high', 'medium'} or meta.get('person_discovery_only')
                or meta.get('identity_status') == 'quarantined' or meta.get('fetch_status') in {'failed', 'blocked', 'empty', 'skipped', 'challenge'}):
            continue
        # Character offsets preserve exact paragraphs despite PDF spacing and
        # traditional/simplified Chinese differences used only for matching.
        characters, offsets = [], []
        for index, char in enumerate(body):
            normalized = folded(char)
            characters.extend(normalized)
            offsets.extend([index] * len(normalized))
        text = ''.join(characters)
        added = 0
        for org in orgs:
            literal_org = re.escape(folded(org))
            company_role_prefix = r'(?:国际控股|股份有限公司|控股有限公司|有限公司|集团|公司|前两任|前任|现任|原|前|执行|非|的|董事会|新任|副|高级){0,4}?'
            patterns = [literal_org + company_role_prefix + role + r'(?:[：:]|的)?(?P<name>' + name + ')' + stop,
                r'(?<![\u4e00-\u9fff])(?P<name>' + name + r')(?:先生|女士)?(?:担任|出任|接任|辞任|升任|获委任为)' + literal_org + company_role_prefix + role,
                literal_org + r'(?:[，,：:](?:' + name + r'[和与、及])?|(?:发布|发表|公告称|宣布)[^。；;]{0,100}?)'
                + r'(?P<name>' + name + r')(?:已|将|已经)?(?:辞任|担任|出任|接任|获委任为)(?:本公司|公司)?(?:执行董事及|执行董事、)?' + role]
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.I):
                    person = match['name']
                    if person in denied_names or person in forms:
                        continue
                    if re.search(r'接替|取代|替代|接棒', text[max(match.start(), match.start('name')-8):match.start('name')]):
                        continue
                    original_start, original_end = offsets[match.start()], offsets[match.end()-1]+1
                    start = body.rfind('\n\n', 0, original_start) + 2
                    if start == 1:
                        start = 0
                    end = body.find('\n\n', original_end)
                    end = len(body) if end < 0 else end
                    quote = body[start:end].strip()
                    if len(quote) > 1800:
                        left = max(body.rfind('。', start, original_start), body.rfind('\n', start, original_start))
                        right = body.find('。', original_end, end)
                        if right < 0:
                            continue
                        quote = body[left+1:right+1].strip()
                    if not 35 <= len(quote) <= 1800 or quote not in body:
                        continue
                    from company_ocr import native_text_issue
                    if native_text_issue(quote) in {'mixed_script_character_map', 'broken_character_map'}:
                        continue
                    # The complete role link is a literal substring. A date
                    # elsewhere in this paragraph is not that role's tenure.
                    names = [(person, match.start('name'), match.end('name'))]
                    before = text[match.start():match.start('name')]
                    parallel = re.search(r'(?<![\u4e00-\u9fff])(?P<name>' + name + r')[和与及、]$', before)
                    if parallel and re.match(r'(?:已|将|已经)?(?:担任|出任|接任|辞任)', text[match.end('name'):]):
                        names.append((parallel['name'], match.start()+parallel.start('name'), match.start()+parallel.end('name')))
                    if re.search(r'两任|历任|多位|几位', before):
                        following = re.match(r'[和与及、](?P<name>' + name + ')' + stop, text[match.end('name'):])
                        if following:
                            names.append((following['name'], match.end('name')+following.start('name'), match.end('name')+following.end('name')))
                            original_end = offsets[match.end('name')+following.end()-1]+1
                    relation = body[original_start:original_end]
                    for colleague, name_start, name_end in names:
                        if colleague in forms or colleague in denied_names:
                            continue
                        key = source.url, colleague, folded(quote)
                        if key in seen:
                            continue
                        seen.add(key)
                        literal_name = body[offsets[name_start]:offsets[name_end-1]+1]
                        explicit_events = []
                        # Only bind a date when the member's own name and role
                        # change immediately follow it. Publication/URL dates
                        # and another person's dates never fill a tenure.
                        dated = re.search(r'(?P<date>(?:19|20)\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?)[，,]?'
                            + re.escape(colleague) + r'(?:升任|担任|出任|接任|辞任|获委任为)' + literal_org + company_role_prefix + role,
                            text[match.start()-35 if match.start() >= 35 else 0:match.end()+10], re.I)
                        if dated:
                            origin = max(0, match.start()-35)
                            ds, de = origin+dated.start('date'), origin+dated.end('date')
                            qs, qe = origin+dated.start(), origin+dated.end()
                            event_quote = body[offsets[qs]:offsets[qe-1]+1]
                            if event_quote in quote:
                                explicit_events.append({'kind': 'appointment', 'date_literal': body[offsets[ds]:offsets[de-1]+1],
                                    'source_quote': event_quote, 'subject': literal_name})
                        result.append({'fact': quote, 'evidence_quote': quote, 'source_url': source.url, 'source_title': source.title,
                            'identity_match': 'confirmed', 'identity_confidence': meta['identity_confidence'],
                            'claim_type': 'person_team_member_record', 'person_chapters': [6], 'team_member_name': literal_name,
                            'team_affiliation_name': org, 'team_role_literal': relation, 'team_source_kind': 'explicit_company_role_in_article',
                            'team_role_events': explicit_events,
                            'provider': meta.get('provider'), 'source_grade': meta.get('source_grade', ''),
                            'retrieved_at': meta.get('retrieved_at', ''), 'published_at': meta.get('published_at', ''),
                            'extraction_method': 'retained_explicit_company_colleague_role'})
                        added += 1
        if audit is not None and added:
            audit.append({'source_url': source.url, 'status': 'explicit_company_colleague_roles', 'candidate_count': added})
    return result
