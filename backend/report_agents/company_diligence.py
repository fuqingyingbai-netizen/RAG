"""Chapter 10: evidence-led work orders, with separate entities and money bases."""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from urllib.parse import urlparse

from opencc import OpenCC

from .company_evidence import source_body, document_pages, pending_ocr_notice
from .company_governance import EID, get, refs, _table, _cell, cited_evidence_ids
from .company_history import _issuer_hosts
from .company_financial_statements import fiscal_report_period,quarter_report_period

VERSION='company-diligence-v2-cross-chapter-display'
TITLE='定向穿透专项尽职调查'
_CC=OpenCC('t2s')
LEGAL=r'[\u4e00-\u9fffA-Za-z（）()·]{2,55}(?:股份有限公司|有限责任公司|有限公司)'
TRUSTED=('hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn')
STREAMS=('融资情况','资金使用合规性','战略布局','业务真实性','大额资金往来','委托方指定事项')


def folded(text):
    """Script equality is a candidate match, never proof of common ownership."""
    return re.sub(r'\s+','',_CC.convert(unicodedata.normalize('NFKC',str(text or '')))).lower()


def host_of(source):return (urlparse(str(get(source,'url'))).hostname or '').lower().removeprefix('www.')


def exchange(source):return any(host_of(source)==d or host_of(source).endswith('.'+d) for d in TRUSTED)


def period_of(source,pages):
    text='\n'.join(str(p['text']) for p in pages[:4])+'\n'+str(get(source,'title'))
    m=re.search(r'(20\d{2})\s*年\s*(?:年度|半年度|中期)报告',_CC.convert(text))
    if m:return m[0].replace(' ','')
    fiscal=fiscal_report_period(text)
    if fiscal:return fiscal['period']
    quarter=quarter_report_period(str(get(source,'content') or text))
    if quarter:return quarter['period']
    m=re.search(r'(?:ANNUAL\s+REPORT|REPORT\s+AND\s+ACCOUNTS)\s*(20\d{2})',text,re.I)
    if m:return m[1]+'年度报告'
    m=re.search(r'\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2})\b',text)
    if m:return m[1]
    m=re.search(r'(20\d{2})\s*年\s*第\s*\d+\s*期',text)
    return m[1]+'年通讯' if m else '文件时期尚未绑定'


def scoped_government_pages(source,target):
    """A multi-company circular is divided at numbered case boundaries."""
    h=host_of(source)
    if not (h.endswith('.gov.cn') or h=='gov.cn'):return []
    pages=document_pages(source)
    blocks=[];current=[]
    for page in pages:
        pieces=re.split(r'(?m)(?=^[一二三四五六七八九十]+、[^\n]{2,90})',page['text'])
        for i,piece in enumerate(pieces):
            if not piece.strip():continue
            if re.match(r'^[一二三四五六七八九十]+、',piece):
                if current:blocks.append(current)
                current=[]
            current.append({'page':page['page'],'text':piece})
    if current:blocks.append(current)
    selected=[]
    for block in blocks:
        body=''.join(folded(p['text']) for p in block)
        # A contents page or a mere co-mention does not establish a case subject.
        subject=bool(re.search(re.escape(folded(target))+r'\(以下简称',body))
        title=re.search(r'^[一二三四五六七八九十]+、([^\n]+)',block[0]['text'])
        definition=re.search(re.escape(folded(target))+r'\(以下简称([^)]{1,60})\)',body)
        aliases=[folded(target)]
        if definition:aliases+=re.split(r'或|、|,|和',definition[1])
        titled=bool(title and any(a not in {'公司','集团',''} and folded(title[1]).startswith(a) for a in aliases))
        if subject and titled and not all('目录' in p['text'] or '...' in p['text'] for p in block):selected+=block
    return selected


def issuer_heading(pages,name):
    from .company_financial_statements import quarter_report_period
    if quarter_report_period('\n'.join(p['text'] for p in pages[:8]),name):return True
    for p in pages[:8]:
        for line in p['text'].splitlines():
            value=folded(line)
            if value==folded(name):return True
            stripped=re.sub(r'20\d{2}|年度报告|年报|annualreport|[•·|:：]','',value)
            if stripped==folded(name):return True
            if re.match(r'^'+re.escape(folded(name))+r'20\d{2}年(?:年度|半年度)报告',value):return True
            # Another issuer's own heading takes precedence over a target
            # mentioned later in a shareholder/customer table or appendix.
            owner=re.fullmatch(r'([\u4e00-\u9fffA-Za-z0-9()·]{2,70}(?:股份有限公司|有限责任公司|有限公司))[^\u4e00-\u9fffA-Za-z0-9]{0,3}',stripped)
            if owner:return owner[1]==folded(name)
    return False


def english_aliases(pages,name):
    text='\n'.join(p['text'] for p in pages[:8]);aliases=[]
    for m in re.finditer(r'(?im)^([A-Z][A-Za-z&.,() /-]{3,100}?(?:Company\s+Limited|Co\.,?\s*Ltd\.?|Limited|Corporation|Inc\.))\s*(?=\n|[（(“"])',text):
        before=text[max(0,m.start()-180):m.start()];after=text[m.end():m.end()+160]
        if folded(name) in folded(before) or re.match(r'\s*[（(]?[“"].{0,100}(?:Company|公司)',after,re.S):aliases.append(m[1].strip())
    return sorted(set(aliases))


def _base(card,source,owner,period):
    eid=card['evidence_id']
    return {'source_url':str(get(source,'url')),'source_title':str(get(source,'title')),
            'evidence_id':eid,'evidence_ids':[eid],'entity':owner,'period':period}


