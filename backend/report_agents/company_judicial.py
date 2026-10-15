"""Chapter 9: observations, individual proceedings and scoped opinions stay separate."""
import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from .company_evidence import source_body, document_pages, pending_ocr_notice
from .company_governance import EID, get, refs, _table, compact
from .company_history import _issuer_hosts
from .company_management import issuer

VERSION='company-judicial-v1'
TITLE='企业司法负面核查'
DETAILS={'get_judicial_documents':'裁判文书','get_service_announcement':'劳动仲裁公告',
         'get_guarantee_info':'担保明细','get_stock_pledge_info':'股权质押明细'}
CASE=re.compile(r'[（(]\d{4}[）)][\w\u4e00-\u9fff]+?\d+号(?:之[一二三四五六七八九十\d]+)?')


def markdown_tables(text):
    header=None
    for line in text.splitlines():
        if not line.strip().startswith('|'):
            header=None
            continue
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        if all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in cells):continue
        if header is None:header=cells
        elif len(cells)==len(header):yield dict(zip(header,cells))


def names(value):
    try:
        parsed=json.loads(value)
        if isinstance(parsed,list):return [str(v) for v in parsed]
        if isinstance(parsed,dict):return [str(n) for v in parsed.values() for n in (v if isinstance(v,list) else [v])]
    except (ValueError,TypeError):pass
    return [v.strip() for v in re.split(r'[、;；]',str(value)) if v.strip()]


def row_quote(raw,row):
    wanted=list(row.values())
    return next((line for line in raw.splitlines() if line.strip().startswith('|') and
                 [v.strip() for v in line.strip().strip('|').split('|')]==wanted),'')


def stage(result):
    # A procedural decision does not establish substantive liability or collection.
    for label,pattern in [('撤诉/按撤诉处理（非实体胜败）','撤回起诉|撤诉'),
                          ('移送/管辖程序（非实体胜败）','移送|管辖'),
                          ('中止程序（非结案）','中止'),('调解记录（履行待核）','调解'),
                          ('驳回起诉（非实体请求裁判）','驳回.*起诉'),
                          ('实体请求被驳回（未证明履行）','驳回.*诉讼请求'),
                          ('执行程序（未证明执行完毕）','执行'),('裁判结果，终局及履行待核','判令|撤销|赔偿|支付')]:
        if re.search(pattern,result):return label
    return '程序/结果待核'


def _base(card,source,kind):
    eid=card['evidence_id']
    return {'kind':kind,'source_url':str(get(source,'url')),'source_title':str(get(source,'title')),
            'evidence_id':eid,'evidence_ids':[eid],'retrieved_at':str(get(source,'created_at') or
             (get(source,'source_metadata',{}) or {}).get('retrieved_at') or '查询时间未留存')}


