"""Person-specific professional queries; never recurse through returned companies."""
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

try:
    from .person_retrieval import integer, user_time_remaining
    from .person_evidence import compact, name_in_text
except ImportError:
    from person_retrieval import integer, user_time_remaining
    from person_evidence import compact, name_in_text

BASE = ['get_executive_related_companies', 'get_executive_positions',
        'get_executive_historical_related_companies', 'get_executive_historical_positions',
        'get_executive_risk_scan']
IDENTITY = ['get_executive_positions', 'get_executive_related_companies']
CRITICAL = ['get_executive_risk_scan', 'get_executive_dishonest',
            'get_executive_judgment_debtor', 'get_executive_judicial_docs']
DETAIL = {'失信': 'get_executive_dishonest', '被执行': 'get_executive_judgment_debtor',
          '限高': 'get_executive_high_consumption_ban', '限制高消费': 'get_executive_high_consumption_ban',
          '处罚': 'get_executive_admin_penalty', '冻结': 'get_executive_equity_freeze',
          '质押': 'get_executive_equity_pledge', '裁判文书': 'get_executive_judicial_docs',
          '立案': 'get_executive_case_filing'}


def documents(payload):
    result = payload.get('result', payload)
    if not isinstance(result, dict):
        return []
    docs = []
    for block in result.get('content', []):
        try:
            data = json.loads(block.get('text') or '')
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            docs.append(data)
    if not docs and any(k in result for k in ('人员名称', 'personName')):
        docs.append(result)
    return docs


def response_state(payload):
    """Recognize explicit provider restrictions and scoped empty responses."""
    docs = documents(payload)
    if any(any(doc.get(k) for k in ('地域限制', '地区限制', '访问限制', '权限限制')) for doc in docs):
        return 'regional_restriction'
    # This is a provider assertion about its database, never legal clearance.
    if docs and all(isinstance(doc.get('搜索结果'), str) and re.fullmatch(
            r'已全量扫描[^。\n]{1,120}数据库，未发现任何记录[。.]?', doc['搜索结果'].strip()) for doc in docs):
        return 'explicit_empty_record_list'
    lists = [v for doc in docs for v in doc.values() if isinstance(v, list)]
    if lists and all(not v for v in lists):
        return 'explicit_empty_record_list'
    return ''


def entity_not_found(payload):
    error = payload.get('error') if isinstance(payload,dict) else None
    message = str(error.get('message','')) if isinstance(error,dict) else str(error or '')
    return bool(re.search(r'未找到公司|未查到.{0,20}公司|company.{0,20}not found|company_not_found',message,re.I))


def validated_records(payload, person, company, tool):
    """Validate returned subject fields, never just echoed request arguments."""
    quotes = []
    matched = False
    for doc in documents(payload):
        subject = str(doc.get('人员名称') or doc.get('personName') or '')
        org = str(doc.get('企业名称') or doc.get('companyName') or '')
        if compact(subject) != compact(person) or compact(org) != compact(company):
            continue
        matched = True
        for value in doc.values():
            if not isinstance(value, list):
                continue
            for row in value[:100]:
                if not isinstance(row, dict):
                    continue
                # Only actual record rows, never provider-authored summaries
                # declaring innocence or totals describing an empty query.
                keys = set(row)
                if not keys.intersection({'企业名称', '公司名称', '案号', '案件编号', '决定书文号', '处罚决定书文号', '执行案号',
                                          '出质人', '质权人', '出质股权数额', '出质股数', '冻结股权数额', '执行法院',
                                          '处罚机关', '作出行政处罚决定机关名称', '被执行人姓名', '失信被执行人姓名'}):
                    continue
                if tool in CRITICAL or tool in DETAIL.values():
                    if not keys.intersection({'案号', '案件编号', '决定书文号', '处罚决定书文号', '执行案号',
                                              '出质人', '质权人', '出质股权数额', '出质股数', '冻结股权数额',
                                              '执行法院', '处罚机关', '作出行政处罚决定机关名称',
                                              '被执行人姓名', '失信被执行人姓名'}):
                        continue
                historical = '历史' if 'historical' in tool else '平台所列（是否现任需核验）'
                quotes.append(f'{person}；查询定位机构：{company}；{historical}记录；' + json.dumps(row, ensure_ascii=False, sort_keys=True))
    return matched, quotes


