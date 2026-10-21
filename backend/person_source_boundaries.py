"""Conservative checks for explicit contradictions in a source-bound draft.

These guards reject specific unsupported statements. They neither verify the
source nor infer a person's competence from an organizational event.
"""
import re

try:
    from .person_text import folded
except ImportError:
    from person_text import folded


def source_context_errors(analysis, supports, context_facts=()):
    text = folded(analysis)
    original = folded(' '.join(str(f.get('fact') or '') for f in supports))
    errors = []
    from person_text import numeric_literals
    # A union of support cards cannot prove that EACH source contains the
    # same date, quantity or legal subject. Same-URL excerpts also remain one
    # source when the prose counts documents rather than individual snippets.
    source_count = re.search(r'([二两三四五六七八九十\d]+)份(?:材料|来源|报道|文献)', text)
    urls = {str(f.get('source_url') or '').rstrip('/') for f in supports if f.get('source_url')}
    if source_count and urls:
        digits={'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
        count=int(source_count[1]) if source_count[1].isdigit() else digits.get(source_count[1],0)
        if count > len(urls):
            errors.append('source_document_count_misstated')
    universal = re.search(r'(?:材料|来源|记录|原文|表述|披露|报道|证据)[^。；;]{0,6}?(?:均|都)(?:仅)?(?:确认|记载|载明|说明|披露|描述|提到|表明|指向|显示)', text)
    if universal and len(supports)>1:
        assertion=text[universal.end():].split('。',1)[0]
        values=re.findall(r'(?:19|20)\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?|\d+(?:\.\d+)?%|\d+(?:\.\d+)?(?:亿|万)?股',folded(numeric_literals(assertion)))
        entity=re.search(r'(?:在|于)([\u4e00-\u9fffA-Za-z0-9]{2,20}?(?:投资|集团|有限公司|股份公司))',assertion)
        if (any(any(value not in folded(numeric_literals(f.get('fact') or '')) for value in values) for f in supports)
                or entity and any(entity[1] not in folded(f.get('fact') or '') for f in supports)):
            errors.append('universal_source_claim_not_shared')
    # A date somewhere in the supplied page is not a date for every holding
    # or appointment. Require a local literal event sentence or an explicit
    # typed snapshot field before associating it with a ratio/role statement.
    dated = re.search(r'(?:截至|于)((?:19|20)\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?)[^。；;]{0,45}(?:持有|持股|担任|任职|签署)',text)
    if dated:
        declared=folded(numeric_literals(dated[1]))
        aligned=False
        for fact in supports:
            material=folded(numeric_literals(fact.get('fact') or ''))
            subject=folded((fact.get('observation') or {}).get('subject') or fact.get('subject') or '')
            period=(fact.get('observation') or {}).get('period') or ''
            period_parts=tuple(map(int,re.findall(r'\d+',period)))
            declared_parts=tuple(map(int,re.findall(r'\d+',declared)))
            if period_parts and period_parts[:len(declared_parts)]==declared_parts:
                aligned=True
            for field in (fact.get('observation') or {}).get('role_date_fields',[]):
                if '待核' in str(field.get('field') or ''):
                    continue
                for date in re.findall(r'(?:19|20)\d{2}[-年]\d{1,2}[-月]\d{1,2}',numeric_literals(field.get('source_value') or '')):
                    parts=tuple(map(int,re.findall(r'\d+',date)))
                    if parts[:len(declared_parts)]==declared_parts:
                        aligned=True
            for sentence in re.split(r'[。；;]',material):
                if declared in sentence and (subject and subject in sentence) and re.search(r'持有|持股|担任|任职|签署',sentence):
                    aligned=True
        if not aligned and any((f.get('observation') or {}).get('subject') or f.get('subject') for f in supports):
            errors.append('date_bound_to_different_source_event')
    if (re.search(r'而非既成事实|仅(?:仅)?为(?:待审)?(?:提案|议案)|尚未获(?:董事会)?批准',text)
            and re.search(r'董事会同意聘任|经审议[，,]?同意选举|表决情况[：:]\d+票同意[，,]0票反对',original)
            and re.search(r'自本次董事会审议通过之日起',original)):
        errors.append('adopted_resolution_as_unapproved_proposal')
    def calendar_dates(value):
        literal = numeric_literals(value)
        return {(int(y), int(m), int(d)) for y, m, d in re.findall(
            r'(?<!\d)((?:19|20)\d{2})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})(?:\s*日)?', literal)}
    def calendar_months(value):
        return {(int(y),int(month or iso_month)) for y,month,iso_month in re.findall(
            r'(?<!\d)((?:19|20)\d{2})\s*(?:年\s*(\d{1,2})\s*月|[-/]\s*(\d{1,2})(?!\d))',numeric_literals(value))}
    if not calendar_dates(analysis) <= calendar_dates(' '.join(str(f.get('fact') or '') for f in supports)):
        errors.append('unsupported_date_combination')
    if not calendar_months(analysis) <= calendar_months(' '.join(str(f.get('fact') or '') for f in supports)):
        errors.append('unsupported_date_combination')
    direct_pattern=r'直接(?:持有|持股|拥有)(?:(?!间接|另|而|但|其中|其他|未说明|未披露|未注明|是否)[^。；;])*'
    def direct_spans(value):
        value=folded(numeric_literals(value))
        return [m for m in re.finditer(direct_pattern,value)
            if not re.search(r'(?:未|不|没有|并非|是否|不能|不代表)[^。；;，,]{0,8}$',value[max(0,m.start()-16):m.start()])]
    direct_claims=direct_spans(analysis)
    if direct_claims:
        value_pattern=r'(?<![\d.])\d+(?:\.\d+)?(?:%|(?:亿|万)?股)'
        source_scopes=[m[0] for f in supports for m in direct_spans(f.get('fact') or '')]
        permitted={v for scope in source_scopes for v in re.findall(value_pattern,scope)}
        claimed={v for scope in direct_claims for v in re.findall(value_pattern,scope[0])}
        if not source_scopes or not claimed <= permitted:
            errors.append('ownership_mode_not_in_source')
    if (re.search(r'退休|接班|继任',original)
            and not re.search(r'投资协议|股权退出|股份退出|出售股权|赎回|清算|回购|股份转让',original)):
        for clause in re.split(r'[。；;，,]',text):
            exit_phrase=re.search(r'退出(?:路径|机制|安排|规划)',clause)
            if (exit_phrase and not re.search(r'管理层退出|退出管理岗位|退出经营|退休退出|岗位退出',clause)
                    and not re.search(r'不能|不构成|未说明|未涉及|未提供|不等于|不代表|没有',clause[:exit_phrase.start()])):
                errors.append('retirement_as_shareholder_exit')
    if (re.search(r'当前(?:的)?投后|现有(?:的)?投后|当前投资项目',text)
            and not re.search(r'投后|投资协议|本次投资|本项目',original)):
        errors.append('investment_scenario_not_established')
    for confirmed in re.finditer(r'属实|已独立核实|一致证实|交叉验证确认',text):
        if not re.search(r'不能|不代表|并非|不等于|尚未|未经|是否',text[max(0,confirmed.start()-12):confirmed.start()]):
            errors.append('source_statement_promoted_to_verified_fact')
    for absent in re.finditer(r'(?:亦|也)?无(?:任何|历史|个人)?(?:司法负面记录|司法记录|法律风险|不良记录)',text):
        if not re.search(r'不代表|不等于|不能推定|并非|不是|无法证明|不能认定|不能证明|不能据此认定',text[max(0,absent.start()-18):absent.start()]):
            errors.append('absence_as_general_exoneration')
    relative_snapshot=re.search(r'截至(?:本|该)?[^。；;]{0,20}(?:签署之日|签署日)',original)
    holding_claim=re.search(r'持有|持股|控股股东|实际控制人|一直担任',text)
    if relative_snapshot and holding_claim:
        if not re.search(r'签署|当时|历史|截至|该材料|该记录|披露时点|来源时点|所载时点|彼时|曾',text):
            errors.append('historical_snapshot_qualifier_missing')
        if (re.search(r'未(?:说明|载明|注明|披露|提供)[^。；;]{0,25}(?:该持股比例|该比例|持股比例)?[^。；;]{0,10}(?:基准日|基准日期|持股时点)',text)
                and not re.search(r'日历|具体年月日|具体签署日期|签署日的具体|具体年份',text)):
            errors.append('available_relative_baseline_denied')
    if (re.search(r'有利于提高.{0,12}效率|确保.{0,12}战略.{0,8}稳定',text)
            and re.search(r'有利于提高|确保长期战略',original)
            and not re.search(r'(?:公司|公告|文件|来源|材料|披露|原文).{0,12}(?:称|认为|表示|评价|自述|表述|宣称|载明)',text)):
        errors.append('company_assessment_without_attribution')
    if (re.search(r'未(?:载明|说明|提供|披露)[^。；;]{0,8}具体(?:年月日|日期)', text)
            and re.search(r'(?<!\d)\d{1,2}月\d{1,2}日', original)
            and not re.search(r'未(?:载明|说明|提供|披露)[^。；;]{0,8}(?:年份|完整日期|完整年月日)', text)):
        errors.append('available_calendar_information_denied')
    denied_period = re.search(r'未(?:载明|说明|提供|披露)[^。；;]{0,12}(?:具体起始日期|任期覆盖区间|任职起止|任期起止)', text)
    if denied_period and not re.search(r'当前|现任|后续|全部|逐项|逐职务', denied_period[0]):
        has_range = re.search(r'(?:19|20)\d{2}年\d{1,2}月\d{1,2}日至(?:19|20)\d{2}年\d{1,2}月\d{1,2}日', numeric_literals(original))
        if has_range or any((f.get('observation') or {}).get('role_date_fields') for f in supports):
            errors.append('available_role_period_denied')
    denied_roles=re.search(r'未(?:注明|载明|提供|说明|披露)(?:其|具体)?(?:任职起止|任职起始|任期起止|任职开始|起始时间)',text)
    if denied_roles and not re.search(r'所引|本条|本段|这些摘录|本批|此条',text):
        from person_records import payload
        def role_set(fact):
            data=payload(fact.get('fact') or '')
            value=data.get('职位') or data.get('角色') or data.get('曾担任角色') or ''
            return set(re.split(r'[,，、/\s]+',folded(' '.join(map(str,value)) if isinstance(value,list) else value))) - {''}
        for support in supports:
            issuer=(support.get('observation') or {}).get('issuer')
            roles=role_set(support)
            if not issuer or not roles:
                continue
            for fact in context_facts:
                record=fact.get('observation') or {}
                if record.get('issuer')!=issuer or not roles & role_set(fact) or fact.get('subject_scope')!='person':
                    continue
                fields=record.get('role_date_fields') or []
                if '起始' in denied_roles[0] or '开始' in denied_roles[0]:
                    fields=[f for f in fields if re.search(r'开始时间\s*[:：]\s*\d{4}|任职日期',f.get('source_value','')+f.get('field',''))]
                if fields:
                    errors.append('broader_material_contains_role_dates')
                    break
    reactions = r'员工不接受|员工.{0,10}(?:反对|抵制|不满)|集体辞职|店长推不下去|员工反馈|员工投诉'
    denied_reactions = r'(?:未提及|未见|没有|未说明|未提供)[^。；;]{0,20}(?:员工反应|员工反馈|员工意见|员工抵制|员工回应)'
    if re.search(denied_reactions, text) and re.search(reactions, original):
        errors.append('source_reaction_denied')
    denied_actors = r'(?:未提及|没有|未见|未说明)[^。；;]{0,15}(?:其他主体|其他人员|他人)[^。；;]{0,12}(?:介入|参与|行为|处置)'
    # Generic references to a team are not proof of intervention. Require an
    # explicit employee response or a named/role actor's concrete action.
    actor_action = r'(?:员工|店长|经理|董事会|管理层|[\u4e00-\u9fff]{2,4}(?:先生|女士))[^。；;]{0,12}(?:下令|决定|辞职|反对|抵制|开除|否决)|(?:当即下令|集体辞职|员工不接受|店长推不下去)'
    if re.search(denied_actors, text) and re.search(actor_action, original):
        errors.append('other_actor_action_denied')
    if (re.search(r'无其他(?:学历或)?履历信息|没有其他任职信息|未提供任何职业履历', text)
            and re.search(r'现任|曾任|历任|担任|董事|总裁|总经理|任职|加入', original)):
        errors.append('available_career_material_denied')
    if re.search(r'以[“"\']?集体辞职[”"\']?相要挟|威胁.{0,8}集体辞职|扬言.{0,8}集体辞职', original):
        for clause in re.split(r'[。；;，,]', text):
            if (re.search(r'员工.{0,8}集体辞职|引发.{0,8}集体辞职|集体辞职抗议|发生.{0,8}集体辞职', clause)
                    and not re.search(r'要挟|威胁|扬言|声称|提出|拟|是否|未说明', clause)):
                errors.append('threatened_event_as_occurred')
    if re.search(r'下令[^。；;]{0,30}开除|要求[^。；;]{0,20}开除', original):
        for clause in re.split(r'[。；;，,]', text):
            if (re.search(r'执行.{0,6}开除|已经?开除|全部开除|完成.{0,6}开除', clause)
                    and not re.search(r'下令|要求|拟|是否|未说明|未载明', clause)):
                errors.append('directed_action_as_completed')
    platform_rows = [f for f in supports if f.get('claim_type') == 'person_platform_record']
    if platform_rows and len(platform_rows) == len(supports):
        all_historical = all(re.search(r'；历史记录；|曾担任角色|"历史任职"', folded(f['fact'])) for f in platform_rows)
        if (all_historical and re.search(r'担任|现任|为.{0,20}负责人', text)
                and not re.search(r'历史|曾任|曾担任|当时|该时期|截至|该记录时点|原任', text)):
            errors.append('historical_role_without_qualification')
    # A book's publication year is evidence about publication, not the
    # implementation date of every practice it describes.
    for year in set(re.findall(r'((?:19|20)\d{2})年[^。；;]{0,8}出版', original)):
        event_date = re.search(year + r'年[^。；;]{0,14}(?:实施|建立|启动|设立|推行)', text)
        source_event_date = re.search(year + r'年[^。；;]{0,14}(?:实施|建立|启动|设立|推行)', original)
        if event_date and not source_event_date:
            errors.append('publication_year_as_event_date')
    if (re.search(r'被赋予.{0,15}(?:职责|权限)|获得.{0,12}决策权', text)
            and re.search(r'能够|期望|有望|可望|预期', original)
            and not re.search(r'聘任|任命|授权|委派|职责为|负责', original)):
        errors.append('commentary_as_formal_authority')
    if re.search(r'投后治理中|已进入投后|本次投资后|对本项目具有退出权', text) and not re.search(r'投后|投资协议|本次投资|本项目', original):
        errors.append('investment_scenario_not_established')
    for fact in supports:
        record = fact.get('observation') or {}
        if not record.get('ownership_subject'):
            continue
        name = folded(record.get('subject') or fact.get('subject') or '')
        ratios = set(re.findall(r'\d+(?:\.\d+)?%', folded(fact['fact'])))
        for clause in re.split(r'[，,。；;]', text):
            if (name and name in clause and ratios & set(re.findall(r'\d+(?:\.\d+)?%', clause))
                    and re.search(r'股东|持股|持有|拥有', clause)
                    and not re.search(r'夫妇|夫妻|配偶|共同|合计|不等同|不能|未说明|未披露|不代表', clause)):
                errors.append('joint_holding_as_individual')
    relation_list = re.search(r'这些公司的关联方有([^。；;]+)', original)
    if relation_list:
        entities = [re.sub(r'等公司.*$', '', s) for s in re.split(r'[、，,]', relation_list[1])]
        for clause in re.split(r'[，,。；;]', text):
            if (re.search(r'关联|控制|拥有', clause) and any(entity and entity in clause for entity in entities)
                    and not re.search(r'这些公司|该等公司|机构的关联|公司层面|上述机构|这些机构|间接|不能|不等于|未说明', clause)):
                errors.append('indirect_relationship_flattened')
    # A conclusion about all available material must consider contrary cards,
    # even when the writer selected a smaller subset to cite in this sentence.
    absence = re.search(r'未(?:载明|说明|提供|披露)(?:其|他|她|目标人物)?在(?P<entities>[^。；;，,]{2,70}?)的(?P<fields>[^。；;]{2,35})', text)
    if (absence and re.search(r'持股|股权|权益', absence['fields'])
            and not re.search(r'当前|现任|现行|同期|生效|所引片段|本段|本条', absence[0])):
        entities = re.split(r'[、和及与]', re.sub(r'等.*$', '', absence['entities']))
        for entity in entities:
            core = re.sub(r'(?:股份有限公司|控股有限公司|有限公司|国际|控股|集团|公司)$', '', entity)
            if len(core) < 2:
                continue
            for fact in context_facts:
                material = folded(fact.get('fact') or '')
                if (fact.get('subject_scope') == 'person' and core in material
                        and re.search(r'持有|拥有|持股|股权|权益', material)
                        and re.search(r'\d+(?:\.\d+)?%', material)):
                    errors.append('broader_material_contains_claimed_missing_fact')
                    break
    return list(dict.fromkeys(errors))
