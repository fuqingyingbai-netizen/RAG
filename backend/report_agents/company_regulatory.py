"""Literal regulator decisions and follow-up notices, separate from judgments.

Only an authenticated regulator page and its locally bound recipient/action
can supply a record. A historical fine is never a present outstanding balance;
a later compliance assessment does not erase the original decision.
"""
import re
from datetime import date
from urllib.parse import urlparse

from .company_evidence import source_body
from .company_governance import get
from .company_text import OriginalTextView,match_compact,match_text

REGULATORS={
    'samr.gov.cn':'国家市场监督管理总局',
    'cac.gov.cn':'国家互联网信息办公室',
    'csrc.gov.cn':'中国证券监督管理委员会',
}
ACTORS={
    '国家市场监督管理总局':r'(?:国家市场监督管理总局|市场监管总局)',
    '国家互联网信息办公室':r'(?:国家互联网信息办公室|国家网信办)',
    '中国证券监督管理委员会':r'(?:中国证券监督管理委员会|中国证监会)',
}
DAY=r'(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?'


def _date(value):
    match=re.search(DAY,value)
    if not match:return ''
    try:return date(*(int(x) for x in match.groups())).isoformat()
    except ValueError:return ''


def regulatory_records(source,target,base):
    """Recover a bounded action quote; title and aliases cannot bind other cases."""
    host=(urlparse(str(get(source,'url'))).hostname or '').lower()
    authority=next((name for domain,name in REGULATORS.items() if host==domain or host.endswith('.'+domain)),None)
    raw,origin=source_body(source);meta=get(source,'source_metadata',{}) or {}
    if not authority or origin=='discovery_summary' or meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:
        return []
    if meta.get('fetch_status') in {'failed','blocked_or_challenge','empty','wrong_page','wrong_page_or_homepage'}:
        return []
    normal=match_text(raw);name=match_text(target)
    # Full legal recipient must be in the title/first body heading. A parent
    # mentioned only as owner of the sanctioned child fails this check.
    lead='\n'.join(normal.splitlines()[:7])
    if match_compact(name) not in match_compact(lead):return []
    spaced=r'\s*'.join(map(re.escape,name))
    aliases=[spaced]
    definition=re.search(spaced+r'\s*[（(]\s*以下简称\s*[「“\"]?([^）)「」“”\"]{2,45})',normal)
    if definition:
        alias=definition[1].strip()
        if alias not in {'本公司','公司','本集团','集团'}:aliases.append(re.escape(alias))
    recipient='(?:'+'|'.join(aliases)+')'
    publication_match=re.search(r'(?:发布时间|发布日期)\s*[:：]?\s*'+DAY,normal)
    publication=_date(publication_match[0]) if publication_match else ''
    # Never bind a date from site navigation to an unrelated historical action.
    records=[]
    for original in re.split(r'(?<=[。；])\s*|\n\s*\n',raw):
        quote=original.strip();view=OriginalTextView(quote);text=view.text
        if not 20<=len(text)<=900 or re.search(r'可能|拟作出|拟对|如违反|若违反|处罚告知|听证告知',text):continue
        action=re.search(r'(?:对\s*'+recipient+r'[^。；]{0,160}?(?:作出行政处罚|处以[^。；]{0,90}罚款)|作出行政处罚决定[^。；]{0,100}?'+recipient+r')',text)
        if not action:continue
        actor=ACTORS[authority]+r'\s*(?:(?:依法|已|决定|近日)\s*)?(?:对\s*'+recipient+r'|作出行政处罚决定)'
        if not re.search(actor,text):continue  # publisher domain is not proof of the deciding agency
        # A full native action date is required. The article's publication
        # date and a year/month retrospective are not substitutes.
        # Bind the nearest full date in the same action clause. A flattened
        # page may include its publication label before a month-only history.
        action_clause=text[:action.end()]
        action_clause=re.split(r'(?:发布时间|发布日期)\s*[:：]?\s*'+DAY+r'(?:\s+\d{1,2}:\d{2})?',action_clause)[-1]
        dates=list(re.finditer(DAY,action_clause))
        event_date=_date(dates[-1][0]) if dates else ''
        if not event_date or not publication:continue
        if re.search(r'撤销[^。；]{0,30}处罚|处罚[^。；]{0,15}被撤销',text):continue
        # Do not associate a nearby amount or date from another recipient.
        tail=text[action.end():]
        if re.search(r'(?:另|同时对|分别对)[^。；]{0,60}(?:有限公司|股份公司)',tail):continue
        amount=re.search(r'(?:罚款[，,]?\s*(?:计|人民币)?|处以(?:人民币)?)\s*([\d,.]+\s*(?:亿|万)?元)',text)
        decision=re.search(r'[\u4e00-\u9fff]{2,12}[〔（(\[]20\d{2}[〕）)\]]\s*\d+\s*号',normal)
        records.append({**base,'kind':'administrative_penalty','entity':target,'date':event_date,
            'period':event_date,'publication_date':publication,'authority':authority,
            'decision_id':decision[0] if decision else '',
            'penalty_amount_text':view.quote(amount.start(1),amount.end(1)) if amount else '',
            'fact':quote,'evidence_quote':quote,'mode':'监管机关原公告；行政处罚，不是法院判决',
            'boundary':'仅指原决定及其当时事实；罚款决定金额不等于尚未支付余额，不推定截至研究日仍持续违法、未整改或已结清。'})
    # A completion headline establishes what the regulator stated at its
    # publication date, not an invented day on which all remediation ended.
    if publication and re.search(recipient+r'[^\n]{0,30}完成[^\n]{0,15}整改',lead):
        paragraphs=re.split(r'\n\s*\n',raw)
        for original in paragraphs:
            text=match_text(original)
            if not re.search(r'核查|评估',text) or not re.search(recipient,text):continue
            if not re.search(r'整改.{0,30}(?:取得|成效)|停止.{0,30}(?:违法|垄断)',text):continue
            # Future instructions are kept separate from the assessed results.
            quote=re.split(r'下一步[，,]',original)[0].strip()
            start=re.search(r'(?:[一二三四五六七八九十\d]+年来[，,]|从核查和评估情况看[，,]|经核查[，,])',match_text(quote))
            if start:
                view=OriginalTextView(quote)
                quote=view.quote(start.start(),len(view.text)).strip()
            if len(quote)>900:continue
            records.append({**base,'kind':'regulatory_remediation','entity':target,'date':publication,
                'period':publication,'publication_date':publication,'authority':authority,
                'fact':quote,'evidence_quote':quote,'mode':'监管机关截至公告日的整改核查评估',
                'boundary':'日期为核查评估公告日；不替代逐项整改原始凭证，也不消除历史处罚或证明其他业务及未来期间无风险。'})
            break
    return records