def _structured(raw,tool,target,base,counts):
    rows=list(markdown_tables(raw));records=[]
    entity=next((r.get('值') for r in rows if r.get('字段')=='企业名称'),None)
    if compact(entity)!=compact(target):counts['structured_subject_unbound']+=1;return []
    if tool=='get_company_risk_scan':
        for r in rows:
            if not str(r.get('条目数','')).isdigit():continue
            n=int(r['条目数']);factor=r.get('风险因子','')
            records.append({**base,'kind':'scan','factor':factor,'count':n,'detail_tool':r.get('明细工具',''),
                            'fact':factor+'：接口计数'+str(n)+'条','evidence_quote':row_quote(raw,r),'coverage':'当前接口返回；非全历史、非去重案件数'})
        return records
    if tool=='get_administrative_penalty':
        # Provider prose contains unjustified assurances. Keep only the lookup observation.
        nohit=any(r.get('字段')=='摘要' and re.search(r'未(?:发现|查询到)|无相关记录',r.get('值','')) for r in rows)
        if nohit:return [{**base,'kind':'lookup','evidence_quote':next((row_quote(raw,r) for r in rows if r.get('字段')=='摘要'),''),
                          'fact':'行政处罚接口本次返回未发现相关记录；默认查询为当前在册有效记录，不能据此证明无历史处罚或经营良好。'}]
        return [{**base,'kind':'lookup','fact':'行政处罚接口已返回内容，尚需逐条绑定处罚决定书、受罚主体、日期和处罚内容。'}]
    if tool=='get_judicial_document_detail':
        fields={r['字段']:r.get('值','') for r in rows if '字段' in r}
        case=fields.get('案号','');parties=fields.get('当事人原文','')
        # The queried entity field alone never establishes who is a party.
        mapped=any(target in line and line.lstrip().startswith('- ') for line in raw.splitlines())
        if not case or not (target in parties or mapped):counts['unmatched_parties']+=1;return []
        result=fields.get('判决结果','待核')
        return [{**base,'kind':'case_detail','case_number':case,'fact':case+'；法院：'+fields.get('法院','待核')+
                 '；程序：'+fields.get('审理程序','待核')+'；裁判日期：'+fields.get('裁判日期','待核')+'；结果：'+result,
                 'evidence_quote':'\n'.join(row_quote(raw,r) for r in rows if r.get('字段') in {'案号','法院','审理程序','裁判日期','判决结果'}),
                 'mode':'数据库所载文书原文含完整主体名，仍待法院原件复核' if target in parties else '原文当事人匿名，仅由数据库映射到目标主体；法院原件身份仍待复核'}]
    for r in rows:
        row_base={**base,'evidence_quote':row_quote(raw,r)}
        if tool=='get_judicial_documents' and r.get('案号'):
            try:parties=json.loads(r.get('当事人','{}'))
            except (ValueError,TypeError):parties={}
            roles=[role for role,people in parties.items() if compact(target) in {compact(n) for n in names(json.dumps(people,ensure_ascii=False))}] if isinstance(parties,dict) else []
            if not roles:counts['unmatched_parties']+=1;continue
            result=r.get('裁判结果','待核')
            records.append({**row_base,'kind':'case','case_number':r['案号'],'role':'、'.join(roles),
                            'parties':r.get('当事人'),'date':r.get('裁判日期','待核'),
                            'stage':stage(result),'amount':r.get('案件金额') or '待核',
                            'document_id':r.get('文书ID',''),'result':result,
                            'fact':r['案号']+'；'+r.get('案由','')+'；'+result,
                            'mode':'数据库当事人映射；匿名原文需复核，非独立法院全文确认'})
        elif tool=='get_service_announcement' and r.get('案号'):
            roles=[role for role in ('申请人','被申请人') if target in names(r.get(role,''))]
            if not roles:counts['unmatched_parties']+=1;continue
            records.append({**row_base,'kind':'labour','case_number':r['案号'],'role':'、'.join(roles),
                            'date':r.get('发布日期','待核'),'parties':r,'stage':'劳动仲裁公告；结果/履行待核',
                            'fact':r['案号']+'；'+str(r),'amount':'未取得裁决金额'})
        elif tool in {'get_guarantee_info','get_stock_pledge_info'}:
            pledge=tool=='get_stock_pledge_info';left='质押人' if pledge else '担保方';right='质押人参股企业' if pledge else '被担保方'
            if left not in r:continue
            if target not in names(r.get(left,''))+names(r.get(right,'')):counts['unmatched_parties']+=1;continue
            records.append({**row_base,'kind':'pledge' if pledge else 'guarantee','date':r.get('公告日期','待核'),
                            'fields':r,'fact':'；'.join(k+'='+v for k,v in r.items()),
                            'mode':'数据库明细；数量/市值/担保金额分别保留，不合计为当前敞口'})
    return records