def diligence_discovery_queries(sources,target,seen=None):
    """Plan bounded searches from retrieved relationship proofs, not summaries.

    PLANONLY anchors are transient registry keys before the evidence ledger
    exists. They never leave this function as claims, citations or evidence.
    """
    seen=seen if seen is not None else set()
    if len(seen)>=3:return []
    anchors={'facts':[{'source_url':str(get(s,'url')),'evidence_id':'E-PLANONLY'} for s in sources]}
    registry,admitted=identity_registry(anchors,target,sources)
    queries=[]
    for entry in registry.values():
        key=folded(entry['name'])
        if not entry['links'] or key in seen:continue
        # Once current issuer reports and a transaction circular are both
        # present, another generic search adds no demonstrated coverage.
        owned=[(s,base) for s,_p,base in admitted if base['entity']==entry['name']]
        has_report=any('报告' in b['period'] for s,b in owned)
        has_transaction=any(re.search(r'circular|通函|收购公告',str(get(s,'title')),re.I) for s,b in owned)
        if has_report and has_transaction:continue
        seen.add(key)
        common={'module':TITLE,'search_tier':'authority_first','evidence_scope':'related_entity_context',
                'diligence_entity':entry['name'],'diligence_relationship_source':entry['links'][0]['source_url'],
                'include_domains':['hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn']}
        if not has_report:queries.append({**common,'query':'"'+entry['name']+'" 年度报告 关联方贷款 商誉 减值 融资资金用途'})
        if not has_transaction:queries.append({**common,'query':'"'+entry['name']+'" 收购 通函 交割 对价调整 贷款 付款机制'})
        if len(seen)>=3:break
    return queries


def identity_registry(cleaned,target,sources):
    cards=defaultdict(list)
    for c in cleaned.get('facts') or []:
        if isinstance(c,dict) and EID.fullmatch(str(c.get('evidence_id') or '')):cards[str(c.get('source_url') or '')].append(c)
    roots={folded(target):{'name':target,'aliases':[],'links':[],'hosts':set()}};admitted=[]
    issuer_hosts=_issuer_hosts(sources,target)
    for source in sources:
        raw,origin=source_body(source);cs=cards[str(get(source,'url'))]
        if not cs or origin=='discovery_summary':continue
        meta=get(source,'source_metadata',{}) or {}
        if meta.get('fetch_status') in {'failed','invalid_pdf_response','blocked_or_challenge','fetch_timeout'}:continue
        pages=document_pages(source)
        if not pages:continue
        direct=(exchange(source) or host_of(source) in issuer_hosts) and issuer_heading(pages,target)
        selected=pages if direct else scoped_government_pages(source,target)
        if not selected:continue
        base=_base(cs[0],source,target,period_of(source,pages));admitted.append((source,selected,base))
        if direct:roots[folded(target)]['aliases']+=english_aliases(pages,target)
        for page in selected:
            text=_CC.convert(page['text'])
            if re.search(r'简单示例|仅为示例|假设.{0,20}(?:架构|结构)|示例.{0,20}(?:架构|结构)',text):continue
            for m in re.finditer(r'(?:控股子公司|全资子公司|子公司|附属公司)(?:为|是|包括)?\s*('+LEGAL+r')',text):
                child=m[1]
                if re.search(r'根据|注册成立|成立于|简称|依据|以下|上述|通过',child):continue
                prefix=re.sub(r'\s+','',re.split(r'[。；]',text[:m.start()])[-1])
                if re.search(r'控股股东|实际控制人|交易对方|卖方|标的公司|目标公司',prefix):continue
                parent_context=(re.search(r'(?:本公司|本集团|'+re.escape(target)+r')[^。；]{0,30}$',prefix)
                                or re.search(r'其[^。；]{0,30}(?:业务|通过|拥有|旗下)[^。；]{0,15}$',prefix)
                                or (not re.search(r'公司|集团',prefix) and re.fullmatch(r'.{2,20}业务(?:主要)?通过',prefix)))
                if not parent_context:continue
                if folded(child)==folded(target):continue
                key=folded(child);roots.setdefault(key,{'name':child,'aliases':[],'links':[],'hosts':set()})
                # The parent is authenticated by issuer document ownership or
                # an explicit full-name case subject, never by a search title.
                roots[key]['links'].append({**base,'kind':'relationship','page':page['page'],
                    'fact':'文档主体'+target+'；'+m[0],'evidence_quote':m[0], 'child':child})
    # Authenticate related issuers on an exchange before using an English-only
    # circular. Merely mentioning a subsidiary in the body does not own it.
    for source in sources:
        raw,origin=source_body(source);pages=document_pages(source)
        if not exchange(source) or origin=='discovery_summary' or not cards[str(get(source,'url'))]:continue
        if (get(source,'source_metadata',{}) or {}).get('fetch_status') in {'failed','invalid_pdf_response','blocked_or_challenge','fetch_timeout'}:continue
        for entry in roots.values():
            if entry['name']==target or not entry['links'] or not issuer_heading(pages,entry['name']):continue
            entry['aliases']+=english_aliases(pages,entry['name'])
            cover='\n'.join(p['text'] for p in pages[:8])
            entry['hosts'].update((urlparse(u if u.startswith('http') else 'https://'+u).hostname or '').removeprefix('www.').lower()
                                  for u in re.findall(r'(?:https?://|www\.)[A-Za-z0-9./_-]+',cover))
    seen={str(get(s,'url')) for s,_p,_b in admitted}
    for source in sources:
        url=str(get(source,'url'));raw,origin=source_body(source);pages=document_pages(source)
        if url in seen or not cards[url] or origin=='discovery_summary' or not pages:continue
        if (get(source,'source_metadata',{}) or {}).get('fetch_status') in {'failed','invalid_pdf_response','blocked_or_challenge','fetch_timeout'}:continue
        cover='\n'.join(p['text'] for p in pages[:8]);short='\n'.join(p['text'] for p in pages[:2])
        for entry in roots.values():
            if entry['name']==target or not entry['links']:continue
            if not (exchange(source) or host_of(source) in entry['hosts']):continue
            owned=issuer_heading(pages,entry['name'])
            for alias in entry['aliases']:
                # An English-only circular explicitly addresses shareholders
                # of the named issuer. An acquisition target in prose fails.
                if re.search(r'shares\s+in\s+'+re.escape(alias),short,re.I):owned=True
                if any(folded(line)==folded(alias) for line in cover.splitlines()):owned=True
            if owned:
                admitted.append((source,pages,_base(cards[url][0],source,entry['name'],period_of(source,pages))))
                seen.add(url);break
    return roots,admitted


