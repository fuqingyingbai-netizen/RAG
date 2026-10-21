"""Conservative checks for explicit contradictions in a source-bound draft.

These guards reject specific unsupported statements. They neither verify the
source nor infer a person's competence from an organizational event.
"""
import re

try:
    from .person_text import folded
except ImportError:
    from person_text import folded


def source_context_errors(analysis, supports):
    text = folded(analysis)
    original = folded(' '.join(str(f.get('fact') or '') for f in supports))
    errors = []
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
    return list(dict.fromkeys(errors))