def litigation_rows(pages,base,period,counts):
    records=[];active=False;last_page=0;unit=''
    for p in pages:
        if p['page']>last_page+1:active=False
        for table in p.get('tables') or []:
            head=''.join(compact(c) for row in table[:3] for c in row if c)
            if all(s in head for s in ('涉案金额','预计负债','进展')):
                active=True
                units=set(re.findall(r'[（(](万元|千元|元)[）)]',head))
                unit=next(iter(units)) if len(units)==1 else ''
            if not active:continue
            for row in table:
                # PDF vector grids sometimes introduce entirely empty split cells.
                # Require all six semantic fields rather than infer absent columns.
                cells=[re.sub(r'\s+','',c or '') for c in row if compact(c)]
                if (len(cells)>=6 and re.fullmatch(r'\d[\d,]*(?:\.\d+)?',cells[1])
                        and cells[2] in {'是','否'} and unit
                        and re.search(r'诉讼|纠纷|仲裁|有限公司|有限责任公司',cells[0])
                        and re.search(r'执行|审理|状书|一审|二审|再审|调解|仲裁|诉讼|结案|撤诉|裁决|裁定|立案|开庭',cells[3])):
                    cutoffs=re.findall(r'截至\s*20\d{2}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日|\s*末)?',p['text'])
                    records.append({**base,'kind':'disclosed_case','period':period,'as_of':re.sub(r'\s+','',cutoffs[-1]) if cutoffs else '按文件报告期，具体事项时点见原文',
                                    'page':p['page'],'pages':[p['page']],
                                    'case_description':cells[0],'amount':cells[1]+unit,'provision':cells[2],
                                    'stage':cells[3],'result':cells[4],'execution':cells[5],
                                    'fact':'；'.join(cells[:6]),'mode':'发行人/律师专项文件列示，集团涉及方不等同母公司责任'})
                elif len(cells)==2 and records and p['page']==records[-1]['page']+1 and re.match(r'^["”）)]',cells[0]):
                    records[-1]['case_description']+=cells[0];records[-1]['result']+=cells[1]
                    records[-1]['fact']+='；跨页续文：'+'；'.join(cells);records[-1]['pages'].append(p['page'])
        last_page=p['page']
    if not records and any('涉案金额' in compact(p['text']) for p in pages):counts['unparsed_case_table']+=1
    return records


def court_record(raw,source,target,base):
    host=(urlparse(str(get(source,'url'))).hostname or '').lower()
    if not (host=='court.gov.cn' or host.endswith('.court.gov.cn')):return []
    roles=re.findall(r'(上诉人|被上诉人|原告|被告|申请执行人|被执行人)(?:[（(][^）)\n]{1,25}[）)])?[:：]\s*'+re.escape(target)+r'(?=[。；\s（(])',raw)
    if not roles:return []
    title_cases=CASE.findall(str(get(source,'title')));all_cases=set(CASE.findall(raw))
    if title_cases:case=title_cases[0]
    elif len(all_cases)==1:case=next(iter(all_cases))
    else:return []
    return [{**base,'kind':'court_identity','case_number':case,'role':'、'.join(dict.fromkeys(roles)),
             'fact':case+'；法院原页当事人字段：'+target+'，角色：'+'、'.join(dict.fromkeys(roles))+
             '；诉请、法院认定、裁判主文及后续程序尚需分段绑定，不从提及金额推定判赔或履行。'}]