def money_rows(page,base):
    """Only a single value column and an explicit currency/unit are read."""
    raw=page['text']
    if re.search(r'unaudited\s+pro\s+forma|ACCOUNTANTS[’\']?\s+REPORT\s+OF\s+THE\s+TARGET\s+GROUP',raw,re.I):return []
    currencies=set(re.findall(r'(RMB|US\$|USD|HK\$|HKD)[’\']000',raw))
    if len(currencies)!=1:return []
    currency=next(iter(currencies));unit={'RMB':'人民币千元','US$':'美元千元','USD':'美元千元','HK$':'港元千元','HKD':'港元千元'}[currency]
    labels={'Total identifiable net assets at fair value':'acquired_net_assets','Goodwill on acquisition':'goodwill',
            'Satisfied by cash':'accounting_consideration','Cash consideration not paid yet':'unpaid_consideration',
            'Cash consideration':'accounting_consideration','Cash and bank balances acquired':'acquired_cash',
            'Net outflow of cash and cash equivalents included in cash flows from investing activities':'acquisition_net_outflow'}
    rows=[]
    for label,kind in labels.items():
        pattern=re.escape(label)+r'\*?[^\dA-Za-z]*?(?:\d{1,2}\s+)?((?:\(\d+(?:,\d{3})*(?:\.\d+)?\)|\d+(?:,\d{3})*(?:\.\d+)?))\s*$'
        matches=list(re.finditer(pattern,raw,re.M))
        for m in matches:
            # Another year/value column would prevent this exact row match.
            rows.append({**base,'kind':kind,'stream':'大额资金往来','page':page['page'],'value':m[1],
                         'unit':unit,'metric':label,'fact':label+'：'+m[1]+' '+unit,
                         'evidence_quote':m[0],'mode':'原表会计计量，非实际提款/银行付款证明',
                         'negotiation_note':'原页注明最终现金对价仍在协商，不能当作当前已最终确定' if re.search(r'final cash consideration is still under negotiation',raw,re.I) else ''})
    return rows


def _sentences(text):
    # Preserve paragraphs/units; line wrapping is not a sentence boundary.
    clean=re.sub(r'(?m)^\d+\s*$','',text).replace('\r','')
    clean=re.sub(r'\b(Pte|Ltd|Co|Inc|Mr|Mrs|Dr)\.',lambda m:m[1]+'\u2024',clean)
    clean=re.sub(r'(?m)^\s*\([a-z]\)\s*(?=[A-Z])','\n\n',clean)
    clean=re.sub(r'(?m)^(?=[A-Z][^\n]{2,100}a (?:wholly-owned|majority-owned) subsidiary)','\n\n',clean)
    clean=re.sub(r'(?m)^\s*(?:\d+\s+)?(?=On\s+\d{1,2}\s+[A-Z][a-z]+\s+20\d{2}|截至\s*20\d{2})','\n\n',clean)
    clean=re.sub(r'(?<!\n)\n(?!\n)',' ',clean)
    return [re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])','',re.sub(r'\s+',' ',s)).replace('\u2024','.').strip() for s in re.split(r'\n{2,}|(?<=[。；])|(?<=[.!?])\s+(?=[A-Z])',clean) if s.strip()]


