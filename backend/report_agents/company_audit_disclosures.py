"""Source-bound combined audit opinions and recorded goodwill impairments."""
import re
from datetime import date
from decimal import Decimal

from .company_text import OriginalTextView,match_compact

DAY=r'20\d{2}年\d{1,2}月\d{1,2}日'
NUMBER=r'\d[\d,]*(?:\.\d+)?'


def _view(page):
    view=OriginalTextView(page['text'])
    positions=[i for i,c in enumerate(view.text) if not c.isspace()]
    flat=''.join(view.text[i] for i in positions)
    def quote(start,end):return view.quote(positions[start],positions[end-1]+1) if start<end else ''
    return flat,quote


def _day(value):
    m=re.fullmatch(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',value)
    if not m:return ''
    try:return date(*(int(x) for x in m.groups())).isoformat()
    except ValueError:return ''


def _audit_addressee(flat,target):
    if not target:return False
    return bool(re.search(r'独立(?:注册公众)?会计师(?:事务所)?报告|独立核数师报告',flat[:350])
        and re.search(r'致'+re.escape(match_compact(target))+r'(?:董事会|全体股东|股东)',flat[:650].casefold()))


def combined_control_rows(pages,target,base):
    records=[]
    for page in pages:
        flat,quote=_view(page)
        if not _audit_addressee(flat,target):continue
        heading=re.search(r'关于财务报表及财务报告内部控制之意见',flat)
        if not heading:continue
        end=re.search(r'形成审计意见的基础|财务报告内部控制的定义',flat[heading.end():])
        stop=heading.end()+end.start() if end else min(len(flat),heading.end()+2200)
        for m in re.finditer(r'我们认为[^。]{5,650}。',flat[heading.end():stop]):
            text=m[0]
            if '财务报告内部控制' not in text:continue
            state=('ineffective' if re.search(r'未能?在所有重大方面保持有效|财务报告内部控制无效',text)
                else 'qualified' if re.search(r'除.{1,120}外.{1,120}有效',text)
                else 'effective' if '在所有重大方面保持了有效的财务报告内部控制' in text else None)
            dt=re.search(r'于('+DAY+r')',text)
            if not state or not dt or not _day(dt[1]):continue
            original=quote(heading.end()+m.start(),heading.end()+m.end())
            records.append({**base,'kind':'internal_control_opinion','cutoff':_day(dt[1]),'state':state,
                'page':page['page'],'period':_day(dt[1])+'财务报告内控','fact':original,'evidence_quote':original,
                'opinion_format':'combined_auditor_report','mode':'年报所载内控审计意见；不扩展为全部非财务控制或团队能力评价'})
    return records


def goodwill_impairment_rows(pages,target,base):
    rows=[];ordered=sorted(pages,key=lambda p:p['page']);views=[_view(p) for p in ordered]
    for i,page in enumerate(ordered):
        flat,quote=views[i]
        heading=re.search(r'关于[^。]{0,35}商誉减值评估',flat)
        if not heading:continue
        preceding=range(max(0,i-2),i+1)
        owner=next((j for j in preceding if _audit_addressee(views[j][0],target)
                   and all(ordered[k+1]['page']==ordered[k]['page']+1 for k in range(j,i))),None)
        if owner is None:continue
        scope=('审计报告原定义的公司及子公司合并范围' if '及其子公司' in views[owner][0][:900]
               else '审计报告原定义的目标主体范围')
        pattern=(r'截至(?P<date>'+DAY+r')止年度(?:本公司|本集团|贵公司)'
                 r'(?:确认|销录|录得|计提)(?:了)?(?:商誉)?减值(?:亏损|损失)(?:为)?'
                 r'(?P<currency>人民币|港元|美元)(?P<value>'+NUMBER+r')(?P<unit>百万元|千元|万元|亿元|元)[。；]')
        for m in re.finditer(pattern,flat[heading.end():]):
            dt=_day(m['date'])
            if not dt or Decimal(m['value'].replace(',',''))<=0:continue
            original=quote(heading.end()+m.start(),heading.end()+m.end())
            rows.append({**base,'kind':'goodwill_impairment_loss','stream':'战略布局','entity':target,
                'period':dt+'止年度','as_of':dt,'cutoff':dt,'page':page['page'],
                'value':m['value'],'currency':m['currency'],'unit':m['unit'],
                'statement_scope':scope,
                'fact':original,'evidence_quote':original,'audit_heading':quote(heading.start(),heading.end()),
                'mode':scope+'；审计报告关键事项列示的已确认年度商誉减值；非全部商誉余额、非现金付款',
                'stage_note':'该损失已包含在原财务报表，不再从已披露利润中重复扣减；不直接推断集团全部商誉已减值或流动性违约。'})
    return rows
