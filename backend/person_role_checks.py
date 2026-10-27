"""Conservative checks for named executives in explicitly labelled rosters."""
import re
from person_text import folded,numeric_literals

ROLE = r'执行副总裁|高级副总裁|副总裁|总裁'


def _tenure_positions(text):
    text=numeric_literals(folded(text));result=[]
    for term in re.finditer(r'任期(?:均为|均|为)?(\d+年)',text):
        # A shared term may follow two explicit appointments separated by a
        # semicolon, with an intervening chairman nomination. The nominating
        # office alone is never a second appointment.
        sentence_start=text.rfind('。',0,term.start())+1
        sentence=text[sentence_start:term.start()]
        shared=('均' in term[0] or bool(re.search(r'(?:均|两职)$',sentence)))
        appointments=list(re.finditer(r'(?:选举|聘任|委任|选任)[^。；;]{0,25}?(董事长|总裁)(?=[，,；;。]|$)',sentence))
        if shared and {m[1] for m in appointments}=={'董事长','总裁'}:
            for role in ('董事长','总裁'):
                appointment=next(m for m in reversed(appointments) if m[1]==role)
                result.append((role,term[1],sentence_start+appointment.start(1)))
        start=max(text.rfind('。',0,term.start()),text.rfind('；',0,term.start()),text.rfind(';',0,term.start()))+1
        roles=list(re.finditer(r'(?<!副)(董事长|总裁)',text[start:term.start()]))
        if roles:
            last=roles[-1]
            # '经董事长提名...聘任其为总裁，任期三年' belongs to
            # the last named office, not the nominating chairman.
            result.append((last[1],term[1],start+last.start()))
            if '均' in term[0] and len(roles)>1:
                previous=roles[-2]
                if re.fullmatch(r'[、和与及兼]*',text[start+previous.end():start+last.start()]):
                    result.append((previous[1],term[1],start+previous.start()))
    return result


def role_tenures(text):
    return list(dict.fromkeys((role,term) for role,term,_ in _tenure_positions(text)))


def roster_roles(facts):
    rows = {}
    for fact in facts:
        text = folded(fact['fact'])
        people = list(re.finditer(r'([\u4e00-\u9fff]{2,4})(?:先生|女士)[，,]', text))
        for i, person in enumerate(people):
            paragraph = text[person.end():people[i+1].start() if i+1<len(people) else len(text)]
            current = re.search(r'现任(?:本公司)?('+ROLE+r')', paragraph)
            if current:
                rows.setdefault(person[1], set()).add(current[1])
    return rows


def role_errors(analysis, supports):
    """Flag an explicit current roster mismatch, not unknown historical jobs."""
    text, rows = folded(analysis), roster_roles(supports)
    for sentence in re.split(r'[。；;]', text):
        for name, source_roles in rows.items():
            # A generic '高管' summary makes no claim about the exact grade.
            direct = re.search(re.escape(name)+r'(?:现任|任本公司|为本公司)('+ROLE+r')', sentence)
            if direct and direct[1] not in source_roles:
                return ['named_executive_role_misattributed']
        group = re.search(r'等.*?(?:后任|现任|均任|均为)('+ROLE+r'(?:或(?:'+ROLE+r'))?)', sentence)
        if not group or not ('年报' in text or '现任' in sentence):
            continue
        names = [name for name in rows if name in sentence[:group.start()]]
        claimed = set(re.findall(ROLE,group[1]))
        if len(names)>=2 and any(not rows[name]&claimed for name in names):
            return ['named_executive_role_misattributed']
    return []


def align_tenure_citations(rows,facts):
    """Add an explicit same-document tenure record; never change claim text.

    Candidates must already be provided, eligible personal evidence, identify
    the target near the role, and contain the exact role/term combination.
    The resulting references still undergo ordinary and semantic validation.
    """
    by_id={f['evidence_id']:f for f in facts};events=[];result=[]
    def terms(fact):
        text=numeric_literals(folded(fact['fact']));subject=folded(fact.get('subject',''))
        return {(role,term) for role,term,start in _tenure_positions(text)
                if subject and subject in text[max(0,start-45):start+len(role)]}
    for i,row in enumerate(rows):
        revised=dict(row);ids=row.get('evidence_ids')
        if not isinstance(ids,list) or not ids or any(eid not in by_id for eid in ids):result.append(revised);continue
        ids=list(dict.fromkeys(ids));urls={by_id[eid]['source_url'] for eid in ids}
        required=set(role_tenures(row.get('analysis','')))
        covered=set().union(*(terms(by_id[eid]) for eid in ids))
        for role,term in sorted(required-covered):
            candidates=[f for f in facts if f.get('analysis_allowed') and f.get('subject_scope')=='person'
                        and f['source_url'] in urls and (role,term) in terms(f)]
            if candidates:
                f=min(candidates,key=lambda f:len(f['fact']))
                if f['evidence_id'] not in ids:
                    ids.append(f['evidence_id']);events.append({'claim_index':i,'role':role,'term':term,
                        'added_evidence_id':f['evidence_id'],'original':f['fact'],'reason':'explicit_same_document_target_role_and_tenure'})
        revised['evidence_ids']=ids;result.append(revised)
    return result,events
