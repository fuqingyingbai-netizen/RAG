"""Bound explicit fiscal periods and original consolidated statement columns.

No issuer figures or calendar year-end defaults are embedded here. Ambiguous
headers, currency columns and shareholder-profit definitions remain gaps.
"""
import re
from datetime import date
from decimal import Decimal

from .company_text import OriginalTextView, issuer_anchor, match_text


def quarter_report_period(raw,target=''):
    view=OriginalTextView(str(raw or '')[:12000]);head=view.text
    if not re.search(r'季度业绩公告',head[:3000]):return None
    prefix=re.escape(match_text(target))+r'.{0,400}?' if target else ''
    m=re.search(prefix+r'今日公布截至\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日止季度业绩',head,re.S)
    if not m:return None
    try:end=date(*(int(v) for v in m.groups()))
    except ValueError:return None
    if end.month not in {3,6,9,12}:return None
    audit='未经审计' if '未经审计' in match_text(raw) else '审计状态未单独绑定'
    aliases=re.findall(r'[「“"]([^」”"\n]{3,60})[」”"]',m[0].split('今日公布',1)[0]) if target else []
    pub=re.search(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[–—-]',head[:m.start()+200])
    publication=''
    if pub:
        try:publication=date(*(int(v) for v in pub.groups())).isoformat()
        except ValueError:pass
    return {'cutoff':end.isoformat(),'year':end.year,'period':f'截至{end.isoformat()}止三个月季度业绩（{audit}）',
            'period_kind':'quarterly','audit_status':audit,'issuer_aliases':aliases,
            'issuer_declaration_quote':view.quote(m.start(),m.end()),'publication_date':publication,'translation_note':''}


def fiscal_report_period(raw):
    head = str(raw or '')[:6500]
    if not re.search(r'20\s*[-－]?\s*F|[财財]年|[财財]政年度|[财財][务務]年度', head, re.I):
        return None
    text = match_text(head)
    if not re.search(r'20\s*[-－]?\s*F|财年|财政年度|财务年度', text, re.I):
        return None
    if not re.search(r'20\s*[-－]?\s*F|20\d{2}\s*(?:财年|财政年度)\s*(?:年度报告|年报)', text, re.I):
        return None
    if not re.search(r'年度报告|annual\s+report', text, re.I):
        return None
    dates = []
    for m in re.finditer(r'截至\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日止\s*(?:财务|财政)?年度', text):
        try:
            dates.append(date(*(int(v) for v in m.groups())))
        except ValueError:
            continue
    if not dates:
        return None
    # The cover's first bound annual period wins. A later shareholder letter
    # may discuss a future fiscal year; it cannot change the filed period.
    end = dates[0]
    translation = next((line.strip() for line in head.splitlines()
                        if re.search(r'中文译本.{0,100}英文版本为准', match_text(line))), '')
    return {'cutoff': end.isoformat(), 'year': end.year,
            'period': f'{end.year}财年年度报告（截至{end.isoformat()}）',
            'translation_note': translation}


_MONEY = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_CELL = re.compile(r'[-+]?' + _MONEY + r'|\(' + _MONEY + r'\)|[—-]')


def _value(cell):
    if cell in {'—', '-'}:
        return None
    return '-' + cell[1:-1] if cell.startswith('(') else cell


def consolidated_statement_rows(pages, target, base, period, cutoff, metrics):
    """Read annual RMB columns, retaining an original row and header locator.

    A convenience USD column is kept in the header proof and excluded from the
    RMB comparison. Parent/VIE reconciliations are not consolidated statements.
    Company-owner profit is not silently replaced by ordinary-share profit.
    """
    document_head = '\n'.join(p['text'] for p in pages[:8])
    fiscal = fiscal_report_period(document_head) or {}
    quarter=quarter_report_period('\n'.join(p['text'] for p in pages),target) if not fiscal else None
    if not issuer_anchor(document_head, target)['matched'] and not quarter:return []
    if quarter and quarter['cutoff']!=cutoff:return []
    period_kind='quarterly' if quarter else 'annual'
    declared_names=[target]+((quarter or {}).get('issuer_aliases') or [])
    rows = []
    target_pattern = '|'.join(r'\s*'.join(map(re.escape, match_text(name))) for name in declared_names)
    labels = [(metrics[0], r'(?:营业收入|收入)'),
              (metrics[1], r'归属于\s*(?:(?:' + target_pattern + r')\s*股东|母公司(?:股东|所有者)|上市公司股东)的净利润'),
              (metrics[2], r'经营活动产生(?:\s*[（(]所用[）)])?的现金流量净额')]
    for page in pages:
        raw = page['text']
        text = match_text(raw)
        heading = re.search(r'(?m)^\s*(?:未经审计)?(?:简明)?合并(?:利润表|损益表|现金流量表)\s*(?:[（(]续[）)])?\s*$', text)
        if not heading:
            continue
        if quarter and not issuer_anchor(text[:heading.start()],target)['matched']:continue
        header = text[heading.end():heading.end() + 400]
        unit_match = re.search(r'[（(]\s*(?:以)?(百万元|千元|万元|元|百万)(?:计)?(?:[，,）)])', header)
        years_match = re.search(r'(?m)^\s*((?:20\d{2}\s+){1,5}20\d{2})\s*$', header)
        duration='三个月' if quarter else '年度'
        if not unit_match or not years_match or '止'+duration not in re.sub(r'\s+','',header):
            continue
        end_date = re.search(r'截至\s*(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日止'+duration, header)
        if (not end_date or (end_date[1] and int(end_date[1]) != int(cutoff[:4]))
                or (int(end_date[2]), int(end_date[3])) != (int(cutoff[5:7]), int(cutoff[8:10]))):
            continue
        header = header[:unit_match.end()]
        if re.search(r'母公司|主要\s*VIE|抵销|合并总额', header, re.I):
            continue
        years = [int(x) for x in re.findall(r'20\d{2}', years_match[1])]
        currencies = re.findall(r'人民币|美元|港元', header)
        rmb_count = len([x for x in currencies if x == '人民币'])
        if rmb_count < 2 or currencies[:rmb_count] != ['人民币'] * rmb_count:
            continue
        if currencies[rmb_count:] not in ([], ['美元']):
            continue
        rmb_years = years[:rmb_count]
        if len(rmb_years) != rmb_count or rmb_years != sorted(set(rmb_years)):
            continue
        if len(years) not in {rmb_count, len(currencies)}:
            continue
        if len(years) > rmb_count and years[-1] != rmb_years[-1]:
            continue
        current_year = int(cutoff[:4])
        if rmb_years[-1] != current_year or current_year - 1 not in rmb_years:
            continue
        current, previous = rmb_years.index(current_year), rmb_years.index(current_year - 1)
        unit='百万元' if unit_match[1]=='百万' else unit_match[1]
        view = OriginalTextView(raw)
        for metric, label in labels:
            for m in re.finditer(r'(?m)^\s*(?P<label>' + label + r')\s+(?P<cells>[^\n]+)', text):
                parts = m['cells'].split()
                if len(parts) < len(currencies):
                    continue
                cells, prefix = parts[-len(currencies):], ' '.join(parts[:-len(currencies)])
                if not all(_CELL.fullmatch(x) for x in cells):
                    continue
                if prefix and (not re.fullmatch(r'\d{1,2}(?:,\s*\d{1,2})*', prefix) or '附注' not in header):
                    continue
                values = [_value(x) for x in cells]
                a, b = values[current], values[previous]
                if a is None or b is None:
                    continue
                av, bv = Decimal(a.replace(',', '')), Decimal(b.replace(',', ''))
                yoy = (av / bv - 1) * 100 if bv > 0 else None
                native_label = re.sub(r'\s+', '', view.quote(m.start('label'), m.end('label')))
                row = {**base, 'kind': 'financial_metric', 'metric': metric,
                       'source_metric': native_label, 'value': a, 'previous_value': b,
                       'unit': unit, 'currency': '人民币', 'period': period,
                       'cutoff': cutoff, 'period_kind': period_kind, 'page': page['page'],
                       'statement_scope': 'consolidated_group',
                       'yoy': str(yoy.quantize(Decimal('.01'))) + '%' if yoy is not None else '',
                       'yoy_basis': '按原表同币种上年同季计算，非原表列示同比' if quarter else '按原表同币种相邻财年计算，非原表列示同比',
                       'computed_yoy_pct': str(yoy.quantize(Decimal('.0001'))) if yoy is not None else None,
                       'printed_yoy_conflict': False,
                       'evidence_quote': view.quote(m.start(), m.end()).strip(),
                       'column_header_quote': view.quote(heading.start(), heading.end() + len(header)),
                       'column_years': rmb_years, 'column_currencies': currencies,
                       'source_translation_note': fiscal.get('translation_note',''),
                       'mode': '原件合并报表明确财年/币种列；不取母公司或VIE调节表、不取美元换算列、不以普通股利润替代公司股东利润',
                       'fact': native_label + '：本期人民币' + a + unit + '，上期人民币' + b + unit}
                if current_year - 2 in rmb_years:
                    third = values[rmb_years.index(current_year - 2)]
                    if third is not None:
                        row.update(third_value=third, third_period=str(current_year - 2) + '财年')
                if quarter:
                    row.update(audit_status=quarter['audit_status'],publication_date=quarter['publication_date'],
                               issuer_declaration_quote=quarter['issuer_declaration_quote'],
                               mode=quarter['audit_status']+'季度合并报表原币列；季度同比不与全年/半年混算，普通股利润与公司股东利润分别核对')
                rows.append(row)
                break
    return rows


def fiscal_segment_revenue_rows(pages,target,period):
    """Bound a native annual segment table and reconcile every RMB column.

    Only unindented top-level rows are admitted. Nested business lines and
    anonymous subtotals are excluded, and the USD convenience column is never
    compared with RMB. Reclassification notes stay attached to the table.
    """
    head='\n'.join(p['text'] for p in pages[:8])
    fiscal=fiscal_report_period(head)
    if not fiscal or fiscal['period']!=period or not issuer_anchor(head,target)['matched']:return []
    for page in pages:
        raw=page['text'];view=OriginalTextView(raw);text=view.text
        start=re.search(r'分部间抵消前.{0,25}分部收入如下表',text)
        if not start:continue
        tail=text[start.end():];unit=re.search(r'[（(]百万元[）)]',tail[:500])
        years=re.search(r'(?m)^\s*((?:20\d{2}\s+){1,4}20\d{2})\s*$',tail[:500])
        date_head=re.search(r'截至\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日止年度',tail[:500])
        if not unit or not years or not date_head:continue
        cutoff=fiscal['cutoff']
        if (int(date_head[1]),int(date_head[2]))!=(int(cutoff[5:7]),int(cutoff[8:10])):continue
        yr=[int(y) for y in re.findall(r'20\d{2}',years[1])]
        currencies=re.findall(r'人民币|美元|港元',tail[:unit.start()])
        if len(yr)<2 or yr!=sorted(set(yr)) or yr[-1]!=fiscal['year']:continue
        if currencies not in [['人民币']*len(yr),['人民币']*len(yr)+['美元']]:continue
        table_start=start.end()+unit.end();body=text[table_start:]
        lines=list(re.finditer(r'[^\n]+',body));found=[];pending=None
        for line in lines:
            value=line[0]
            if re.match(r'\s*[（(]?\d+[.．、]',value) and not re.match(r'\s*[（(]\d+[）)]',value):break
            if value[0].isspace():continue
            m=re.fullmatch(r'(?P<label>[^\d\n:：]{1,65}?)\s+(?P<cells>[-\d,(][\d,().\s-]*)',value)
            if not m:
                if re.fullmatch(r'[^\d\s:：]{2,60}',value):pending=(value,line.start())
                elif pending:
                    m2=re.fullmatch(r'[（(]\d+[）)]\s*(?P<cells>[-\d,(][\d,().\s-]*)',value)
                    if m2:
                        label,offset=pending;m=(label,m2['cells'],offset,line.end());pending=None
                if not m:continue
            if isinstance(m,tuple):label,cells,offset,finish=m
            else:label,cells,offset,finish=m['label'].strip(),m['cells'],line.start(),line.end()
            values=cells.split()
            if len(values)!=len(currencies) or not all(_CELL.fullmatch(v) for v in values):continue
            numbers=[_value(v) for v in values[:len(yr)]]
            if any(v is None for v in numbers):continue
            quote=view.quote(table_start+offset,table_start+finish)
            found.append((label,numbers,quote))
            if label=='合并收入':break
        totals=[x for x in found if x[0]=='合并收入']
        if len(totals)!=1 or not any(x[0]=='分部间抵消' for x in found) or len(found)<4:continue
        total=totals[0]
        if any(sum(Decimal(x[1][i].replace(',','')) for x in found if x is not total)!=Decimal(total[1][i].replace(',','')) for i in range(len(yr))):continue
        note_match=re.search(r'(?:1[.．]|[（(]1[）)])\s*(.{20,900}?)\n\s*(?:2[.．]|[（(]2[）)])',body,re.S)
        note=view.quote(table_start+note_match.start(1),table_start+note_match.end(1)).strip() if note_match else ''
        header_quote=view.quote(start.start(),table_start)
        return [{'kind':'segment_revenue','entity':label,'dimension':'分部／合并调节',
                 'value':numbers[-1],'previous_value':numbers[-2],'unit':'百万元','currency':'人民币',
                 'period':period,'value_period':str(yr[-1])+'财年','previous_period':str(yr[-2])+'财年',
                 'page':page['page'],'fact':label+'：本期人民币'+numbers[-1]+'百万元，上期人民币'+numbers[-2]+'百万元',
                 'evidence_quote':quote,'column_header_quote':header_quote,'column_years':yr,'column_currencies':currencies,
                 'reclassification_note':note,'source_translation_note':fiscal['translation_note'],
                 'reconciliation_verified':True,'mode':'原表顶层分部及合并调节；逐年人民币勾稽通过；排除嵌套明细和美元换算列'}
                for label,numbers,quote in found]
    return []
