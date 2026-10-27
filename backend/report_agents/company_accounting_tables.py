"""Issuer main-accounting grids with explicit year and restatement columns.

Only native grid headers assign columns. Amounts never decide which column is
current, comparative, adjusted or unadjusted. A split label requires the exact
empty-cell continuation on the immediately following physical page.
"""
import re
from decimal import Decimal, InvalidOperation

from .company_text import OriginalTextView, match_text

VERSION = 'company-main-accounting-grid-v1'


def compact(value):
    return re.sub(r'\s+', '', match_text(str(value or '')))


def amount(value):
    text = compact(value)
    if not re.fullmatch(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)', text):
        return None
    return '-' + text[1:-1] if text.startswith('(') else text


def number(value):
    try:
        return Decimal(str(value).replace(',', '').removesuffix('%'))
    except (InvalidOperation, ValueError):
        return None


def native_row_quote(text, cells):
    view = OriginalTextView(text)
    pieces = [r'\s*'.join(map(re.escape, compact(cell))) for cell in cells if compact(cell)]
    if not pieces:
        return ''
    found = re.search(r'\s*'.join(pieces), view.text)
    return view.quote(found.start(), found.end()) if found else ''


def row_pattern(cells):
    return r'\s*'.join(r'\s*'.join(map(re.escape, compact(cell))) for cell in cells if compact(cell))


def schema(headers, year, interim):
    width = max((len(row) for row in headers), default=0)
    columns = []; carrying_year = None
    for index in range(1, width):
        labels = [compact(row[index]) for row in headers if index < len(row) and compact(row[index])]
        joined = ''.join(labels)
        years = {int(m[1]) for label in labels for m in re.finditer(r'^(20\d{2})年(?:度)?$', label)}
        basis = 'adjusted' if any(v in joined for v in ('调整后', '重述后')) else 'unadjusted' if any(v in joined for v in ('调整前', '重述前')) else ''
        if len(years) == 1:
            carrying_year = next(iter(years))
            columns.append({'index': index, 'year': carrying_year, 'basis': basis, 'labels': labels})
        elif '增减' in joined and '%' in joined:
            columns.append({'index': index, 'kind': 'change', 'labels': labels}); carrying_year = None
        elif interim and '本报告期' in joined and '末' not in joined:
            carrying_year=year
            columns.append({'index': index, 'year': year, 'basis': basis, 'labels': labels})
        elif interim and '上年同期' in joined and '末' not in joined:
            carrying_year=year-1
            columns.append({'index': index, 'year': year - 1, 'basis': basis, 'labels': labels})
        elif basis and carrying_year is not None:
            columns.append({'index': index, 'year': carrying_year, 'basis': basis, 'labels': labels})
        else:
            columns.append({'index': index, 'kind': 'unknown', 'labels': labels})
    current = [c for c in columns if c.get('year') == year]
    previous = [c for c in columns if c.get('year') == year - 1]
    if len(current) != 1 or not previous:
        return None
    if len(previous) > 1:
        adjusted = [c for c in previous if c['basis'] == 'adjusted']
        before = [c for c in previous if c['basis'] == 'unadjusted']
        if len(adjusted) != 1 or len(before) != 1 or len(previous) != 2:
            return None
        prior = adjusted[0]
    else:
        prior = previous[0]
    changes = [c for c in columns if c.get('kind') == 'change']
    if len(changes) != 1:
        return None
    return {'columns': columns, 'current': current[0], 'previous': prior,
            'change': changes[0], 'before': [c for c in previous if c['basis'] == 'unadjusted' and c != prior],
            'third': [c for c in columns if c.get('year') == year - 2]}


