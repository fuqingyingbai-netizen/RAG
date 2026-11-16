"""Narrow, offline corrections from a reviewed industry run. No IO."""
import re
import hashlib
from difflib import SequenceMatcher

VERSION = 'industry-review-fixes-v2-audited-boundaries'


def local_segments(fact, quote, context, segments):
    """A mixed-subject introduction cannot scope a following named example."""
    direct = [s for s in segments if s in quote]
    if direct:
        return direct
    lines = str(context).splitlines()
    heading = lines[0].strip(' #\t') if len(lines) > 1 else ''
    if (not heading or len(heading) > 65 or re.search(
            r'从.{0,45}到|包括|涵盖|分别|领域[，,]|[。；;]|上游|中游|下游', heading)):
        return []
    # Inherit only an explicit segment heading, not a nearby narrative clause.
    return [s for s in segments if re.fullmatch(
        r'(?:[一二三四五六七八九十\d]+[.、）)]\s*)?(?:全球|中国大陆|中国|我国|国内|海外)?' + re.escape(s) +
        r'(?:领域|行业|赛道|市场|应用|产业|发展|概况|技术|产品|案例|分析|：|:|\s)*', heading)]


def directive_primary(fact, source_text):
    """Recognize an original directive by its document identity and structure."""
    from industry_claims import public_source_type
    if public_source_type(fact.get('source_url')) not in {'government', 'regulatory'}:
        return False
    title = str(fact.get('source_title') or '')
    if re.search(r'解读|评论|访谈|答记者问|图解|转载|媒体报道', title):
        return False
    if not re.search(r'实施意见|指导意见|行动计划|工作方案|规划纲要|(?:关于.{2,60})?(?:通知|决定|公告)$', title.split('_')[0]):
        return False
    body = str(source_text or '')
    loc=(fact.get('provenance') or {}).get('locator') or {}
    start,end=loc.get('start'),loc.get('end')
    if (loc.get('status')!='verified' or type(start) is not int or type(end) is not int
            or not 0<=start<end<=len(body) or body[start:end]!=loc.get('quote')
            or loc.get('body_sha256')!=hashlib.sha256(body.encode()).hexdigest()):
        return False
    quote = str(fact.get('evidence_quote') or fact.get('fact') or '')
    structure = re.search(r'(?:^|\n)\s*(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[）)]|\d+[.、．])', body)
    obligation = re.search(r'应当|不得|确保|明确.{0,12}权限|建立|加强|完善|推动|促进', quote)
    return bool(structure and obligation)


def mask_task_counts(text):
    """Mask only editorial task counts; preserve all measured business counts."""
    patterns = (
        r'其余\s*\d+\s*项(?=见(?:独立|核验|本轮)?台账)',
        r'本节仅列前\s*\d+\s*项(?:优先工作)?[，,]\s*共\s*\d+\s*项',
        r'本轮共登记\s*\d+\s*项核验任务',
    )
    for pattern in patterns:
        text = re.sub(pattern, lambda m: re.sub(r'\d+', lambda n: ' ' * len(n[0]), m[0]), text)
    return text


def policy_source_assertion(line):
    """Mask material lists, but retain actual assertions embedded in that field."""
    def requested_material(match):
        value=match[0]
        if re.search(r'明确|规定|应当|不得|必须|禁止|证实|证明|认定|已(?:经|核实|核验|确认)|属于|就是',value):
            return value
        return ''
    cleaned=re.sub(r'(?:所需材料|材料)[：:][^。\n|]*',requested_material,line)
    return bool(re.search(r'政策原文|法规原文',cleaned))


def completion_issue(claim, scope=None):
    """Only forecast targets actually stated positively contribute to the horizon."""
    q=claim.get('question') or ''
    text=str(claim.get('conclusion') or '')+' '+str(claim.get('text') or '')
    ctx=scope or claim.get('question_completion_context') or {}
    if q=='未来五至十年来源预测':
        cutoff=str(ctx.get('as_of_date') or '')[:4]
        if cutoff.isdigit():
            allowed=ctx.get('forecast_target_years')
            allowed={int(y) for y in allowed if str(y).isdigit()} if allowed is not None else None
            used=set()
            # A document title, a denied comparison, or a future work item is
            # not an assertion that this forecast has been answered.
            body=re.sub(r'《[^》]*》','所引文件',text)
            for clause in re.split(r'[。！？；;，,\n]',body):
                if re.search(r'不能|不应|不得|不宜|不等于|无法|未(?:曾)?(?:披露|提供|给出|说明)|'
                             r'没有|缺少|缺乏|尚无|待(?:补|核实|核验)|需(?:要)?(?:补|核验|跟踪)|继续跟踪',clause):
                    continue
                if not re.search(r'预测|预计|预估|目标|情景|展望',clause):continue
                used.update(int(y) for y in re.findall(r'(?<!\d)(20\d{2})年?',clause))
            if allowed is not None:used &= allowed
            if not any(5<=y-int(cutoff)<=10 for y in used):return 'forecast_horizon_not_answered'
    if q=='五力机制与护城河':
        dimensions=sum(bool(re.search(p,text)) for p in (
            r'供应商.{0,10}(?:议价|价格|锁定)',r'客户.{0,10}(?:议价|选择|切换)',
            r'进入.{0,6}壁垒|新进入者',r'替代.{0,6}(?:品|竞争|威胁)|绕过.{0,12}界面',
            r'现有.{0,8}(?:对手|竞争)|价格战|同业竞争'))
        if dimensions<2 and re.search(r'(?:只|仅)(?:披露|涉及|提出|给出)|一种.{0,12}(?:担忧|风险|路径)',text):
            return 'competition_framework_partial'
    return None