def detail_tools(text, explicit=''):
    selected = []
    for label, tool in DETAIL.items():
        # Negative "0条/无记录" scans do not trigger every drilldown. Explicit
        # commissioned checks still run, and failure/zero is retained as a gap.
        positive = any(label in line and re.search(r'[:：|]\s*[1-9]\d*\s*(?:条|项|[,，}|]|$)', line)
                       for line in str(text).splitlines())
        if label in explicit or positive:
            selected.append(tool)
    return list(dict.fromkeys(selected))


def xiniu_plan(intake, company):
    """Offer only capabilities relevant to requested person questions."""
    text = ' '.join([*intake.get('focus_modules', []), *intake.get('focus_questions', []),
                     str(intake.get('special_requirements') or ''), str(intake.get('person_context') or '')])
    tasks = []
    entity = next((kind for kind in ('基金管理人', '投资机构', '基金', 'LP')
                   if re.search(r'\bLP\b' if kind == 'LP' else re.escape(kind), text, re.I)), '')
    if entity:
        tasks.append(('get_entity_profile', {'firm_name': company, 'entity_type': entity}, '关联机构资本背景'))
    if re.search('经营|融资|资本|退出|financ|funding', text, re.I):
        tasks.append(('get_company_info', {'firm_name': company, 'aspect': '融资状况分析'}, '经营胜任力'))
    if re.search('团队|高管|人员变动|招聘|team', text, re.I):
        tasks.append(('get_company_info', {'firm_name': company, 'aspect': '团队人物及招聘分析'}, '核心管理团队背景'))
    if re.search('近期|最近|近一年|舆情|事件|动态|recent', text, re.I):
        cutoff = date.fromisoformat(intake.get('as_of_date') or date.today().isoformat())
        tasks.append(('get_project_events', {'company_names': [company], 'start_date': (cutoff-timedelta(days=365)).isoformat(),
                     'end_date': cutoff.isoformat(), 'limit': 20}, '关联机构事件'))
    return tasks[:3]