def accounting_grid_rows(pages, target, base, period, cutoff, metrics, raw_source=''):
    year = int(cutoff[:4]); interim = '半年度' in period or '中期' in period
    aliases = {compact(name): name for name in metrics}
    aliases.update({compact(name): metrics[1] for name in
                    ('归属于母公司股东的净利润', '归属于母公司所有者的净利润')})
    ordered = sorted(pages, key=lambda p: p['page']); result = []
    for page_index, page in enumerate(ordered[:55]):
        raw = page['text']; view = OriginalTextView(raw)
        for table in page.get('tables') or []:
            if not table or not table[0] or not re.search(r'主要会计数据|主要财务数据', compact(table[0][0])):
                continue
            first_data = next((i for i, row in enumerate(table) if i and any(amount(c) is not None for c in row[1:])), None)
            if first_data is None:
                continue
            headers = table[:first_data]; layout = schema(headers, year, interim)
            if not layout:
                continue
            header_quote=native_row_quote(raw,[cell for header in headers for cell in header])
            if not header_quote:
                continue
            label_match = re.search(row_pattern(table[first_data]), view.text)
            if not label_match:
                continue
            before_data = view.text[:label_match.start()]
            units = list(re.finditer(r'单位\s*[:：]\s*(人民币|美元|港元|欧元|日元|英镑)?\s*(百万元|万元|千元|元)(?![／/])', before_data))
            if not units:
                continue
            unit_match = units[-1]; unit = unit_match[2]
            currencies = list(re.finditer(r'币种\s*[:：]\s*(人民币|美元|港元|欧元|日元|英镑)', before_data[unit_match.start():]))
            currency = currencies[-1][1] if currencies else unit_match[1] or '未载'
            unit_quote = view.quote(unit_match.start(), label_match.start())
            if raw_source and (unit_quote not in raw_source or header_quote not in raw_source):
                continue
            for row_index, row in enumerate(table[first_data:], first_data):
                label = compact(row[0]); metric = aliases.get(label); continuation = None
                if not metric and row_index == len(table) - 1 and page_index + 1 < len(ordered):
                    following = ordered[page_index + 1]
                    tables = following.get('tables') or []
                    if following['page'] == page['page'] + 1 and tables and tables[0]:
                        tail = tables[0][0]
                        if len(tail) == len(row) and all(not compact(c) for c in tail[1:]):
                            metric = aliases.get(label + compact(tail[0]))
                            if metric:
                                continuation = (following, tail)
                if not metric or len(row) < max(c['index'] for c in layout['columns']) + 1:
                    continue
                if any(c.get('kind') == 'unknown' and compact(row[c['index']]) for c in layout['columns']):
                    continue
                value = amount(row[layout['current']['index']]); previous = amount(row[layout['previous']['index']])
                if value is None or previous is None:
                    continue
                quote = native_row_quote(raw, row)
                if not quote or (raw_source and quote not in raw_source):
                    continue
                quote_pages = [page['page']]
                if continuation:
                    following, tail = continuation; tail_quote = native_row_quote(following['text'], tail)
                    start = raw_source.find(quote); end = raw_source.find(tail_quote, start + len(quote)) if tail_quote and start >= 0 else -1
                    if end < 0 or end + len(tail_quote) - start > 8000:
                        continue
                    quote = raw_source[start:end + len(tail_quote)]; quote_pages.append(following['page'])
                yoy = compact(row[layout['change']['index']]).removesuffix('%')
                if number(yoy) is None:
                    continue
                recomputed = (number(value) / number(previous) - 1) * 100 if number(previous) > 0 else None
                conflict = recomputed is not None and abs(number(yoy) - recomputed) > Decimal('0.06')
                source_metric=label+(compact(continuation[1][0]) if continuation else '')
                record = {**base, 'kind': 'financial_metric', 'metric': metric, 'source_metric': source_metric,
                    'entity': target, 'value': value, 'previous_value': previous, 'unit': unit, 'currency': currency,
                    'period': period, 'cutoff': cutoff, 'period_kind': 'interim' if interim else 'annual',
                    'yoy': yoy + '%', 'computed_yoy_pct': str(round(recomputed, 4)) if recomputed is not None else None,
                    'printed_yoy_conflict': conflict, 'page': page['page'], 'pages': quote_pages,
                    'evidence_quote': quote, 'original_offset': raw_source.find(quote) if raw_source else None,
                    'context_quote': unit_quote, 'statistical_scope': 'issuer_main_accounting_table',
                    'previous_value_basis': layout['previous']['basis'] or '原表所载',
                    'context': {'native_column_headers': headers, 'source_row_cells': row,
                                'continuation_label': continuation[1][0] if continuation else ''},
                    'mode': '发行人主要会计数据表原列；不外推法人单体、独立业务或银行流水验证'}
                before = layout['before']
                if before:
                    old = amount(row[before[0]['index']])
                    if old is None:
                        continue
                    record.update(previous_value_before_adjustment=old,
                                  previous_value_before_adjustment_period=str(year - 1) + '年度',
                                  previous_value_before_adjustment_basis='调整前原列，未用于本次同比计算')
                if len(layout['third']) == 1:
                    third = amount(row[layout['third'][0]['index']])
                    if third is not None:
                        record.update(third_value=third, third_period=str(year - 2) + '年度',
                                      third_value_comparable=not bool(layout['previous']['basis'] and
                                          layout['third'][0]['basis'] != layout['previous']['basis']))
                money_unit=(currency if currency!='未载' else '')
                record['fact'] = metric + '：本期' + money_unit + value + unit + '，上期' + money_unit + previous + unit
                if before:
                    record['fact'] += '（调整后）；上期调整前原列' + record['previous_value_before_adjustment'] + unit
                if record.get('third_value'):
                    record['fact'] += '；' + record['third_period'] + record['third_value'] + unit
                if record.get('third_value_comparable') is False:
                    record['comparability_note']='较早年度与调整后比较列的口径可比性尚未确认；保留原列数值，不据此给出连续两次年度比较分档。'
                    record['context']['comparability_note']=record['comparability_note']
                result.append(record)
    return result
