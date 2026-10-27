"""Recover a ruled before/after table from PDF geometry, never from inference."""
from collections import Counter
from io import BytesIO
import hashlib
import os
import re

VERSION='company-comparison-grid-reading-order-v2-continuations'


def comparison_page(text):
    text=re.sub(r'\s+','',str(text))
    for match in re.finditer(r'修[订訂正]前.{0,500}?(?:修[订訂正]后|修訂後)',text):
        context=text[max(0,match.start()-1000):match.end()+1000]
        if re.search(r'章程|议事规则|議事規則|公司法|法定代表|注册资本|註冊資本',context):return True
    return False


def glyphs(text):
    return Counter(re.sub(r'\s+','',str(text)))


def grid_reading_text(page,native,*,continuation_headers=None):
    """Require all original glyphs and unambiguous vertical table regions."""
    tables=sorted(page.find_tables(),key=lambda t:(t.bbox[1],t.bbox[0]))
    if not tables:return None,'no_vector_grid'
    pieces=[];literal=[];extracted=[];cursor=page.bbox[1]
    x0,_,x1,y1=page.bbox
    for table_index,table in enumerate(tables):
        left,top,right,bottom=table.bbox
        if top<cursor:return None,'overlapping_table_regions'
        rows=table.extract()
        if not rows or max(map(len,rows),default=0)<2:return None,'missing_columns'
        head=''.join(str(c or '') for c in rows[0])
        explicit=comparison_page(head+'章程')
        if not explicit and (not continuation_headers or table_index!=0 or
                             len(continuation_headers)!=max(map(len,rows),default=0)):
            return None,'unbound_comparison_columns'
        # Text beside a grid could change its interpretation if moved above
        # or below it. Preserve the original stream instead of guessing order.
        if any(top<(c['top']+c['bottom'])/2<bottom and
               not left<=(c['x0']+c['x1'])/2<=right and str(c.get('text','')).strip()
               for c in page.chars):return None,'text_beside_grid'
        before=page.crop((x0,cursor,x1,top)).extract_text() if top>cursor else ''
        before=before or '';pieces.append(before);literal.append(before)
        normalized=[[str(c) if c is not None else '' for c in row] for row in rows]
        literal.extend(c for row in normalized for c in row)
        lines=[]
        # A repeated header is a layout binding to an earlier physical page,
        # not a new company fact. Only the native cells enter the glyph check.
        if not explicit:
            lines=['| '+' | '.join(continuation_headers)+' |',
                   '| '+' | '.join('---' for _ in continuation_headers)+' |']
        for index,row in enumerate(normalized):
            lines.append('| '+' | '.join(re.sub(r'\s+',' ',c).strip() for c in row)+' |')
            if index==0 and explicit:lines.append('| '+' | '.join('---' for _ in row)+' |')
        pieces.append('\n'.join(lines));extracted.append(normalized);cursor=bottom
    after=page.crop((x0,cursor,x1,y1)).extract_text() if cursor<y1 else ''
    after=after or '';pieces.append(after);literal.append(after)
    if glyphs(''.join(literal))!=glyphs(native):return None,'glyph_inventory_mismatch'
    return {'text':'\n'.join(p for p in pieces if p),'tables':extracted},''


def column_edges(table,width):
    """Use all ruled cells, including merged ones, rather than their values."""
    values=sorted({edge for cell in getattr(table,'cells',[]) for edge in (cell[0],cell[2])})
    edges=[]
    for value in values:
        if not edges or abs(value-edges[-1]*width)>1:edges.append(value/width)
    return edges


def continuation_layout(page,table,binding):
    if not binding or page.page_number!=binding['last_page']+1:return False
    x0,y0,x1,y1=page.bbox;width=x1-x0;height=y1-y0
    if binding['bottom_fraction']<0.86 or (table.bbox[1]-y0)/height>0.20:return False
    edges=column_edges(table,width)
    if len(edges)!=len(binding['column_edges']) or len(edges)<3:return False
    if any(abs(a-b)>0.002 for a,b in zip(edges,binding['column_edges'])):return False
    # A new caption before an identically sized grid starts a different table.
    before=page.crop((x0,y0,x1,table.bbox[1])).extract_text() or ''
    if not before.strip() or re.fullmatch(r'\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*',before):return True
    lines=[re.sub(r'\s+','',line) for line in before.splitlines() if line.strip()]
    return bool(lines) and all(line in binding.get('running_headers',[]) for line in lines)