def build_judicial_package(cleaned,target,sources=None,*,limit=240000,query_attempts=None):
    cards=defaultdict(list);counts=Counter();records=[];notes=[];coverage=[]
    for c in cleaned.get('facts') or []:
        if isinstance(c,dict) and EID.fullmatch(str(c.get('evidence_id') or '')):cards[str(c.get('source_url') or '')].append(c)
    hosts=_issuer_hosts(sources,target)
    for s in sources or []:
        raw,origin=source_body(s);meta=get(s,'source_metadata',{}) or {};url=str(get(s,'url'))
        usable=[c for c in cards[url] if c.get('eligible_for_report') is not False and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'}]
        if not usable:continue
        base=_base(usable[0],s,'judicial');tool=str(meta.get('tool') or '')
        if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:counts['subject_rejected']+=1;continue
        if origin=='discovery_summary':counts['summary_excluded']+=1;continue
        failed=meta.get('query_status') in {'failed','error','blocked','unauthorized','quota_exceeded'} or meta.get('error') or meta.get('fetch_status') in {'failed','invalid_pdf_response'}
        if failed:
            if tool:coverage.append({**base,'fact':tool+'调用未成功；无记录与失败分开。'})
            continue
        if tool in DETAILS or tool in {'get_company_risk_scan','get_administrative_penalty','get_judicial_document_detail'}:
            records+=_structured(raw,tool,target,base,counts)
            if re.search(r'已截取前|格式化存在字段截断',raw):counts['formatter_truncation']+=1
            tips=[r.get('值') for r in markdown_tables(raw) if r.get('字段') in {'摘要','提示'}]
            # Preserve coverage facts but never copy the provider's business assurances.
            safe=[t for t in tips if t and re.search(r'前\d+条|包含\d+条|累计共有\d+条|共有\d+条',t)]
            coverage.append({**base,'fact':tool+'：'+('；'.join(safe) if safe else '查询已返回，覆盖期及历史完整性未确认')})
            continue
        records+=court_record(raw,s,target,base)
        pages=document_pages(s)
        legal=('法律意见书' in compact(raw[:7000]) and compact(target) in compact(raw[:1600])
               and '律师事务所' in compact(raw[:1000]) and meta.get('entity_validation')!='rejected')
        if not (issuer(s,target,hosts) or legal):continue
        if not pages:continue
        period_match=re.search(r'20\d{2}\s*年[^\n]{0,10}(?:年度报告|半年度报告|超短期融资券)',raw[:4000])
        period=re.sub(r'\s+','',period_match[0]) if period_match else '文件时期待核'
        if legal:
            for review in meta.get('visual_reviews') or []:
                if (review.get('status')=='reviewed' and review.get('kind')=='document_signature_date'
                        and isinstance(review.get('page'),int) and re.fullmatch(r'20\d{2}-\d{2}-\d{2}',str(review.get('value') or ''))):
                    attempted=((meta.get('document_extraction') or {}).get('ocr') or {}).get('attempted_pages') or []
                    mode='原页图片人工核对' if review['page'] in attempted else '原页图片人工核对，未执行OCR'
                    notes.append({**base,'kind':'source_note','page':review['page'],'fact':'签章日期：'+review['value']+'（'+mode+'）'})
            definition=next((p for p in pages if re.search(r'报告期\s*指',p['text'])),None)
            if definition:
                m=re.search(r'报告期\s*指\s*([^\n]+)',definition['text'])
                if m:notes.append({**base,'kind':'source_note','page':definition['page'],'fact':'法律意见报告期定义：'+re.sub(r'\s+',' ',m[0])})
        records+=litigation_rows(pages,base,period,counts)
        for p in pages:
            text=re.sub(r'\s+','',p['text'])
            for m in re.finditer(r'截至20\d{2}年\d{1,2}月(?:末|\d{1,2}日)?[^。]{0,120}对外担保[^。]{0,150}余额合计[^。]{0,120}。',text):
                records.append({**base,'kind':'disclosed_exposure','page':p['page'],'period':period,'fact':m[0],
                                'mode':'原文件截至该日余额及合并范围，不代替当前敞口，不与平台条目加总'})
            # Only explicit issuer declarations. Eligibility lists, questions,
            # hypothetical risk clauses and unrelated parties are not violations.
            patterns=[r'(?:本报告期|公司报告期)[^。；]{0,35}(?:无重大诉讼、仲裁事项|不存在(?:重大)?处罚及整改情况|未发生破产重整相关事项)[。；]',
                      r'根据发行人的确认，并经本所律师适当核查，上述未决诉讼、仲裁对本次发行不构成实质性不利影响[。；]',
                      r'(?:发行人|上述境内主要子公司)近三年来无重大违法和重大违规行为，也未受到[^。]{0,120}重大行政处罚。',
                      r'报告期内，公司及公司的控股股东、实际控制人、董事、高级管理人员不存在被中国证监会采取行政监管措施和被证券交易所采取纪律处分的情况。',
                      r'经查询[^。]{0,400}不存在违法失信的情况。',
                      r'本案涉及的诉讼标的金额较小，该诉讼对本公司经营成果与财务状况不会产生重大不利影响。']
            for pattern in patterns:
                for m in re.finditer(pattern,text):records.append({**base,'kind':'declaration','page':p['page'],'period':period,'fact':m[0],
                                                                  'mode':'专项法律意见，按本次发行、列示主体、原报告期及重大性标准适用' if legal else '发行人本报告期披露，非独立全量核查'})
        extraction=meta.get('document_extraction') or {}
        for key in ('omitted_pages','needs_ocr_pages'):
            counts[key]+=len(extraction[key]) if isinstance(extraction.get(key),list) else int(extraction.get(key) or 0)
    # Keep separate decisions on the same case, including conflicting stages.
    unique=[];seen={}
    for r in records:
        key=(r['source_url'],r['kind'],r.get('fact'),r.get('date'),r.get('page'),r.get('document_id'))
        if key not in seen:
            r['row_occurrences']=1;unique.append(r);seen[key]=r
        else:
            seen[key]['row_occurrences']+=1;counts['identical_rows_folded']+=1
    selected=[];used=0
    for r in sorted(unique,key=lambda r:3 if r['kind'] in {'guarantee','pledge'} else 0):
        size=len(json.dumps(r,ensure_ascii=False))
        if used+size<=limit:selected.append(r);used+=size
        else:counts['budget_excluded']+=1
    gaps=['接口计数分别表示文书、立案、开庭等条目，不能相加为案件数；没有案号和程序衔接，不推定这些记录相互重复或均已结案。',
          '数据库默认查询与当前在册覆盖不能证明全历史无处罚、无失信或无重大风险；接口失败、权限/额度限制和零命中分别披露。',
          '撤诉、移送、调解、实体判决、执行及终结本次执行分开；未取得后续程序不能证明履行完毕，金额不明不等于零。',
          '涉案/诉请金额、判令支付、预计负债、已支付及执行回款分别核对；美元与人民币、万元与元不直接加总，未形成预计负债不等于没有风险。',
          '公司、子公司、股东和管理人员责任分别绑定；担保与质押是需要核对敞口的事项，不能仅凭条目数判断违法或正常融资。',
          '司法记录以外的产品召回、行政监管措施、纪律处分、负面报道与供应链争议需按各自原件核查，问询或注册终止不自动等同处罚。']
    if counts['needs_ocr_pages']:gaps.append(pending_ocr_notice(sources,'存在低文字页尚未执行OCR；不将文字提取当扫描识别，不以未识别到内容证明无风险。'))
    if counts['omitted_pages']:gaps.append('部分原件尚未提取全文，未检出不等于未披露。')
    if counts['budget_excluded']:gaps.append('部分明细超出本章证据预算，不能据此概括全量结果。')
    if counts['formatter_truncation']:gaps.append('专业平台内容存在格式化行/字段截断，需回已保存的原始返回核对，不能声称已核完全部明细。')
    if any(r['kind']=='pledge' and '解除' in r['fields'].get('状态','') for r in selected):gaps.append('质押工具虽以当前生效为默认语义，返回明细包含已解除状态；需按原公告核对各笔最新状态，不能把全部计数视为仍在押。')
    if any(r['kind']=='guarantee' and r['fields'].get('履行状态')=='待查' for r in selected):gaps.append('已得担保明细仍有履行状态待查，未形成可核对的当前担保余额、到期、代偿及反担保有效性，不据此判为持续存续或无实质风险。')
    if not any(r['kind']=='case' for r in selected):gaps.append('尚无绑定完整当事人和案号的母公司具体裁判记录；风险扫描不能替代案件明细。')
    return {'version':VERSION,'target_name':target,'facts':selected,'source_notes':notes,'coverage':coverage,'query_attempts':query_attempts or [],
            'information_gaps':gaps,'diagnostic':{'candidate_claims':len(unique),'delivered_claims':len(selected),
            'by_kind':dict(Counter(r['kind'] for r in selected)),'filters':dict(counts)}}


def render_judicial(p):
    f=p['facts'];lines=['## 9. '+TITLE,'','### 查询覆盖与计数边界','']
    for attempt in p.get('query_attempts') or []:
        if attempt.get('status')=='failed':lines+=['- 专业平台调用未成功：'+attempt.get('tool','风险接口')+'；不计为无记录，需补齐查询。']
    for c in p['coverage']:lines+=['- '+c['fact']+'；'+c['retrieved_at']+' '+refs(c)]
    scans=[r for r in f if r['kind']=='scan']
    if scans:lines+=_table(['扫描因子','接口条目数','明细工具与证据'],[[r['factor'],str(r['count']),r['detail_tool']+'；'+refs(r)] for r in scans])
    for r in f:
        if r['kind']=='lookup':lines+=['- '+r['fact']+' '+refs(r)]
    lines+=['','计数是查询线索；本章不将零命中扩写为历史清白，也不从有记录推定违法或重大业务影响。',
            '','### 具体司法与劳动仲裁记录','']
    cases=[r for r in f if r['kind'] in {'case','labour'}]
    judgments=[r for r in cases if r['kind']=='case']
    if judgments:lines+=['本章保留'+str(len(judgments))+'条裁判列表记录，涉及'+str(len({r['case_number'] for r in judgments}))+'个完整案号编号；同案不同文书/日期/程序分别保留，“之一”等补充文书未擅自并案，这不是全量独立案件数。','']
    if cases:lines+=_table(['案号/文书日期','主体角色与数据性质','程序/结果','金额与出处'],[
        [r['case_number']+'；'+r['date'],r['role']+'；'+r.get('mode','仲裁公告，非裁决'),r['stage']+'；'+r.get('result','公告未提供裁决结果'),r['amount']+'；'+refs(r)] for r in cases])
    else:lines+=['尚未形成可绑定案号与当事人角色的具体记录，不能由风险汇总推定胜败、结案和责任。']
    for r in f:
        if r['kind']=='case_detail':lines+=['- 文书分段核验：'+r['fact']+'（'+r['mode']+'） '+refs(r)]
        if r['kind']=='court_identity':lines+=['- '+r['fact']+' '+refs(r)]
    lines+=['','### 发行人及专项法律文件列示事项','']
    disclosed=[r for r in f if r['kind']=='disclosed_case']
    if disclosed:lines+=_table(['文件期/集团涉及方','涉案金额/预计负债','程序与裁判结果','执行情况/原页'],[
        [r['period']+'；'+r['as_of']+'；'+r['case_description'],r['amount']+'；预计负债：'+r['provision'],r['stage']+'；'+r['result'],r['execution']+'；'+refs(r)+'（物理页'+','.join(map(str,r['pages']))+'）'] for r in disclosed])
    for r in disclosed:
        if '暂无财产可供执行' in r['execution']:
            lines+=['- 回款核验重点：'+r['execution']+'；需按该案的受偿方与付款方核对后续资产线索、实际回款及债权减值，不能将追偿方归作为被执行失信主体。 '+refs(r)+f"（物理页{r['page']}）"]
    for r in f:
        if r['kind']=='declaration':lines+=['- '+r['period']+'原文声明：'+r['fact']+'（'+r['mode']+'） '+refs(r)+f"（物理页{r['page']}）"]
    for r in p['source_notes']:lines+=['- '+r['fact']+' '+refs(r)+f"（物理页{r['page']}）"]
    lines+=['','不同文件时期、重大性标准和集团范围分别保留。旧期律师对某次融资的意见不覆盖全部接口记录；本期无重大诉讼的自报也不抹去其他诉讼及执行事项。',
            '','### 担保、质押与业务敞口','']
    for r in f:
        if r['kind']=='disclosed_exposure':lines+=['- '+r['period']+'原文余额：'+r['fact']+'（'+r['mode']+'） '+refs(r)+f"（物理页{r['page']}）"]
    for kind,title in [('guarantee','担保'),('pledge','股权质押')]:
        group=[r for r in f if r['kind']==kind];shown=sorted(group,key=lambda r:r['date'],reverse=True)[:8]
        if shown:
            lines+=['- '+title+'：本章证据包保留'+str(sum(r['row_occurrences'] for r in group))+'行明细，下表按公告日期展示前'+str(len(shown))+'组字段；相同字段行折叠展示，不证明属于同一笔义务，未将公示笔数或历史解除记录合计为当前余额。']
            lines+=_table(['公告日期','原始字段与状态','相同字段行数/证据'],[[r['date'],r['fact'],str(r['row_occurrences'])+'；'+refs(r)] for r in shown])
        else:lines+=['- '+title+'具体方向、对手方、当前状态和金额尚未绑定明细，不能直接判为正常或异常。']
    lines+=['','### 核验判断与待补事项','']+['- '+g for g in p['information_gaps']]
    return '\n'.join(lines)


def judicial_errors(text,p):
    errors=[]
    if text.strip()!=render_judicial(p).strip():errors.append('第九章存在未受原始司法证据支持的改写')
    if not p['facts']:errors.append('第九章尚无可核对记录')
    allowed={r['evidence_id'] for key in ('facts','source_notes','coverage') for r in p[key]}
    if set(EID.findall(text))-allowed:errors.append('第九章存在未知证据编号')
    return errors
