"""Native issuer financing releases; no inferred cash receipts or net amounts."""
import re
from datetime import date,datetime

from .company_evidence import source_body
from .company_issuer_identity import bilingual_publisher_anchor

MONEY=r'(?:HK\$|US\$|USD|RMB)\s*[\d,]+(?:\.\d+)?(?:\s+(?:billion|million))?'


def press_financing_rows(source,target,base,identity,*,as_of=''):
    anchor=bilingual_publisher_anchor(source,target,identity)
    if not anchor or not anchor.get('bilingual_binding'):return []
    raw,origin=source_body(source)
    if origin=='discovery_summary':return []
    head=raw[:3000];dates=[]
    chinese=re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日',head)
    if chinese:
        try:dates.append(date(*(int(v) for v in chinese.groups())).isoformat())
        except ValueError:return []
    english=re.search(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b',head)
    if english:
        try:dates.append(datetime.strptime(english[0],'%B %d, %Y').date().isoformat())
        except ValueError:return []
    if not dates or len(set(dates))!=1:return []
    publication=dates[0]
    if as_of and publication>as_of:return []
    paragraphs=[p.strip() for p in re.split(r'\n\s*\n',raw) if p.strip()]
    owner=anchor['bilingual_binding']['original_legal_name'];rows=[]
    for quote in paragraphs:
        if not 40<=len(quote)<=1500 or owner not in quote:continue
        action=re.search(re.escape(owner)+r'\s*\([^\n]{5,260}\)\s*today announced the completion of (?:its )?('+MONEY+r')\s+placing\s+of\s+([\d,]+)\s+newly issued ordinary shares',quote,re.I)
        price=re.search(r'placing price of\s+('+MONEY+r')\s+per\s+(?:Placement\s+)?Share',quote,re.I)
        if not action or not price or re.search(r'expected completion|subject to completion|not completed|has not completed',quote,re.I):continue
        rows.append({**base,'kind':'financing','stream':'融资情况','entity':target,'period':publication,
            'date':publication,'publication_date':publication,'fact':quote,'evidence_quote':quote,
            'gross_proceeds_text':action[1],'shares_text':action[2],'placing_price_text':price[1],
            'net_proceeds_text':'','document_origin':'issuer_press_release',
            'issuer_binding':anchor['bilingual_binding'],
            'mode':'发行人原公告称配售完成；总额、股数和每股价格分列，非银行到账认证',
            'stage_note':'未见明确总募集净额时不由用途比例/分项金额反算，不将总额冒充净额。'})
        break
    if not rows:return []
    for quote in paragraphs:
        if len(quote)>1500 or not re.search(r'The Company intends to (?:utilize|use) the net proceeds',quote,re.I):continue
        rows.append({**base,'kind':'financing_use_plan','stream':'融资情况','entity':target,'period':publication,
            'date':publication,'publication_date':publication,'fact':quote,'evidence_quote':quote,
            'document_origin':'issuer_press_release','mode':'拟定募集资金用途／非实际支出',
            'stage_note':'将来用途、分配比例和拟分配金额不等于已支付、已使用或银行流水；不相加反推实际总净额。'})
        break
    return rows