def coverage_rows(attempts):
    """Fold lifecycle events into query outcomes; summaries are never zero hits."""
    latest = {}
    for row in attempts:
        if row.get('tool') in {'initialize', 'person_collection'}:
            continue
        key = (row.get('provider', ''), row.get('subject', ''), row.get('tool', ''))
        if row.get('status') == 'reused' and key in latest:
            continue
        # A later local dedup/skip must not erase an earlier query result.
        if row.get('status') == 'not_queried' and key in latest and latest[key].get('status') not in {'not_queried', 'reused'}:
            continue
        latest[key] = row
    labels = {'records_found': '查到记录', 'empty_result': '返回空结果',
              'failed': '调用失败', 'not_queried': '尚未查询', 'returned_unresolved': '返回待核验'}
    reasons = {'person_platform_budget_exhausted': '本轮本地调用预算已用尽',
               'critical_budget_reserved': '为关键司法信用查询预留预算',
               'affiliation_budget_reserved': '为关联主体关键查询预留预算',
               'identity_not_verified': '人物与定位机构关系尚未核实',
               'returned_person_or_company_identity_not_matched': '返回主体与目标不匹配',
               'zero_or_summary_only_not_exoneration': '仅返回摘要或缺少可引用明细',
               'explicit_empty_record_list': '匹配主体的记录列表为空，仅限该项查询',
               'source_statement_pending_review': '取得来源记录，内容仍须复核',
               'quota_exceeded': '平台明确返回额度不足', 'unauthorized': '鉴权失败',
               'rate_limited': '平台限流', 'request_failed': '请求失败，尚不能判断原因',
               'not_configured': '未配置', 'online_search_disabled': '本轮未开启在线检索',
               'access_denied':'平台拒绝该请求，需核对权限或主体范围', 'initialization_failed':'平台连接初始化未完成',
               'weak_affiliation_candidate': '关联线索不足，未扩展付费查询'}
    reasons['user_time_budget_exhausted'] = '已到用户设定的时间预算，未发起新调用'
    reasons['provider_entity_not_found'] = '平台未找到该公司记录，须核对实体匹配及覆盖范围；不代表主体不存在或无风险'
    reasons['regional_restriction'] = '平台返回地域或访问限制，并非无记录'
    result = []
    for row in latest.values():
        raw = row.get('status')
        state = ('records_found' if raw in {'collected', 'selected_into_report', 'validated_records'} else
                 'empty_result' if raw == 'empty_result' else 'failed' if raw == 'failed' else
                 'not_queried' if raw in {'not_queried', 'reused'} else 'returned_unresolved')
        tool_labels = {'get_executive_positions': '在外任职', 'get_executive_related_companies': '关联企业',
                       'get_executive_historical_positions': '历史任职', 'get_executive_historical_related_companies': '历史关联企业',
                       'get_executive_risk_scan': '风险线索扫描', 'get_executive_dishonest': '失信被执行记录',
                       'get_executive_judgment_debtor': '被执行记录', 'get_executive_judicial_docs': '裁判文书',
                       'get_executive_equity_pledge': '股权质押', 'affiliation_core_checks': '关联线索核实'}
        tool_labels.update(get_executive_high_consumption_ban='限制高消费',get_executive_admin_penalty='行政处罚',
                           get_executive_equity_freeze='股权冻结',get_executive_case_filing='立案信息',
                           get_project_events='关联机构事件',get_entity_profile='关联机构背景')
        tool = row.get('tool','')
        label = '企业资料·' + tool.split(':',1)[1] if tool.startswith('get_company_info:') else tool_labels.get(tool,tool)
        result.append({**{k: row.get(k, '') for k in ('provider', 'subject', 'tool', 'reason', 'retrieved_at')},
                       'tool_label': label,
                       'status': state, 'status_label': labels[state],
                       'reason_label': reasons.get(row.get('reason'), '结果仍需复核' if not row.get('reason') else row['reason'])})
    return result


def retain_response(project, provider, tool, payload, subject=''):
    """Keep returned originals, including empty/summary/schema-change responses."""
    if not getattr(project, 'id', None):
        return ''
    try:
        from .research_store import research_store
    except ImportError:
        from research_store import research_store
    text = json.dumps(payload, ensure_ascii=False)
    for name in ('QCC_API_KEY', 'XINIU_API_KEY', 'TYC_API_KEY'):
        secret = os.getenv(name, '').strip()
        if secret:
            text = text.replace(secret, '[REDACTED]')
            bare = re.sub(r'^Bearer\s+', '', secret, flags=re.I)
            if len(bare) >= 8:
                text = text.replace(bare, '[REDACTED]')
    key = research_store.put_text(f'projects/{project.id}/person-platform-responses/{provider}_{uuid.uuid4().hex[:20]}.json',
                                  text, 'application/json; charset=utf-8')
    retrieval = dict(getattr(project, 'person_retrieval_audit', None) or {})
    retrieval['professional_response_objects'] = [*retrieval.get('professional_response_objects', []),
        {'provider': provider, 'tool': tool, 'subject': subject, 'object_key': key,
         'retrieved_at': datetime.now().isoformat(timespec='seconds')}]
    project.person_retrieval_audit = retrieval
    return key


