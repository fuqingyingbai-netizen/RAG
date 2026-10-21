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
    def calendar_dates(value):
        literal = numeric_literals(value)
        return {(int(y), int(m), int(d)) for y, m, d in re.findall(
            r'(?<!\d)((?:19|20)\d{2})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})(?:\s*日)?', literal)}
    if not calendar_dates(analysis) <= calendar_dates(' '.join(str(f.get('fact') or '') for f in supports)):
        errors.append('unsupported_date_combination')
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