def classify_quote(quote):
    t=_CC.convert(quote);low=t.lower()
    from .company_history import accounting_background
    if accounting_background(t):return None
    if re.search(r'如果|若|不时进行企业合并|可能.{0,100}完成|完成.{0,50}可能',low):return None
    if re.search(r'(?:从|自).{0,35}控制权之日起|when.{0,20}control.{0,20}obtained',low):return None
    if re.search(r'unaudited pro forma|for the purpose of.*pro forma|备考|假设.{0,25}(?:交易|收购|完成|已发生)',low):return 'pro_forma','大额资金往来','备考假设/模拟影响，非实际提款或付款'
    if re.search(r'未付|not paid yet',low) or (re.search(r'未使用',low) and re.search(r'募集|配售|融资款|所得款项',low)):return 'payment_pending','大额资金往来','未付/未使用，不能写成已全部支付'
    if re.search(r'(?:采用|拟)?发行股份.{0,30}募集配套资金|拟发行债券',low):return 'financing_plan','融资情况','融资/交易方案披露；完成、到账和实际用途另行核验'
    if re.search(r'完成[^，。；:：]{0,25}(?:配售|发行)|配售完成后[^。；]{0,150}(?:股份总数|股本总额)|配售[^。；]{0,80}净额|已使用.*(?:配售|募集)|used.*net proceeds',low):
        if not re.search(r'已使用|used',low) and re.search(r'提名权|权利|股东的意向|发行完成前|发行完成时|发行完成后',low):return None
        if re.search(r'坚定看好|顶级|全球[^。；]{0,30}最大|充分体现|这份认可|期许',low):return None
        return 'fund_use' if re.search(r'已使用|used',low) else 'financing','融资情况','公司融资及资金使用披露，非银行流水独立核验'
    if re.search(r'loan|entrusted loan|借款|股东贷款|委托贷款',low):return 'related_funding','大额资金往来','主体/额度/余额/提款和用途分开；未自动归入本次收购'
    if re.search(r'(?:since|from).{0,35}acquisition.{0,160}(?:revenue|profit)|收购完成后.{0,80}(?:实现|营业收入)|标的公司.{0,50}实现净利润',low):return 'acquired_contribution','业务真实性','集团并购后表现与标的贡献分别保留；统计期按原文，不归因全部增长或机械年化'
    if re.search(r'本次(?:交易|收购).{0,60}不形成商誉',low):return 'accounting_treatment','业务真实性','原文仅针对本次交易的会计处理，非公司全部历史商誉为零'
    if re.search(r'goodwill|商誉|可辨认净资产|identifiable net assets',low):return 'purchase_accounting','业务真实性','会计确认/估值与减值口径，非现金已支付证明'
    if re.search(r'closing took place|completed.*acquisit|acquisition has been completed|完成.*(?:收购|交割)',low):return 'closing','业务真实性','交割/完成披露，不单独证明协同实现或资金合规'
    if re.search(r'(?:cash|purchase|final|aggregate|total|the|adjusted|acquisition)\s+consideration\b|consideration\s+(?:of|shall|will|paid|was|is)|交易对价|交易价格|现金对价|支付现金购买资产',low):return 'consideration','大额资金往来','协议基准、调整后对价与净现金流分别核对'
    if re.search(r'评估基准|评估值',low):return 'valuation','业务真实性','评估基准日、账面价值与评估值，非交易实付或收益已实现'
    if re.search(r'financial information of the target group.{0,60}(?:will be|was|is) included in.{0,60}consolidated financial|(?:纳入|进入)合并(?:报表|范围)',low):return 'consolidation','业务真实性','原文合并口径，母公司单体和集团分开'
    if re.search(r'excluded business was not included in',low):return 'business_perimeter','业务真实性','标的历史财务信息的排除业务范围，不当作本次取得的全部资产或集团业务'
    if re.search(r'(?:will|would).{0,100}(?:improve|enhance|expand|strengthen)|有助于|将有利于|旨在',low):return 'strategy','战略布局','预期/计划，非完成或效果证明'
    return None


def disclosure_rows(source,pages,base):
    rows=[]
    for page in pages:
        raw=page['text'];text=_CC.convert(raw)
        rows+=money_rows(page,base)
        if re.search(r'重要会计政策|会计政策及会计估计|SUMMARY\s+OF\s+(?:SIGNIFICANT|MATERIAL)\s+ACCOUNTING\s+POLICIES',text,re.I):continue
        # Fund use disclosures usually wrap across several lines and bullets.
        for m in re.finditer(r'截至\s*20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日[，,]\s*本集团已使用[^。]{10,650}',text):
            quote=re.sub(r'\s+',' ',re.split(r'\n\s*\d+[、.．]',m[0])[0]).strip()
            if re.search(r'配售|募集',quote):rows.append({**base,'kind':'fund_use','stream':'融资情况','page':page['page'],'fact':quote,'evidence_quote':quote,
                'mode':'公司截至原日资金使用披露；内部用途不等于外部付款穿透'})
        for quote in _sentences(raw):
            if not 20<=len(quote)<=1500:continue
            if re.search(r'please refer|详情请见|具体请参见',quote,re.I):continue
            if not re.search(r'\d|完成|收购|合并|acquisit|consid|loan|goodwill',quote,re.I):continue
            # Legal policies, mandates and general risks are not actual events.
            if re.search(r'如发生|应当|有权|董事获授权|授权.*发行|shall be recognised|when.*acquir|accounting policy|accounting policies|policy to account|depending on whether|contingent liabilities in case',quote,re.I):continue
            category=classify_quote(quote)
            if not category:continue
            kind,stream,mode=category
            if kind=='financing' and not re.search(r'本公司|本集团|我们|(?:日|[，,；。:：\s])公司(?:完成|已完成|发行|配售)|'+re.escape(base.get('entity') or '\x00')+r'|\b(?:the company|our company|we)\b',_CC.convert(quote),re.I):continue
            if kind=='consolidation' and re.search(r'详见|见附注',quote):continue
            if kind=='consolidation' and re.search(r'该公司|该子公司',quote):continue # bind the controlled entity on its native row first
            if kind in {'strategy','closing','consideration','purchase_accounting','consolidation'} and not re.search(r'[。.!?；]$',quote):continue
            if len(re.findall(r'\d[\d,.]*',quote))>18:continue
            if kind=='payment_pending':
                if re.search(r'Cash consideration not paid yet',quote,re.I):continue # explicit table fields above
                date_start=re.search(r'(?:于|截至)\s*20\d{2}\s*年',quote)
                if date_start:quote=quote[date_start.start():]
                mode+='；到期未付需先核对披露原因及后续兑付，不直接等同违约'
            if kind=='fund_use' and re.search(r'募集\s*年份|募集资金总体使用情况|募集资金承诺项目',_CC.convert(quote)):continue
            if kind=='fund_use' and re.search(r'截至\s*20\d{2}.+本集团已使用',quote):continue # complete bullet paragraph retained above
            if kind=='strategy' and not re.search(r'收购|并购|acquisit|投资|investment',quote,re.I):continue
            if kind=='related_funding' and not re.search(r'obtained|provided|outstanding.{0,30}loan|from.{0,50}holding|shareholder|股东贷款|借款(?:本金|金额|余额)|委托贷款',quote,re.I):continue
            if kind=='related_funding' and len(re.findall(r'\d[\d,.]*',quote))>12:continue
            if kind in {'related_funding','pro_forma','consideration'} and not re.search(r'(?:RMB|US\$|USD|HK\$|人民币|港元).{0,30}\d|\d[\d,.]*\s*(?:亿元|万元|百万元|美元)',quote,re.I):continue
            if kind=='consideration' and not re.search(r'acquisit|purchas|seller|target|收购|并购|购买资产|交易对价|交易价格|现金对价',quote,re.I):continue
            if kind=='purchase_accounting' and not re.search(r'acquisit|business combination|impairment|收购|并购|商誉减值',quote,re.I):continue
            if kind=='purchase_accounting' and not re.search(r'(?:RMB|US\$|USD|HK\$|人民币|港元).{0,35}\d|\d[\d,.]*\s*(?:亿元|万元|千元|百万元|%)',quote,re.I):continue
            if kind=='purchase_accounting' and re.search(r'ACCOUNTANTS[’\']?\s+REPORT\s+OF\s+THE\s+TARGET\s+GROUP',raw,re.I):continue # historical target goodwill is not new purchase accounting
            if re.search(r'unaudited pro forma',raw,re.I) and kind in {'related_funding','consideration','purchase_accounting','pro_forma'}:
                kind,stream,mode='pro_forma','大额资金往来','原页备考假设/模拟影响，非实际提款、付款或原交易最终计量'
            rows.append({**base,'kind':kind,'stream':stream,'page':page['page'],'fact':quote,'evidence_quote':quote,'mode':mode,
                         'stage_note':'含未来/条件措辞，按原文不能等同完成' if re.search(r'\bwill\b|\bshall\b|subject to|拟|尚未|预计',quote,re.I) else ''})
    return rows


