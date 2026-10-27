"""Package complete, currently passing person reports; partial samples are rejected."""
import argparse,hashlib,html,json,re,shutil,sys
from pathlib import Path
import mistune
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from person_evidence import split_sections
from person_material_accounting import build_accounting,delivery_gate
from replay_person_chapters import generation_code_snapshot
from build_person_prose_rerun import metrics

CSS='''body{margin:0;background:#f3f5f3;color:#183129;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:32px 20px 80px}h1{font-size:32px;line-height:1.3}h2{margin-top:2em;border-bottom:1px solid #d8e1dc;padding-bottom:8px}a{color:#17664b;overflow-wrap:anywhere}article,.card{background:white;padding:28px;border-radius:16px;margin:20px 0;min-width:0}.muted{color:#62746a}.badge{display:inline-block;background:#dceee3;border-radius:20px;padding:3px 12px}blockquote{margin:12px 0;padding:8px 18px;background:#f3f7f3;border-left:3px solid #91b09e;overflow-wrap:anywhere}.scroll{max-width:100%;overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #dce4de;padding:8px 10px;min-width:100px;vertical-align:top}th{background:#edf3ee}pre{white-space:pre-wrap;overflow-wrap:anywhere}nav{display:flex;gap:16px;flex-wrap:wrap}article{overflow-wrap:anywhere}details{margin:16px 0}summary{cursor:pointer;font-weight:600}@media(max-width:600px){main{padding:20px 12px 50px}article,.card{padding:18px}h1{font-size:26px}}'''
BASE_SCRIPT="""<script>if((location.protocol==='https:'||location.protocol==='http:')&&!location.pathname.endsWith('/')&&!location.pathname.endsWith('.html')){history.replaceState(null,'',location.pathname+'/'+location.search+location.hash);}</script>"""

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def page(title,body):
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title>'+BASE_SCRIPT+'<style>'+CSS+'</style></head><body><main>'+body+'</main></body></html>'


