"""Read back real saved report/evidence/Word objects without model calls."""
import argparse,hashlib,json,re,sqlite3,sys,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
from report_agents.company_evidence import source_body


def sha(value):return hashlib.sha256(value).hexdigest()
def compact(value):return re.sub(r'\s+','',value)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--directory',required=True);ap.add_argument('--company',required=True)
    args=ap.parse_args();directory=(ROOT/'work'/args.directory).resolve()
    db=sqlite3.connect((directory/'research.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    row=db.execute("SELECT * FROM research_artifacts WHERE artifact_type='desktop_report' ORDER BY id DESC LIMIT 1").fetchone()
    meta=json.loads(row['artifact_metadata']);report=row['content'];store=directory/'objects'
    assert (store/row['object_key']).read_text(encoding='utf-8')==report
    sources={str(r['id']):dict(r) for r in db.execute('SELECT * FROM research_sources')}
    for source in sources.values():source['source_metadata']=json.loads(source['source_metadata'] or '{}')
    native=meta.get('company_source_review_evidence',{});checks=[]
    for fact in native.get('facts',[]):
        source=sources[fact['source_id']];raw=source_body(source)[0]
        assert sha(raw.encode())==fact['original_sha256']
        assert raw[fact['original_offset']:fact['original_end']]==fact['fact']
        checks.append({'source_id':fact['source_id'],'chapter':fact['chapter'],'original_sha256':fact['original_sha256'],
            'quote_sha256':sha(fact['fact'].encode()),'start':fact['original_offset'],'end':fact['original_end']})
    def artifact(kind):
        value=db.execute('SELECT content FROM research_artifacts WHERE artifact_type=? ORDER BY id DESC LIMIT 1',(kind,)).fetchone()
        return json.loads(value[0]) if value else {}
    editorial=artifact('company_editorial');usage=artifact('company_information_usage')
    payload=(store/meta['docx_object_key']).read_bytes()
    assert sha(payload)==meta['docx_sha256']
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(store/meta['docx_object_key']) as archive:
        xml=ET.fromstring(archive.read('word/document.xml'))
        word=''.join(t.text or '' for t in xml.findall('.//w:t',ns))
        bookmarks=[b.get('{'+ns['w']+'}name') for b in xml.findall('.//w:bookmarkStart',ns)]
    missing_report=[];missing_word=[]
    for finding in editorial.get('findings',[]):
        # Main prose must survive save and actual OOXML, including limitations.
        text=compact(finding['text'])
        if text not in compact(report):missing_report.append(finding['finding_id'])
        if text not in compact(word):missing_word.append(finding['finding_id'])
    assert not missing_report and not missing_word,(missing_report,missing_word)
    result=json.loads((directory/'result.json').read_text(encoding='utf-8'))
    outcome={'company':args.company,'scope':'One retained frozen source through real ResearchWorkflow; not complete-company due diligence acceptance',
        'report_artifact_id':row['id'],'report_version':row['version'],'report_chars':len(report),'report_sha256':sha(report.encode()),
        'saved_object_equals_database':True,'native_selections':checks,'source_count':len(sources),
        'source_reading':{sid:{k:s.get(k) for k in ('state','review_windows','reviewed_windows','accepted_claims','reading_scope','unread_ranges','structural_gaps')} for sid,s in native.get('source_review',{}).items()},
        'editorial':editorial.get('diagnostic',{}),'usage':usage.get('diagnostic',{}),'main_findings_in_database_and_word':len(editorial.get('findings',[])),
        'docx_sha256':sha(payload),'docx_bookmarks':len(bookmarks),'docx_native_hyperlinks':meta.get('docx_native_hyperlinks'),
        'docx_integrity_status':meta.get('docx_integrity_status'),'docx_render_status':meta.get('docx_render_status'),
        'docx_layout_status':meta.get('docx_layout_status'),'docx_render_page_count':meta.get('docx_render_page_count'),
        'pdf_sha256':sha((store/meta['pdf_object_key']).read_bytes()) if meta.get('pdf_object_key') else None,
        'delivery_status':meta.get('delivery_status'),'delivery_ready':meta.get('company_delivery_contract',{}).get('delivery_ready'),
        'document_review_status':meta.get('company_document_review',{}).get('status'),
        'document_review_issues':meta.get('company_document_review',{}).get('issues'),
        'summary_status':meta.get('company_summary_diagnostic',{}),'metrics':result.get('metrics'),
        'seconds_this_invocation':result.get('seconds_this_invocation'),'model':result.get('model'),'base_url':result.get('base_url'),
        'search_queries':result.get('metrics',{}).get('search_queries'),'platform_requests':result.get('metrics',{}).get('platform_requests'),
        'code_sha256':{k:v for k,v in result.get('code_sha256',{}).items() if k.replace('\\','/').startswith(('backend/company_','backend/report_agents/company_')) or k.replace('\\','/') in {'backend/research_workflow.py','backend/docx_exporter.py','backend/research_api.py'}},
        'runtime_files_changed_since_invocation':[k for k,v in result.get('code_sha256',{}).items()
            if not (ROOT/k).is_file() or sha((ROOT/k).read_bytes())!=v]}
    out=ROOT/'docs/deliverables/company-recovery-20261104'/(args.company+'-real-saved-readback.json')
    out.write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:outcome[k] for k in ('company','report_artifact_id','main_findings_in_database_and_word','docx_integrity_status','docx_render_status','delivery_status')}))
    db.close()


if __name__=='__main__':main()