def _cash_checks(records):
    groups=defaultdict(lambda:defaultdict(list))
    for r in records:
        if r.get('value'):groups[(r['source_url'],r['page'],r['entity'],r['unit'])][r['kind']].append(r)
    checks=[]
    for values in groups.values():
        keys=('accounting_consideration','unpaid_consideration','acquired_cash','acquisition_net_outflow')
        if not all(k in values for k in keys):continue
        if any(len(values[k])!=1 for k in keys):continue # multiple tables/transactions are not joined by page alone
        values={k:v[0] for k,v in values.items()}
        def number(r):return Decimal(r['value'].replace(',','').replace('(','-').replace(')',''))
        observed=[number(values[k]) for k in keys]
        checks.append({'entity':values[keys[0]]['entity'],'source_url':values[keys[0]]['source_url'],
                       'evidence_ids':values[keys[0]]['evidence_ids'],
                       'page':values[keys[0]]['page'],'unit':values[keys[0]]['unit'],
                       'equation':' + '.join(str(n) for n in observed[:3])+' = '+str(observed[3]),
                       'matched':sum(observed[:3])==observed[3],'scope':'同原页同币种单位的披露勾稽，非银行收付认证'})
    return checks


def select_rows(rows,quota):
    def date_key(r):
        period=str(r.get('period') or r.get('date') or '')
        asof=str(r.get('as_of') or '')
        text=asof if re.search(r'20\d{2}',asof) else period
        year=re.search(r'20\d{2}',text)
        month=re.search(r'20\d{2}(?:年\s*|-)(\d{1,2})(?:月|-)',text)
        rank=int(month[1]) if month else (6 if '半年度' in text or '中期' in text else 12 if re.search(r'年度报告|annual report',text,re.I) else 0)
        return (int(year[0]) if year else 0,rank,r.get('page',0))
    ordered=sorted(rows,key=date_key,reverse=True);result=[];seen=set()
    def add(r):
        key=(r.get('entity'),r.get('period'),r['kind'],folded(r['fact']))
        if key in seen or len(result)>=quota:return
        result.append(r);seen.add(key)
    kinds=('fund_use','financing','financing_use_plan','financing_plan','goodwill_impairment_loss','related_funding','accounting_consideration','unpaid_consideration',
           'acquired_cash','acquisition_net_outflow','goodwill','acquired_net_assets','consideration',
           'pro_forma','closing','strategy','acquired_contribution','valuation','accounting_treatment','purchase_accounting','consolidation','execution_followup','encumbrance_followup')
    for kind in kinds:
        candidates=[r for r in ordered if r['kind']==kind]
        if kind=='pro_forma':candidates.sort(key=lambda r:bool(re.search(r'loan|贷款',r['fact'],re.I)),reverse=True)
        match=next(iter(candidates),None)
        if match:add(match)
    for r in ordered:add(r)
    return result