def render_markdown(text,eids,annex=False):
    rendered=mistune.create_markdown(escape=True,plugins=['table','url'])(text)
    rendered=rendered.replace('<table>','<div class="scroll"><table>').replace('</table>','</table></div>')
    if annex:
        rendered=re.sub(r'<h2>(E-[A-Z0-9-]+)</h2>',lambda m:'<h2 id="'+m[1]+'">'+m[1]+'</h2>',rendered)
    else:
        rendered=re.sub(r'\[(E-[A-Z0-9-]+)\]',lambda m:'<a href="appendix.html#'+m[1]+'">['+m[1]+']</a>' if m[1] in eids else m[0],rendered)
    return rendered


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runs',nargs='+',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);args=ap.parse_args()
    out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);cards=[];cases=[]
    for i,run in enumerate(args.runs,1):
        run=run.resolve();summary=read(run/'summary.json');contract=read(run/'contract.json');audit=read(run/'audit.json')
        assert summary['code_unchanged_during_run'] is True and read(run/'generation-code-snapshot.json')==generation_code_snapshot()
        assert summary['runner_sha256']==hashlib.sha256((ROOT/'scripts/run_person_content_acceptance.py').read_bytes()).hexdigest()
        assert hashlib.sha256((Path(summary['baseline'])/'source-snapshots.json').read_bytes()).hexdigest()==summary['sources_sha256']
        report=(run/'desktop_report.md').read_text(encoding='utf-8');sections=split_sections(report)
        accounting,annex=build_accounting(report,contract,audit['section_diagnostics'])
        gate=delivery_gate(report,contract,audit['section_diagnostics'],accounting,audit['errors'])
        assert audit['automatic_delivery_status']=='passed' and gate['status']=='passed',('Full report not deliverable',gate)
        assert all(n in sections for n in range(1,16))
        assert annex==(run/'evidence-appendix.md').read_text(encoding='utf-8')
        folder=out/f'report-{i}';folder.mkdir()
        for filename in ['desktop_report.md','evidence-appendix.md','audit.json','acceptance-results.json']:
            shutil.copyfile(run/filename,folder/filename)
        chapters=[]
        for n in range(2,13):
            p=contract['chapters'][str(n)];m=metrics(sections[n],p)
            assert m['analysis_chars']<=600 and m['displayed_original_chars']<=1600
            material=audit['section_diagnostics'][str(n)].get('content_acceptance',{}).get('material_diagnosis',{})
            chapters.append({'chapter':n,'title':p['title'],'metrics':m,'material_status':material.get('status'),
                'material_counts':material.get('counts',{}),'material_input_records':material.get('input_records')})
        target=contract['target_name'];eids={r['evidence_id'] for r in contract['facts']}
        nav='<nav><a href="../index.html">返回总目录</a><a href="desktop_report.md">报告原文件</a><a href="appendix.html">完整原文及采用去向</a><a href="audit.json">验收依据</a></nav>'
        soup=BeautifulSoup(render_markdown(report,eids),'html.parser');toc=[]
        for n in range(1,16):
            label=sections[n].splitlines()[0].lstrip('#').strip()
            heading=next(h for h in soup.find_all('h2') if h.get_text().strip()==label and not h.find_parent('blockquote'))
            heading['id']=f'chapter-{n}'
            toc.append('<a href="#chapter-'+str(n)+'">'+html.escape(label)+'</a>')
        contents='<details open><summary>章节目录</summary><nav>'+''.join(toc)+'</nav></details>'
        (folder/'index.html').write_text(page(target+'研究报告',nav+'<article>'+contents+str(soup)+'</article>'+nav),encoding='utf-8')
        appendix_nav=nav+'<p><a href="index.html">返回本份报告</a></p>'
        (folder/'appendix.html').write_text(page(target+'原文与采用去向',appendix_nav+'<article>'+render_markdown(annex,eids,annex=True)+'</article>'+appendix_nav),encoding='utf-8')
        row={'target_name':target,'folder':folder.name,'source_snapshot_sha256':summary['sources_sha256'],
            'implementation_version':audit['version'],'delivery_gate':gate,'qualified_records':len(contract['facts']),
            'source_urls':len({f['source_url'] for f in contract['facts']}),'material_accounting':{k:v for k,v in accounting.items() if k not in ['records','excluded_records']},
            'chapters':chapters,'report_sha256':hashlib.sha256((run/'desktop_report.md').read_bytes()).hexdigest(),
            'appendix_sha256':hashlib.sha256((run/'evidence-appendix.md').read_bytes()).hexdigest()}
        cases.append(row)
        labels={'analysis':'正文分析','table':'资料表','table_reference':'跨章专业表引用','source_display':'来源原文','appendix':'补充附录','corroborating_appendix':'佐证附录','missing':'待补','pending':'待核'}
        table=''.join('<tr><td>'+str(c['chapter'])+' '+html.escape(c['title'])+'</td><td>'+str(c['metrics']['analysis_chars'])+'</td><td>'+str(c['metrics']['displayed_original_chars'])+'</td><td>'+html.escape('、'.join(labels.get(k,k)+' '+str(v)+'条' for k,v in c['material_counts'].items()))+'</td></tr>' for c in chapters)
        cards.append('<section class="card"><h2>'+html.escape(target)+'</h2><p class="badge">全报告自动验收通过</p><p>合格记录 '+str(row['qualified_records'])+' 条，来自 '+str(row['source_urls'])+' 个网址；完整原文全部保留。记录数不代表独立消息源数。</p><nav><a href="'+folder.name+'/index.html">阅读完整报告</a><a href="'+folder.name+'/appendix.html">查看原文与采用去向</a></nav><details><summary>全部正文章节的验收统计</summary><div class="scroll"><table><tr><th>章节</th><th>分析字符</th><th>原文字符</th><th>材料去向</th></tr>'+table+'</table></div></details></section>')
    write(out/'metrics.json',{'scope':'Complete reports with fresh final whole-report gates; no independent source authentication claim.','cases':cases,'browser_visual_qa':'not_performed'})
    body='<h1>人物研究报告交付汇总</h1><p class="muted">完整报告、原始材料与逐章采用去向</p><section class="card"><p>本包仅收录通过当前完整报告验收的结果。检查覆盖来源支持、语义、材料采用、旧事项保留与章节篇幅；公开来源及报告所列限制仍适用。</p><p>正文分析每章不超过600字符，代表性原文不超过1600字符。专业资料表和完整来源附录另行保留；附录保留不等于正文分析采用。</p></section>'+''.join(cards)+'<p class="muted">仅作静态文件及引用核验，未进行浏览器视觉验收。外部来源链接联网访问；页面阅读不依赖外部运行资源。</p>'
    (out/'index.html').write_text(page('人物研究报告交付汇总',body),encoding='utf-8')
    print(json.dumps({'output':str(out),'complete_reports':len(cases)},ensure_ascii=False))


if __name__=='__main__':main()
