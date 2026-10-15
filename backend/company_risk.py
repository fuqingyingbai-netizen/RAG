"""Bounded company risk drilldown, driven by the scan rather than all 35 tools."""
import re

DETAIL_TOOLS=('get_judicial_documents','get_service_announcement','get_guarantee_info','get_stock_pledge_info')


def drilldown_tools(text):
    result=[]
    for line in text.splitlines():
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells)==3 and cells[1].isdigit() and int(cells[1])>0 and cells[2] in DETAIL_TOOLS:
            if cells[2] not in result:result.append(cells[2])
    return result


def document_requests(text,maximum=2):
    header=None;result=[];seen=set()
    for line in text.splitlines():
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        if '文书ID' in cells and '案号' in cells:header=cells;continue
        if not header or len(cells)!=len(header):continue
        row=dict(zip(header,cells));did=row.get('文书ID','');case=row.get('案号','')
        if not did or re.fullmatch(r'[-: ]+',did) or not case or did in seen:continue
        seen.add(did);result.append((case,did))
        if len(result)>=maximum:break
    return result