def primary_affiliation_basis(project, intake, company):
    """A public filing can locate company context without clearing QCC checks."""
    try:
        from .person_text import folded
        from .person_chapter_research import primary_document
        from .person_identity import discovery_index
    except ImportError:
        from person_text import folded
        from person_chapter_research import primary_document
        from person_identity import discovery_index
    person = folded(intake.get('target_name') or project.target_name)
    organization = folded(company)
    aliases = [folded(v) for v in (intake.get('person_anchor') or {}).get('known_affiliations', [])]
    forms = [organization, *[a for a in aliases if len(a)>=3 and a in organization]]
    references = []
    for source in getattr(project, 'sources', []) or []:
        meta = source.source_metadata or {}
        if not primary_document(source) or meta.get('identity_confidence') not in {'high','medium'} or meta.get('identity_status') == 'quarantined':
            continue
        if discovery_index(source.title, source.content):
            continue
        text = folded(source.content)
        for match in re.finditer(re.escape(person), text):
            window = text[max(0,match.start()-180):match.end()+180]
            if any(org and org in window for org in forms) and re.search(r'董事|主席|创始|创办|任职|担任|总裁|founder|chairman|director', window, re.I):
                references.append({'source_id':source.id,'url':source.url})
                break
    return references[:3]


def reassess_retained_outcomes(project):
    """Clarify old generic failures from saved originals; make no provider call."""
    try:
        from .research_store import research_store
    except ImportError:
        from research_store import research_store
    rows = getattr(project,'person_platform_attempts',None) or []
    objects = (getattr(project,'person_retrieval_audit',None) or {}).get('professional_response_objects',[])
    changed = 0
    for record in objects:
        tool = record.get('tool','').removesuffix(':retry')
        candidates = [r for r in rows if r.get('provider')==record.get('provider') and r.get('subject')==record.get('subject') and r.get('tool')==tool]
        if not candidates:
            continue
        latest = candidates[-1]
        if not (latest.get('status') == 'failed' and latest.get('reason') == 'request_failed' or latest.get('status')=='returned'):
            continue
        try:
            raw = json.loads(research_store.get_text(record['object_key']))
        except Exception:
            continue
        state,reason = ('failed','provider_entity_not_found') if entity_not_found(raw) else (
            ('empty_result','explicit_empty_record_list') if response_state(raw)=='explicit_empty_record_list' else ('',''))
        if not state:
            continue
        for row in candidates:
            if row.get('status') != latest.get('status'):
                continue
            row.update(original_status=row.get('status'),original_reason=row.get('reason',''),
                       status=state,reason=reason,classification_source='retained_original_response',
                       raw_response_key=record['object_key'])
            changed += 1
    return changed


def collect_group(workflow, db, project, jobs, emit=None):
    """Verify all direct affiliations, then core checks, then company background."""
    added = 0
    budget = integer('PERSON_PLATFORM_CALL_BUDGET', 18, 0, 100)
    project.person_platform_core_pending = set()
    verified = []
    for company, intake in jobs:
        person = str(intake.get('target_name') or project.target_name)
        query_person = ''.join(re.findall(r'[\u4e00-\u9fff·]', person)) or person
        args = {'searchKey': company, 'personName': query_person}
        used = len(getattr(project, 'person_platform_query_keys', set()))
        remaining = budget - used - len(project.person_platform_core_pending)
        reason = ''
        if remaining < len(IDENTITY + CRITICAL):
            reason = 'person_platform_budget_exhausted'
        else:
            added += collect(workflow, db, project, company, intake, emit, phase='identity')
            if not getattr(project, 'person_platform_identities', {}).get((compact(query_person), compact(company))):
                reason = 'identity_not_verified'
        if reason:
            audit = workflow._company_platform_audit(project, intake, company, 'qcc', '')
            for tool in (IDENTITY + CRITICAL if reason == 'person_platform_budget_exhausted' else CRITICAL):
                audit.record(tool, args, 'not_queried', reason)
            continue
        verified.append((company, intake))
        project.person_platform_core_pending.update(
            ('qcc', tool, json.dumps(args, ensure_ascii=False, sort_keys=True)) for tool in CRITICAL)
    for phase in ('critical', 'background'):
        for company, intake in verified:
            added += collect(workflow, db, project, company, intake, emit, phase=phase)
    return added