TASK_ACTIONS={
 '融资情况':('核对融资到账、承诺用途与实际使用，区分余额、用途说明和银行凭证。','发行/配售文件、用途变更决议、分项支出台账及抽样付款/到账凭证','金额及用途能与同期间资金台账和原币种对账，差异有原件解释'),
 '资金使用合规性':('按具体融资/付款事项核对账户、授权、关联方、合同与业务背景；不由公开未检出直接认定合规。','授权与合同、收付款台账、银行原始凭证、关联方/受益所有人材料','交易主体、授权、业务及收付对应，未闭环项单列，不出具笼统合规保证'),
 '战略布局':('核对披露目标、实际交割与后续业务效果，预期协同不当成已实现成果。','交割文件、业务整合里程碑、同口径客户/产能/分部收入资料','目标、完成事项与未达成部分有可追溯的后续证据'),
 '业务真实性':('核对标的/交易双方、控制和交割、PPA/商誉及经营贡献；客户/供应商、设备与技术移交按已披露交易范围核对，不由收入增长证明并购效果。','交割与主体登记、购买价分摊/估值、减值测试、合同移交/客户同意与设备技术清单及同口径标的经营资料','主体、权属、控制取得与计量时期一致，披露差异、移交范围和后续经营效果分别解释'),
 '大额资金往来':('核对付款方、收款方、贷款人、托管人和标的，区分额度/余额/实际提款及已付/未付；不预设账户路径。','贷款合同与提款/还款表、对价调整计算、托管协议、逐笔银行凭证','同主体同日期同币种勾稽；备考值、会计现金流与银行实付分别有解释'),
 '追偿与执行':('按具体案件及受偿方核对执行进展、资产线索、实际回款和减值；不把追偿方当失信责任人。','后续执行裁定、收款凭证、债权账龄及减值底稿','案号、债权主体、裁判义务与实际回款对应，未执行部分状态明确'),
 '担保与质押':('按具体担保/质押人、对手方、解除/存续及报告期核对敞口；数据库笔数不作当前余额。','担保合同/授权、债务余额、解除公告/登记及代偿/反担保资料','每项主体、期间、金额/股数和状态明确，历史解除记录不进入当前敞口')}


