"""Chinese 20-F ordinary-share/ADS beneficial-interest table, not a registry."""
import hashlib
import re
from datetime import date
from decimal import Decimal
from .company_text import OriginalTextView,match_compact

NUMBER=r'(?:\d{1,3}(?:,\d{3})+|\d+)'
VALUES=re.compile(r'(?<![\d,])(?P<ordinary>'+NUMBER+r')\s+(?P<ads>'+NUMBER+r')\s+(?P<ratio>\d+(?:\.\d+)?%)\s*$')
DAY=r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日'


def beneficial_ownership_disclosures(pages,*,as_of_date=''):
    rows=[];contexts=[]
    if as_of_date:
        try:as_of_date=date.fromisoformat(str(as_of_date)[:10]).isoformat()
        except ValueError:return rows,contexts
    for page in pages:
        raw=str(page.get('text') or '')
        if not any(word in raw for word in ('實益所有權','实益所有权')):continue
        view=OriginalTextView(raw);text=view.text;compact=match_compact(text)
        if not re.search(r'A[.．、]?\s*主要股东',text):continue
        if '实益所有权资料按照美国证交会的规则和条例' not in compact:continue
        if re.search(r'示例|以下仅为假设|假设(?:数据|表格|持股)',text):continue
        dated=re.search(r'下表载列截至\s*'+DAY+r'[^：:]{0,180}(?:普通股|实益所有权)[^：:]{0,90}[：:]',text)
        if not dated:continue
        try:cutoff=date(*(int(dated[i]) for i in (1,2,3))).isoformat()
        except ValueError:continue
        if as_of_date and cutoff>as_of_date:continue
        header=re.search(r'实益所有权\s+实益所有权\s+姓名\s*[（(]股份[）)]\s*[（(]美国存托股[）)]\s*(?:[（(]\d+[）)]\s*)?比例',text[dated.end():])
        if not header:continue
        start=dated.end()+header.end()
        end=re.search(r'附\s*注\s*[：:]|\n\s*B[.．、]\s*关联交易',text[start:])
        stop=start+end.start() if end else len(text)
        definition=view.quote(dated.start(),dated.end()+header.start()).strip()
        if len(definition)>2200:continue
        signature=hashlib.sha256(match_compact(definition).encode()).hexdigest()[:16]
        context={'key':signature,'cutoff':cutoff,'page':page['page'],'definition_quote':definition,
                 'date_quote':view.quote(dated.start(),dated.end()),
                 'basis':'20-F实益所有权；普通股与美国存托股分列，非完整登记股东名册',
                 'boundary':'按原表定义逐人理解，可能包含60日内可取得股份及表决/处置权；不直接等同本人金钱权益或实际控制，比例不简单相加，不由ADS列重算普通股。'}
        pending=None;offset=start;found=[]
        for line in text[start:stop].splitlines(keepends=True):
            stripped=line.strip();match=VALUES.search(stripped);body_start=offset+len(line)-len(line.lstrip())
            if match:
                prefix=stripped[:match.start()].strip()
                marker=re.fullmatch(r'[（(]\s*\d+\s*[）)]',prefix)
                note_match=re.search(r'[（(]\s*(\d+)\s*[）)]\s*$',prefix)
                note=note_match[1] if note_match else ''
                if not prefix or marker:
                    if pending is None:offset+=len(line);continue
                    name,quote_start,name_end,pending_note=pending
                    note=note or pending_note
                else:
                    name=re.sub(r'\s*[（(]\s*\d+\s*[）)]\s*$','',prefix).strip()
                    quote_start=body_start;name_end=body_start+len(name)
                pending=None
                if not 2<=len(name)<=90 or re.search(r'[|：:%]|^\d',name):offset+=len(line);continue
                if Decimal(match['ratio'][:-1])>100:offset+=len(line);continue
                if not all(re.fullmatch(NUMBER,match[k]) for k in ('ordinary','ads')):offset+=len(line);continue
                original=view.quote(quote_start,offset+len(line)).strip()
                aggregate=bool(re.search(r'全体董事.*高级管理人员.*合计',name))
                native_name=view.quote(quote_start,name_end).strip()
                found.append({'kind':'beneficial_ownership_total' if aggregate else 'beneficial_ownership',
                    'entity':native_name,'holder_key':match_compact(name),'page':page['page'],'footnote_marker':note,
                    'period':cutoff+'（原表截至日）','cutoff':cutoff,'ordinary_shares':match['ordinary'],
                    'ads':match['ads'],'ratio':match['ratio'],'context_key':signature,
                    'evidence_quote':original,'fact':original,'basis':'issuer_beneficial_ownership'})
            elif stripped and re.fullmatch(r'[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 .·-]{1,89}(?:[（(]\d+[）)])?',stripped):
                name=re.sub(r'\s*[（(]\d+[）)]$','',stripped).strip()
                marker=re.search(r'[（(](\d+)[）)]$',stripped)
                pending=(name,body_start,body_start+len(name),marker[1] if marker else '')
            elif stripped:pending=None
            offset+=len(line)
        if found:
            caveats=[]
            nearby=[p for p in pages if p['page'] in {page['page'],page['page']+1}]
            for holder in found:
                if not holder['footnote_marker']:continue
                for note_page in nearby:
                    note_view=OriginalTextView(note_page['text'])
                    pattern=re.escape(OriginalTextView(holder['entity']).text)+r'(?:先生|女士)?[^。]{0,750}?不具有任何金钱权益[^。]{0,30}。'
                    for m in re.finditer(pattern,note_view.text):
                        caveats.append({'entity':holder['entity'],'marker':holder['footnote_marker'],'page':note_page['page'],
                                        'quote':note_view.quote(m.start(),m.end())})
            context['holder_caveats']=caveats
            signature=hashlib.sha256((match_compact(definition)+'|'+str(page['page'])+'|'+
                '|'.join(str(c['page'])+match_compact(c['entity']+c['quote']) for c in caveats)).encode()).hexdigest()[:16]
            context['key']=signature
            for ordinal,row in enumerate(found,1):row.update(context_key=signature,row_ordinal=ordinal)
            rows+=found;contexts.append(context)
    return rows,contexts