def recover_comparison_pages(payload,pages):
    selected=[p['page'] for p in pages if comparison_page(p['text'])]
    result={'version':VERSION,'method':'pdf_vector_grid_reading_order',
            'source_sha256':hashlib.sha256(payload).hexdigest(),
            'selected_pages':selected,'processed_pages':[],'recovered_pages':[],'pending_pages':[],'failures':[]}
    if not selected:return result
    try:maximum=max(1,min(100,int(os.getenv('COMPANY_PDF_COMPARISON_MAX_PAGES','100'))))
    except (ValueError,TypeError):maximum=100
    try:
        import pdfplumber
        by_page={p['page']:p for p in pages}
        binding=None;anchors=set(selected)
        result['continuation_headers']={}
        with pdfplumber.open(BytesIO(payload)) as document:
            for page in document.pages:
                number=page.page_number
                if number not in by_page:
                    binding=None;page.close();continue
                explicit=number in anchors
                if not explicit and (not binding or number!=binding['last_page']+1):
                    page.close();continue
                if len(result['processed_pages'])>=maximum:
                    if explicit or binding:
                        selected.append(number) if number not in selected else None
                        result['failures'].append({'page':number,'reason':'comparison_page_budget'})
                        if binding:binding={**binding,'last_page':number}
                    page.close();continue
                try:tables=page.find_tables()
                except Exception as exc:
                    if explicit:result['failures'].append({'page':number,'reason':type(exc).__name__})
                    binding=None;page.close();continue
                inherited=bool(tables and continuation_layout(page,tables[0],binding))
                if not explicit and not inherited:
                    binding=None;page.close();continue
                if number not in selected:selected.append(number)
                record=by_page[number]
                result['processed_pages'].append(page.page_number)
                headers=binding['headers'] if inherited else None
                header_page=binding['header_page'] if inherited else number
                try:recovered,error=grid_reading_text(page,record['text'],continuation_headers=headers)
                except Exception as exc:recovered=None;error=type(exc).__name__
                if recovered:
                    record['native_stream_text']=record['text']
                    record.update(recovered,text_origin='pdf_vector_grid_reading_order',
                                  reading_order_version=VERSION,reading_order_glyph_inventory='unchanged')
                    result['recovered_pages'].append(page.page_number)
                    if inherited:
                        record['comparison_header_binding']={'physical_page':header_page,'headers':headers}
                        result['continuation_headers'][str(number)]=record['comparison_header_binding']
                else:result['failures'].append({'page':page.page_number,'reason':error})
                # A text extraction failure must remain pending, but does not
                # erase a geometrically verified column binding for later pages.
                binding=None
                if tables and (recovered or error=='glyph_inventory_mismatch'):
                    table=tables[-1];rows=table.extract()
                    if rows and comparison_page(''.join(str(c or '') for c in rows[0])+'章程'):
                        headers=[re.sub(r'\s+',' ',str(c or '')).strip() for c in rows[0]]
                        header_page=number
                    elif len(tables)!=1:headers=None
                    edges=column_edges(table,page.bbox[2]-page.bbox[0])
                    if headers and len(edges)==len(headers)+1:
                        before=page.crop((page.bbox[0],page.bbox[1],page.bbox[2],tables[0].bbox[1])).extract_text() or ''
                        running=[re.sub(r'\s+','',line) for line in before.splitlines()[:2]
                                 if 2<len(re.sub(r'\s+','',line))<=100]
                        binding={'last_page':number,'header_page':header_page,'headers':headers,
                                 'column_edges':edges,'running_headers':running,
                                 'bottom_fraction':(table.bbox[3]-page.bbox[1])/(page.bbox[3]-page.bbox[1])}
                page.close()
    except Exception as exc:result['error_type']=type(exc).__name__
    result['selected_pages']=sorted(set(selected))
    result['pending_pages']=sorted(set(selected)-set(result['recovered_pages']))
    return result