def build_diligence_package(cleaned,target,sources=None,*,prior_packages=None,intake=None,limit=180000):
    sources=list(sources or []);prior_packages=prior_packages or {};intake=intake or {};counts=Counter()
    registry,admitted=identity_registry(cleaned,target,sources);records=[]
    from .company_issuer_identity import build_issuer_identity
    from .company_press_releases import press_financing_rows
    identity=build_issuer_identity(sources,target)
    cards=defaultdict(list)
    for card in cleaned.get('facts') or []:
        if isinstance(card,dict) and EID.fullmatch(str(card.get('evidence_id') or '')):
            cards[str(card.get('source_url') or '')].append(card)
    for source in sources:
        candidates=[c for c in cards[str(get(source,'url'))] if c.get('eligible_for_report') is not False
            and c.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'}
            and c.get('source_entity_validation') not in {'rejected','ambiguous','related_entity_context'}]
        if candidates:
            base=_base(candidates[0],source,target,'')
            records+=press_financing_rows(source,target,base,identity,as_of=str(intake.get('as_of_date') or ''))
    latest={}
    for _s,_p,base in admitted:
        year=re.search(r'20\d{2}',base['period'])
        if year:latest[base['entity']]=max(latest.get(base['entity'],0),int(year[0]))
    for source,pages,base in admitted:
        from .company_audit_disclosures import goodwill_impairment_rows
        records+=goodwill_impairment_rows(pages,base['entity'],base)
        for entry in registry.values():
            if entry['name']==base['entity']:records+=entry['links']
        year=re.search(r'20\d{2}',base['period'])
        if year and int(year[0])>=latest.get(base['entity'],int(year[0]))-2:
            records+=disclosure_rows(source,pages,base)
        else:counts['older_or_undated_document_not_expanded']+=1
        extraction=(get(source,'source_metadata',{}) or {}).get('document_extraction') or {}
        counts['omitted_pages']+=int(extraction.get('omitted_pages') or 0)
        counts['needs_ocr_pages']+=len(extraction.get('needs_ocr_pages') or [])
    # Checked chapters supply typed signals, never generated risk prose.
    for r in prior_packages.get('history',{}).get('facts',[]):
        if r.get('kind')=='event' and re.search(r'配售|募集|发行.*(?:债券|股份)|融资',r.get('fact','')):
            text=_CC.convert(r.get('fact',''));position=text.find(_CC.convert(target))
            local=text[position:position+240] if position>=0 else ''
            if ('战略配售' in text and re.search(r'作为.{0,180}入围|(?:作为|以).{0,35}战略投资者|(?:获选|入围|列入).{0,40}(?:投资者|配售)',local)):
                records.append({**r,'kind':'investment_candidacy','stream':'战略布局','entity':target,
                                'mode':'目标作为他人发行/配售的投资者或名单入围方；不等于目标自身融资、认购完成或资金到账'})
                continue
            year=re.search(r'20\d{2}',str(r.get('period','')))
            if year and int(year[0])<latest.get(target,int(year[0]))-2:continue
            records.append({**r,'kind':'financing','stream':'融资情况','entity':target,'mode':'第三章已核对的具体融资事件；用途仍按原件核对'})
    for r in prior_packages.get('judicial',{}).get('facts',[]):
        if r.get('kind')=='disclosed_case' and re.search(r'执行|未决|审理',r.get('stage','')+r.get('execution','')):
            records.append({**r,'kind':'execution_followup','stream':'追偿与执行','entity':r.get('case_description') or target,
                            'display_reference':{'chapter':9,'section':'发行人及专项法律文件列示事项'},
                            'mode':'第九章具体案件接续，不重复作司法风险结论'})
    # Keep concrete examples of distinct states as triggers. Chapter 9 retains
    # all rows; repeating them here would neither complete nor deepen the check.
    encumbrances=defaultdict(list)
    for r in prior_packages.get('judicial',{}).get('facts',[]):
        if r.get('kind') in {'guarantee','pledge'}:
            status=r.get('fields',{}).get('状态') or r.get('fields',{}).get('履行状态') or '待核'
            encumbrances[(r['kind'],status)].append(r)
    for rs in encumbrances.values():
        r=max(rs,key=lambda r:r.get('date',''))
        records.append({**r,'kind':'encumbrance_followup','stream':'担保与质押','entity':target,
                        'mode':'第九章同类型/同状态选取的触发示例，非全量敞口；按字段中的具体主体穿透'})
    # Dedup only identical claims of the same source, period and subject.
    unique=[];seen=set()
    for r in records:
        key=(r['source_url'],r.get('page'),r.get('entity'),r.get('period'),r['kind'],r.get('fact'))
        if key not in seen:unique.append(r);seen.add(key)
    delivered=[];used=0
    # First secure actual financing / funding / execution signals; do not let
    # hundreds of routine disclosures crowd them out.
    priority={'financing':0,'fund_use':0,'related_funding':1,'execution_followup':1,'relationship':1,
              'accounting_consideration':1,'acquired_cash':1,'unpaid_consideration':1,'acquisition_net_outflow':1,
              'closing':2,'consideration':2,'goodwill':2,'acquired_net_assets':2,'encumbrance_followup':2,'pro_forma':3,'strategy':4}
    for r in sorted(unique,key=lambda r:(priority.get(r['kind'],5),r['source_url'],r.get('page',0))):
        size=len(json.dumps(r,ensure_ascii=False))
        if used+size<=limit:delivered.append(r);used+=size
        else:counts['budget_excluded']+=1
    cash_checks=_cash_checks(delivered)
    grouped=defaultdict(list)
    for r in delivered:
        if r['kind']!='relationship':grouped[r.get('stream','业务真实性')].append(r)
    tasks=[]
    for stream,rs in grouped.items():
        action,materials,close=TASK_ACTIONS[stream]
        # At most three explicit triggers, preserving scope and chronology.
        chosen=select_rows(rs,3)
        tasks.append({'task_id':'D10-'+str(len(tasks)+1).zfill(2),'stream':stream,'triggers':chosen,
                      'object':task_object(chosen[0]),
                      'action':action,'materials':materials,'closure_criteria':close,'status':'待核验，未发送函证/未完成线下尽调',
                      'evidence_ids':sorted({e for r in chosen for e in r['evidence_ids']}),
                      'priority':'具体证据触发的核验事项；核验顺序不等于风险等级'})
    # Every evidenced financing also needs a distinct compliance work order.
    finance=next((t for t in tasks if t['stream']=='融资情况'),None)
    if finance:
        action,materials,close=TASK_ACTIONS['资金使用合规性']
        tasks.append({**finance,'task_id':'D10-'+str(len(tasks)+1).zfill(2),'stream':'资金使用合规性',
                      'action':action,'materials':materials,'closure_criteria':close})
    requested=[]
    explicit=intake.get('client_specified_checks') or []
    for item in ([explicit] if isinstance(explicit,str) else explicit):
        if isinstance(item,str) and item.strip():requested.append(item.strip())
    questions=intake.get('focus_questions') or []
    research_requests=[str(x).strip() for x in ([questions] if isinstance(questions,str) else questions) if isinstance(x,str) and x.strip()]
    if intake.get('special_requirements'):research_requests.append(str(intake['special_requirements']).strip())
    gaps=['委托方指定事项只能来自项目明确输入；“现有客户”“海外大客户”不能证明委托方指定、具体客户名单或客户已同意合同转移。',
          '母公司单体、子公司和集团合并口径分别列示；关联贷款有披露不代表已证明本次交易的实际资金路径，也不代表集团外部新增融资。',
          '交易基准、调整后对价、会计对价、已付/未付、并入现金和净现金流按日期与原币种单位区分，不能拿一种口径替代另一种。',
          '监管通讯案例、股东批准、上市规则分类及其他制度下的重大资产重组分别核对；案例入选不证明监管已审查资金合规或已豁免再融资审批。',
          '公开披露、审计关键事项及备考信息不能替代银行原始凭证、合同和业务背景逐笔核验；未取得材料不直接证明违法或清白。']
    if counts['needs_ocr_pages']:gaps.append(pending_ocr_notice(sources,'存在低文字页尚未执行OCR；正文可读文字与扫描/图像页核验分开。'))
    if counts['omitted_pages']:gaps.append('部分原件未提取全文，未选取到事项不能表述为全文未披露。')
    if counts['budget_excluded']:gaps.append('部分已识别原文超出本章证据预算，任务触发和展示样例均不代表完整尽调覆盖。')
    if counts['older_or_undated_document_not_expanded']:gaps.append('较旧或文件期未绑定的原件未在本章全面展开，仅保留已支持的主体关系/原章节线索；不因此认定不存在其他历史事项。')
    return {'version':VERSION,'target_name':target,'facts':delivered,'tasks':tasks,'client_specified_checks':requested,'research_requests':research_requests,
            'cash_reconciliations':cash_checks,'information_gaps':gaps,
            'diagnostic':{'admitted_documents':len(admitted),'linked_entities':[e['name'] for e in registry.values() if e['links']],
                          'candidate_claims':len(unique),'delivered_claims':len(delivered),'by_kind':dict(Counter(r['kind'] for r in delivered)),
                          'task_count':len(tasks),'filters':dict(counts)}}