def collect(workflow, db, project, company, intake, emit=None, phase='all'):
    person = str(intake.get('target_name') or project.target_name or '')
    if intake.get('ai_search_enabled') is False:
        rows = getattr(project, 'person_platform_attempts', None)
        if rows is None:
            rows = []
            project.person_platform_attempts = rows
        rows.append({'provider': 'person_routing', 'tool': 'professional_collection', 'subject': company,
                     'status': 'not_queried', 'reason': 'online_search_disabled',
                     'retrieved_at': datetime.now().isoformat(timespec='seconds')})
        return 0
    if not company or compact(company) == compact(person):
        return 0
    if not hasattr(project, 'person_platform_query_keys'):
        project.person_platform_query_keys = set()
    budget = integer('PERSON_PLATFORM_CALL_BUDGET', 18, 0, 100)
    added = 0
    explicit = ' '.join([*intake.get('focus_questions', []), str(intake.get('special_requirements') or '')])
    query_person = ''.join(re.findall(r'[\u4e00-\u9fff·]', person)) or person
    token = os.getenv('QCC_API_KEY', '').strip()
    headers = {'Authorization': token if token.lower().startswith('bearer ') else 'Bearer ' + token}
    url = os.getenv('QCC_MCP_EXECUTIVE_URL', 'https://agent.qcc.com/mcp/executive/stream')
    timeout = integer('STRUCTURED_SOURCE_TIMEOUT_SECONDS', 45, 10, 180)
    tasks = list(dict.fromkeys(IDENTITY + CRITICAL + BASE + detail_tools('', explicit)))
    if phase == 'identity':
        tasks = IDENTITY[:]
    elif phase == 'critical':
        tasks = CRITICAL + detail_tools('', explicit)
    elif phase == 'background':
        tasks = [t for t in tasks if t not in IDENTITY + CRITICAL]
    tasks = list(dict.fromkeys(tasks))
    identities = getattr(project, 'person_platform_identities', None)
    if identities is None:
        identities = {}
        project.person_platform_identities = identities
    identity_key = (compact(query_person), compact(company))
    audit = workflow._company_platform_audit(project, intake, company, 'qcc', token)
    audit.planned(tasks)

    def reserve(provider, tool, args, active_audit):
        remaining = user_time_remaining()
        if remaining is not None and remaining < 60:
            active_audit.record(tool, args, 'not_queried', 'user_time_budget_exhausted')
            return False
        key = (provider, tool, json.dumps(args, ensure_ascii=False, sort_keys=True))
        label = tool + (':' + args['aspect'] if args.get('aspect') else '')
        pending = getattr(project, 'person_platform_core_pending', set())
        if key in project.person_platform_query_keys:
            pending.discard(key)
            active_audit.record(label, args, 'reused', 'same_run_query_deduplicated')
            return False
        if phase != 'all' and key not in pending and len(project.person_platform_query_keys) + len(pending) >= budget:
            active_audit.record(label, args, 'not_queried', 'critical_budget_reserved')
            return False
        if len(project.person_platform_query_keys) >= budget:
            active_audit.record(label, args, 'not_queried', 'person_platform_budget_exhausted')
            return False
        # The initial company pass precedes web-discovered affiliations. Keep
        # part of the same total budget for their identity and core checks.
        reserve_count = min(integer('PERSON_PLATFORM_AFFILIATION_RESERVE', 8, 0, 30), max(0, budget - len(IDENTITY + CRITICAL)))
        if phase == 'all' and len(project.person_platform_query_keys) >= budget - reserve_count:
            active_audit.record(label, args, 'not_queried', 'affiliation_budget_reserved')
            return False
        project.person_platform_query_keys.add(key)
        pending.discard(key)
        return True

    remaining = user_time_remaining()
    if remaining is not None and remaining < 60:
        audit.stop_reason = 'user_time_budget_exhausted'
        audit.finish_unqueried()
    elif not token:
        audit.stop_reason = 'not_configured'
        audit.finish_unqueried()
    elif not audit.cached_failure():
        try:
            session, ok, error = audit.initialize(workflow._mcp_initialize, url, headers, timeout=timeout)
            if not ok:
                audit.result('initialize', {}, {'error': error})
                audit.stop_reason = audit.stop_reason or 'initialization_failed'
                audit.finish_unqueried()
            else:
                for index, tool in enumerate(tasks):
                    args = {'searchKey': company, 'personName': query_person}
                    if tool not in IDENTITY and not identities.get(identity_key):
                        audit.record(tool, args, 'not_queried', 'identity_not_verified')
                        continue
                    if not reserve('qcc', tool, args, audit):
                        continue
                    payload, session = audit.call(workflow._mcp_call_tool, url, headers, tool, args, session=session, request_id=100+index, timeout=timeout)
                    raw_key = retain_response(project, 'qcc', tool, payload, company)
                    response_kind = response_state(payload)
                    if response_kind == 'regional_restriction':
                        audit.result(tool, args, {'error': {'code': 403, 'message': 'provider_region_restricted'}})
                        audit.record(tool, args, 'failed', 'regional_restriction')
                        audit.stop_reason = 'regional_restriction'
                        audit.finish_unqueried()
                        break
                    if audit.result(tool, args, payload):
                        break
                    if raw_key:
                        project.person_platform_attempts[-1]['raw_response_key'] = raw_key
                    if payload.get('error'):
                        continue
                    docs = documents(payload)
                    # A new output schema or a genuine zero remains inspectable
                    # in the query audit, without treating summaries as facts.
                    last = getattr(project, 'person_platform_attempts', [])[-1]
                    last['returned_fields'] = sorted({k for doc in docs for k in doc})
                    last['returned_list_counts'] = {k: len(v) for doc in docs for k, v in doc.items() if isinstance(v, list)}
                    matched, quotes = validated_records(payload, query_person, company, tool)
                    if not matched:
                        audit.record(tool, args, 'rejected', 'returned_person_or_company_identity_not_matched')
                        continue
                    if tool in IDENTITY and quotes:
                        identities[identity_key] = True
                    raw = workflow._extract_mcp_text(payload)
                    if tool == 'get_executive_risk_scan':
                        for name in detail_tools(raw, explicit):
                            if name not in tasks:
                                tasks.append(name)
                                audit.planned([name])
                    if not quotes:
                        empty = response_kind == 'explicit_empty_record_list'
                        audit.record(tool, args, 'empty_result' if empty else 'no_citable_record',
                                     'explicit_empty_record_list' if empty else 'zero_or_summary_only_not_exoneration')
                        continue
                    content = '\n\n'.join(quotes) + '\n\n### 平台原始展示\n' + raw
                    meta = {'tool': tool, 'target': company, 'query': company, 'target_person': person,
                            'person_subject_verified': True, 'person_record_quotes': quotes,
                            'identity_confidence': 'high', 'identity_reason': '平台返回人员名称及定位机构匹配',
                            'person_chapters': [7, 9, 12] if 'risk' in tool or tool in DETAIL.values() else [2, 6, 9],
                            'query_status': 'returned', 'retrieved_at': datetime.now().isoformat(timespec='seconds'),
                            'company_qcc_raw_response': payload}
                    if workflow._save_structured_source(db, project, 'qcc_executive', '人物任职关联与司法核查',
                            f'企查查-{tool}-{person}-{company}', content, meta, emit=emit, intake=intake):
                        added += 1
                        audit.record(tool, args, 'collected', 'source_statement_pending_review')
                    else:
                        audit.record(tool, args, 'validated_records', 'source_statement_pending_review')
        except Exception as exc:
            # Do not put exception URLs (which may contain credentials) into logs.
            audit.record('person_collection', {}, 'failed', type(exc).__name__)
            audit.finish_unqueried()

    if phase in {'identity', 'critical'}:
        return added
    key = os.getenv('XINIU_API_KEY', '').strip()
    xa = workflow._company_platform_audit(project, intake, company, 'xiniu', key)
    public_affiliation = primary_affiliation_basis(project, intake, company) if not identities.get(identity_key) else []
    xtasks = xiniu_plan(intake, company)
    xa.planned([t + (':' + a['aspect'] if a.get('aspect') else '') for t, a, _ in xtasks])
    remaining = user_time_remaining()
    if remaining is not None and remaining < 60:
        xa.stop_reason = 'user_time_budget_exhausted'
        xa.finish_unqueried()
    elif not key:
        xa.stop_reason = 'not_configured'
        xa.finish_unqueried()
    elif not identities.get(identity_key) and not public_affiliation:
        xa.stop_reason = 'identity_not_verified'
        xa.finish_unqueried()
    elif xtasks and not xa.cached_failure():
        base = os.getenv('XINIU_MCP_URL', 'https://vip.xiniudata.com/mcp').strip()
        xurl = base if 'api_key=' in base else base + ('&' if '?' in base else '?') + urlencode({'api_key': key})
        try:
            session, ok, error = xa.initialize(workflow._mcp_initialize, xurl, {}, timeout=timeout)
            if not ok:
                xa.result('initialize', {}, {'error': error})
                xa.stop_reason = xa.stop_reason or 'initialization_failed'
                xa.finish_unqueried()
            else:
                company_profile_missing = False
                for index, (tool, args, module) in enumerate(xtasks):
                    label = tool + (':' + args['aspect'] if args.get('aspect') else '')
                    if tool == 'get_company_info' and company_profile_missing:
                        xa.record(label,args,'not_queried','provider_entity_not_found')
                        continue
                    if not reserve('xiniu', tool, args, xa):
                        continue
                    payload, session = xa.call(workflow._mcp_call_tool, xurl, {}, tool, args, session=session, request_id=200+index, timeout=timeout)
                    retain_response(project, 'xiniu', label, payload, company)
                    if xa.result(label, args, payload):
                        break
                    if payload.get('error'):
                        if entity_not_found(payload):
                            company_profile_missing = tool == 'get_company_info'
                            xa.record(label,args,'failed','provider_entity_not_found')
                            continue
                        try:
                            from .company_platform import failure_kind
                        except ImportError:
                            from company_platform import failure_kind
                        # One retry only for a generic transport/service failure,
                        # charged to the SAME total budget. Never retry quota,
                        # auth, region or rate-limit failures in this loop.
                        if failure_kind(payload) == 'request_failed' and reserve('xiniu', tool, {**args, '_attempt': 2}, xa):
                            payload, session = xa.call(workflow._mcp_call_tool, xurl, {}, tool, args, session=session,
                                                       request_id=400+index, timeout=timeout)
                            retain_response(project, 'xiniu', label + ':retry', payload, company)
                            if xa.result(label, args, payload):
                                break
                    if payload.get('error'):
                        continue
                    if response_state(payload) == 'explicit_empty_record_list':
                        xa.record(label,args,'empty_result','explicit_empty_record_list')
                        continue
                    text = workflow._extract_mcp_text(payload)
                    if workflow._save_structured_source(db, project, 'xiniu', module, f'烯牛-{label}-{company}', text,
                            {'tool': tool, 'target': company, 'query': company, 'person_chapters': [4, 6, 11],
                             'affiliation_basis': 'public_primary_disclosure' if public_affiliation else 'qcc_returned_identity',
                             'affiliation_basis_sources': public_affiliation,
                             'query_status': 'returned'}, emit=emit, intake=intake):
                        added += 1
                        xa.record(label, args, 'collected', 'source_statement_pending_review')
        except Exception as exc:
            xa.record('person_collection', {}, 'failed', type(exc).__name__)
            xa.finish_unqueried()
    # TYC is opt-in fallback; company collectors retain their existing behavior.
    if os.getenv('PERSON_TYC_FALLBACK_ENABLED', 'false').lower() == 'true' and not any(
            r.get('provider') == 'qcc' and r.get('status') in {'returned', 'collected'}
            for r in getattr(project, 'person_platform_attempts', []) if r.get('subject') == company):
        added += workflow._collect_tyc_sources(db, project, company, intake, emit=emit)
    return added