def attach_completion_context(claim, packet, eids):
    scope = packet.get('_scope') or {}
    targets = []
    for eid in eids:
        fact = (packet.get('_facts') or {}).get(eid, {})
        n = fact.get('numeric_context') or {}
        period = str(n.get('period') or '')
        if n.get('is_forecast') is True and re.fullmatch(r'20\d{2}', period):
            targets.append(int(period))
    claim['question_completion_context'] = {
        'as_of_date': scope.get('as_of_date'), 'forecast_target_years': targets}
    return claim


def reading_paragraphs(claims):
    """Only exact prose duplicates share a reading paragraph and its references.

    Similarity cannot establish that conditions or value-to-subject bindings
    agree. Leave such prose intact for editorial review, not destructive folding.
    """
    from industry_reader import analysis_paragraphs
    rows=[];positions={}
    for claim in claims:
        for text in analysis_paragraphs(claim.get('text') or ''):
            key=re.sub(r'\s+','',text)
            if not key:continue
            refs=tuple(dict.fromkeys(claim.get('evidence_ids') or []))
            if key in positions:
                old=rows[positions[key]]
                old['refs']=tuple(dict.fromkeys((*old['refs'],*refs)))
                continue
            positions[key]=len(rows)
            rows.append({'text':text,'refs':refs,'question':claim.get('question')})
    return rows


def recovery_collection_exhausted(collection):
    """Read global hard limits, not a temporarily stopped collection phase."""
    if collection is None:
        return False
    return any(collection.used[k] >= collection.limits[k] for k in ('queries','search_requests')) or (
        collection.elapsed >= collection.limits['seconds'])


def implementation_only(fact):
    text=str((fact.get('fact_contract') or {}).get('statement') or fact.get('fact') or '')
    return bool(re.search(r'异步批量数据采集|追踪本身|工具调用主体.{0,6}用户|埋点|遥测|OpenTelemetry',text,re.I)
        and not re.search(r'替代|迭代风险|失效|漏洞|攻击|测试.{0,20}(?:成功率|成本|延迟)',text))


def incompatible_definitions_as_conflict(text, facts):
    if not re.search(r'证据冲突|数据冲突|数值.{0,8}(?:不一致|冲突)|规模.{0,12}(?:不一致|差异值)',text):
        return False
    if re.search(r'不代表|不等于|不能据此|尚不能|仅是口径差异',text):
        return False
    groups={};count=0
    for f in facts:
        n=f.get('numeric_context') or {}
        if not all(n.get(k) for k in ('metric','period','geography','definition','unit')):
            continue
        if (f.get('numeric_validation') or {}).get('passed') is not True:
            continue
        key=tuple(str(n[k]) for k in ('metric','period','geography','definition','unit'))+(n.get('is_forecast'),)
        groups.setdefault(key,set()).add(str(n.get('value')));count+=1
    return count>=2 and len(groups)>=2 and not any(len(v)>=2 for v in groups.values())


def proposal_responsibility(value):
    return re.sub(r'(?:最终)?(?:统计)?口径确认(?:由|责任在)客户方负责',
        '统计定义及可比性由研究方核验，客户方确认研究用途与范围', str(value))


def diverse_market_ids(order, eligible, cards):
    """Reserve distinct disclosed definitions within the existing four-card cap."""
    first=[];seen=set()
    for eid in list(dict.fromkeys(order+eligible)):
        f=cards[eid];n=f.get('numeric_context') or {};c=f.get('fact_contract') or {}
        if (c.get('quantity_type')!='amount' or c.get('sample_boundary')
                or (f.get('numeric_validation') or {}).get('passed') is not True
                or not all(n.get(k) for k in ('definition','period','geography','metric'))):
            continue
        key=tuple(str(n[k]) for k in ('definition','period','geography','metric'))+(n.get('is_forecast'),)
        if key not in seen:first.append(eid);seen.add(key)
        if len(first)==4:break
    return list(dict.fromkeys(first+order))


def compact_source_rows(source, entries):
    """Group a source while explicitly pairing every locator with its E-ID."""
    rows=[]
    for i in range(0,len(entries),4):
        chunk=entries[i:i+4]
        evidence='<br>'.join(e for e,_ in chunk)
        locations='<br>'.join(e.split('<br>',1)[0]+': '+loc for e,loc in chunk)
        rows.append('| '+evidence+' | '+source+' | '+locations+' |')
    return rows


WRITER_GUIDANCE = '''本题有可比材料时，按同一对象层次、客群、期间与条件逐项比较，并说明差异能支持什么判断。
已有数字应按来源和定义完整列示，不因不可比较而遗漏同题另一口径；不能把不同定义的正常差异当成数据冲突。
保留条件性机制推理并说明它是研究推论及所需前提；不要把每个业务含义都要求原文逐字陈述，也不要把假设当实际结果。
多轮执行增加成本不等于成本与模型单价无关；缺少分解数据时不认定唯一成本瓶颈。
每段先表达一个发现，再说明依据、含义和必要限制；不重复复述同一材料，不以无指代的其机制或上述行为开段。
未来跨度以本轮截止日为起点；当年单点预测不能回答未来五至十年。'''