def task_object(record):
    parts=[record['entity'],str(record.get('period') or record.get('date') or '记录时期未绑定')]
    if record.get('case_description'):
        if folded(record['case_description'])!=folded(record['entity']):parts.append(record['case_description'])
        parts.append('执行情况：'+record.get('execution','待核'))
    else:
        fact=record['fact']
        # Detailed allocations remain in the financing table, once. A short
        # trigger keeps its actual amount, never just a generic checklist.
        if record.get('kind')=='fund_use' and '其中' in fact:fact=fact.split('其中',1)[0].rstrip('，,；; ')
        parts.append(fact)
    return '；'.join(parts)


def display_diligence_fact(record):
    if record.get('kind')=='execution_followup' and (record.get('display_reference') or {}).get('chapter')==9:
        return ('原件案件阶段：'+record.get('stage','待核')+'；执行披露：'+record.get('execution','待核')
                +'；涉案金额字段：'+record.get('amount','待核')+'；判决主文及诉讼费用详见第九章同事项。')
    if record.get('kind')=='purchase_accounting':
        original=record['fact']
        sentence=re.search(r'\bAs at \d{1,2} [A-Z][a-z]+ 20\d{2},\s+the net carrying amount of goodwill amounted to (?:RMB|US\$|HK\$)[\d,]+(?:\.\d+)?\.',original,re.I)
        if sentence:return sentence[0]
    if record.get('kind')=='closing' and '该项收购' in record['fact'] and len(folded(record['fact']))<100:
        return record['fact']+'（本句未单列收购标的，需结合所引原页上下文核对，不合并为同一笔交易。）'
    return record['fact']


def render_diligence(p):
    lines=['## 10. '+TITLE,'','### 本项目核查方向与触发依据','']
    for request in p.get('research_requests') or []:lines+=['- 项目输入的研究要求：'+request.replace('E-','E－')+'（作为研究范围，未作为企业事实）']
    if p['client_specified_checks']:
        lines+=['委托方明确指定的待核事项（属于研究任务，未作为企业事实或已完成核查）：']+['- '+x for x in p['client_specified_checks']]
    else:lines+=['项目未明确指定专项对象；以下由已核对证据建议核查，不能把一般研究要求或企业自身客户关系改写成委托方特指某笔交易，也不代表已完成专项尽调。']
    for task in p['tasks']:
        lines+=['- '+task['task_id']+' '+task['stream']+'；原件主体或事项线索：'+_cell(task['object'])+' ['+'] ['.join(task['evidence_ids'])+']']
    if not p['tasks']:lines+=['尚未形成可追溯到具体事项的核查对象；不能用通用检查清单冒充本项目已完成穿透。']
    lines+=['','### 已核到的公开披露及其边界','',
            '首列用于定位披露文件的主体或原件已列事项；文件发行人不自动等于子公司交易的收付款人。交易参与方、合并范围与单体资金分别按原文核对；仅以“该公司”指代而未绑定实体的并表语句不单独列为持股事实。','']
    for stream in STREAMS[:5]+('追偿与执行','担保与质押'):
        group=[r for r in p['facts'] if r.get('stream')==stream]
        if not group:continue
        lines+=['#### '+stream,'']
        # A bounded set of evidence rows supports decisions; complete literals
        # stay in the package. Samples are never represented as all records.
        quota={'融资情况':4,'战略布局':3,'业务真实性':8,'追偿与执行':3,'担保与质押':3}.get(stream,12)
        selected=select_rows(group,quota)
        lines+=['本节证据包保留'+str(len(group))+'项原文记录，以下展示'+str(len(selected))+'项；按来源时期分别理解，不作全量覆盖结论。','']
        lines+=_table(['披露来源或事项／文件期','原文核对记录','含义与边界','出处'],[
            [r['entity']+'；'+r.get('period','原记录时期'),display_diligence_fact(r),r.get('mode','')+'；'+r.get('stage_note','')+'；'+r.get('negotiation_note',''),
             refs(r)+(f"（物理页{r['page']}）" if r.get('page') else '')] for r in selected])
    relations=[r for r in p['facts'] if r['kind']=='relationship']
    if relations:
        lines+=['','关联主体纳入依据（持股关系不等于母公司直接付款或承担全部债务）：']
        for r in relations[:6]:lines+=['- '+r['fact']+' '+refs(r)+f"（物理页{r['page']}）"]
    if p['cash_reconciliations']:
        lines+=['','原页现金流勾稽（非银行实付认证）：']
        for c in p['cash_reconciliations']:
            lines+=['- '+c['entity']+'；'+c['equation']+' '+c['unit']+'；'+('原表勾稽一致' if c['matched'] else '原表金额尚未勾稽一致，需回原件核对')+' '+refs(c)+f"（物理页{c['page']}）"]
    lines+=['','### 专项核验任务台账','']
    if p['tasks']:lines+=_table(['编号/事项','待验证问题','所需材料','闭环标准与当前状态'],[
        [t['task_id']+' '+t['stream'],t['action'],t['materials'],t['closure_criteria']+'；'+t['status']] for t in p['tasks']])
    lines+=['','### 核查范围与未闭环项','']+['- '+x for x in p['information_gaps']]
    return '\n'.join(lines)


def diligence_errors(text,p):
    errors=[]
    if text.strip()!=render_diligence(p).strip():errors.append('第十章出现未受定向核查证据或明确委托支持的改写')
    if not p['tasks']:errors.append('第十章尚无具体证据触发的专项核查对象')
    allowed={e for r in p['facts'] for e in r['evidence_ids']}
    if set(cited_evidence_ids(text))-allowed:errors.append('第十章存在未知证据编号')
    return errors
