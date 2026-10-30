"""Build a local source-review entry point bound to exact report/corpus hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from person_provenance import stable_id
from replay_person_chapters import generation_code_snapshot

HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>人物证据复核</title><style>
:root{font-family:"Microsoft YaHei",system-ui,sans-serif;color:#233142;background:#f4f6f9}*{box-sizing:border-box}body{margin:0}header{background:#13283f;color:white;padding:24px 30px}h1{font-size:24px;margin:0 0 10px}header p{margin:5px 0;color:#dce5ef;font-size:14px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;padding:18px 24px;border-bottom:1px solid #d6dfe8;background:white}input,select,textarea,button{font:inherit;padding:9px;border:1px solid #b7c5d4;border-radius:5px}input[type=search]{min-width:230px;flex:1}button{background:#edf3fa;color:#173b60;cursor:pointer}button.primary{background:#1764a1;color:white;border-color:#1764a1}main{display:grid;grid-template-columns:340px minmax(0,1fr);gap:20px;padding:22px}aside{max-height:calc(100vh - 240px);overflow:auto}aside,article{background:white;border:1px solid #dce4ed;border-radius:8px;padding:16px;min-width:0}.item{width:100%;text-align:left;margin:0 0 8px;background:#f6f8fc;word-break:break-word}.item.active{border:2px solid #1764a1;background:#edf5fc}.item small{display:block;color:#61758b;margin-top:5px}.pagination{display:flex;align-items:center;gap:9px;margin-top:12px}h2{font-size:19px;margin-top:0}h3{font-size:15px;margin-top:22px;color:#32506f}pre{font:14px/1.8 "Microsoft YaHei",system-ui,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px;border-radius:6px;max-height:480px;overflow:auto;margin:8px 0}mark{background:#ffe3a3}dl{display:grid;grid-template-columns:105px 1fr;gap:8px;font-size:14px}dt{color:#61758b}dd{margin:0;overflow-wrap:anywhere}textarea{width:100%;min-height:100px;resize:vertical}label{display:block;margin:12px 0 6px}.notice{background:#fff4d8;color:#6e4a0b;padding:12px;border-radius:5px;font-size:14px;line-height:1.65}.status{padding:10px 24px;font-size:14px;color:#36516c}#message{color:#a04412}a{color:#1764a1}.empty{padding:20px;color:#61758b}@media(max-width:850px){main{grid-template-columns:1fr;padding:12px}header{padding:20px}aside{max-height:330px;overflow:auto}dl{grid-template-columns:95px 1fr}.toolbar{padding:12px}}
</style><header><h1 id="heading"></h1><p>来源、身份、时间与采用去向复核工作台</p><p>当前报告未通过整体验收；本页勾选不自动批准报告，不自动产生个人信用或责任结论。</p></header>
<div class="toolbar"><input type="search" id="query" placeholder="搜索原文、人物、机构或证据编号" aria-label="搜索证据"><select id="chapter" aria-label="按章节筛选"><option value="">全部章节及未分配材料</option></select><select id="filter" aria-label="按复核状态筛选"><option value="all">全部状态</option><option value="pending">仅待复核</option><option value="reviewed">已填写复核</option></select><button class="primary" id="export">导出本次复核 JSON</button><button id="import">导入同版本复核</button><input id="file" type="file" accept="application/json" hidden></div>
<div class="status" id="counts"></div><div class="status" id="message" role="status"></div><main><aside><div id="list"></div><div class="pagination"><button id="previous">上一页</button><span id="page"></span><button id="next">下一页</button></div></aside><article id="detail"></article></main>
<script id="bundle" type="application/json">__BUNDLE__</script><script>
'use strict';const data=JSON.parse(document.getElementById('bundle').textContent);const entries=data.entries;const key='person-review:'+data.binding.report_sha256+':'+data.binding.source_sha256+':'+data.binding.index_code_sha256;let notes={},page=0,selected=null;try{notes=JSON.parse(localStorage.getItem(key)||'{}')}catch{}const statuses=['待复核','片段已核对','身份待补证','归属不符','时间待补证','需追查相反证据','暂不采用（须说明理由）'];
const el=id=>document.getElementById(id);const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node};el('heading').textContent=data.target_name+' · 人物证据复核';for(let n=1;n<=15;n++){const o=make('option','第'+n+'章');o.value=String(n);el('chapter').append(o)}
function filtered(){const q=el('query').value.trim().toLowerCase(),chapter=el('chapter').value,state=el('filter').value;return entries.filter(r=>(!q||JSON.stringify(r).toLowerCase().includes(q))&&(!chapter||(r.chapter_candidates||[]).includes(Number(chapter)))&&(state==='all'||(state==='pending'?!notes[r.id]||notes[r.id].status==='待复核':notes[r.id]&&notes[r.id].status!=='待复核')))}
function render(){const rows=filtered(),pages=Math.max(1,Math.ceil(rows.length/25));page=Math.min(page,pages-1);if(!rows.some(r=>r.id===selected)){selected=rows[0]?.id||null;if(rows[0])show(rows[0]);else el('detail').replaceChildren(make('div','此筛选条件没有复核材料。'))}el('list').replaceChildren();for(const r of rows.slice(page*25,(page+1)*25)){const b=make('button');b.className='item'+(selected===r.id?' active':'');b.dataset.record=r.id;b.append(make('strong',r.evidence_id||r.kind),make('div',(r.statement||r.title||'无可提取片段').slice(0,90)),make('small',(notes[r.id]?.status||'待复核')+' · '+(r.subject_scope||'来源待核验')));b.onclick=()=>{selected=r.id;show(r);render()};el('list').append(b)}if(!rows.length)el('list').append(make('div','此筛选条件没有条目。'));el('page').textContent=(page+1)+' / '+pages;el('previous').disabled=page===0;el('next').disabled=page+1>=pages;el('counts').textContent='全部 '+entries.length+' 条 · 筛选后 '+rows.length+' 条 · 已填写 '+Object.values(notes).filter(n=>n.status!=='待复核').length+' 条 · 未核验不等于无风险';}
function show(r){const box=el('detail');box.replaceChildren(make('h2',r.evidence_id||'保留来源待提取'),make('p',r.title||''));const notice=make('div',r.attribution_boundary||'本条为来源陈述，尚未独立核实；片段与原文一致不等于结论成立。');notice.className='notice';box.append(notice);const dl=make('dl');for(const [label,value]of [['主体/归属',(r.subject||'未明确')+' / '+(r.subject_scope||'未解决')],['事件/有效时间',JSON.stringify(r.effective_time||{})],['文档发布日期',r.document_published_at||'未记录'],['采集日期',r.collected_at||'未记录'],['章节候选',(r.chapter_candidates||[]).join('、')||'未分配'],['原文定位',JSON.stringify(r.locators||[])],['当前索引版本',data.binding.index_code_sha256.slice(0,16)]]){dl.append(make('dt',label),make('dd',value))}box.append(dl);if((r.source_url||'').startsWith('https://') || (r.source_url||'').startsWith('http://')){const a=make('a','打开原始来源网页');a.href=r.source_url;a.target='_blank';a.rel='noopener noreferrer';box.append(a)}box.append(make('h3','保留片段'),make('pre',r.statement||'尚未形成合格片段，需查看完整原文及身份锚点。'));const docs=(r.document_ids||[]).map(id=>data.documents[id]).filter(Boolean);for(const d of docs){const details=make('details');details.append(make('summary','展开完整原文 · '+d.document_id));const pre=make('pre'),loc=(r.locators||[]).find(l=>l.document_id===d.document_id&&l.match==='exact');if(loc){pre.append(document.createTextNode(d.content.slice(0,loc.start_char)),make('mark',d.content.slice(loc.start_char,loc.end_char)),document.createTextNode(d.content.slice(loc.end_char)))}else pre.textContent=d.content||'原文未取得';details.append(pre);box.append(details)}const label=make('label','本条复核状态（本地暂存，导出后可留档）');const select=make('select');select.id='review-state';for(const s of statuses){const o=make('option',s);o.value=s;select.append(o)}select.value=notes[r.id]?.status||'待复核';const area=make('textarea');area.id='review-notes';area.placeholder='记录原文位置、身份锚点、相反材料和采用/不采用理由。';area.value=notes[r.id]?.reason||'';const save=make('button','保存本条复核');save.className='primary';save.onclick=()=>{if(select.value==='暂不采用（须说明理由）'&&area.value.trim().length<8){el('message').textContent='暂不采用需填写具体理由，不能只写字数或预算不足。';return}notes[r.id]={status:select.value,reason:area.value,updated_at:new Date().toISOString()};localStorage.setItem(key,JSON.stringify(notes));el('message').textContent='已在此浏览器本地保存；请导出 JSON 留档。此操作未批准整份报告。';render()};box.append(label,select,make('label','复核依据与理由'),area,save);}
function exportReview(){const value={schema:'person-manual-review-v1',binding:data.binding,target_name:data.target_name,report_accepted:false,review_notes:notes};const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=make('a');a.href=url;a.download='person-review-'+data.binding.report_sha256.slice(0,12)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
el('export').onclick=exportReview;el('import').onclick=()=>el('file').click();el('file').onchange=async()=>{try{const v=JSON.parse(await el('file').files[0].text());if(v.schema!=='person-manual-review-v1'||!Object.keys(data.binding).every(k=>v.binding?.[k]===data.binding[k]))throw Error('报告、语料或索引版本不一致，拒绝导入。');const ids=new Set(entries.map(r=>r.id));for(const[id,n]of Object.entries(v.review_notes||{})){if(!ids.has(id)||!statuses.includes(n.status))throw Error('复核条目或状态不合法。')}notes=v.review_notes||{};localStorage.setItem(key,JSON.stringify(notes));render();el('message').textContent='已导入同版本复核；整份报告仍需独立验收。'}catch(e){el('message').textContent=e.message}};for(const id of ['query','chapter','filter'])el(id).oninput=()=>{page=0;render()};el('previous').onclick=()=>{page--;render()};el('next').onclick=()=>{page++;render()};const initial=entries.find(r=>r.id===location.hash.slice(1)||r.evidence_id===location.hash.slice(1))||entries[0];if(initial){selected=initial.id;show(initial)}else el('detail').append(make('div','没有复核材料。'));render();
</script></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True, type=Path)
    ap.add_argument('--contract', required=True, type=Path)
    ap.add_argument('--report', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    source_bytes = (args.corpus / 'source-snapshots.json').read_bytes()
    sources = json.loads(source_bytes)
    contract = json.loads(args.contract.read_text(encoding='utf-8'))
    index = contract['provenance_index']
    originals = {}
    for s in sources:
        content = str(s.get('content') or '')
        doc_id = stable_id('DOC', {'url': s['url'], 'content': content})
        originals[doc_id] = {'document_id': doc_id, 'content': content}
    facts = {f['evidence_id']: f for f in contract['facts']}
    entries = []
    for obs in [*index['observations'], *index['quarantine']]:
        fact = facts.get(obs.get('evidence_id'), {})
        entries.append({'id': obs['observation_id'], **obs,
            'title': fact.get('source_title') or '',
            'attribution_boundary': fact.get('attribution_boundary') or '',
            'document_ids': list(dict.fromkeys(l['document_id'] for l in obs['locators'] if l['document_id'] in originals))})
    for doc in index['documents']:
        if doc['observations'] or doc['rejected_statements']:
            continue
        entries.append({'id': doc['document_id'], 'kind': '来源待提取/待核验', 'title': doc['title'],
            'source_url': doc['url'], 'statement': '', 'chapter_candidates': [],
            'attribution_boundary': doc['identity_reason'] or '来源保留不等于已有合格人物事实。',
            'document_ids': [doc['document_id']], 'locators': []})
    code = generation_code_snapshot()
    bundle = {'target_name': contract['target_name'], 'report_accepted': False,
        'binding': {'report_sha256': hashlib.sha256(args.report.read_bytes()).hexdigest(),
            'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
            'index_code_sha256': hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest()},
        'entries': entries, 'documents': originals}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(bundle, ensure_ascii=False).replace('<', chr(92)+'u003c').replace('>', chr(92)+'u003e').replace('&', chr(92)+'u0026')
    args.output.write_text(HTML.replace('__BUNDLE__', encoded), encoding='utf-8')
    manifest = {'html': str(args.output.resolve()), 'entry_count': len(entries),
        'binding': bundle['binding'], 'report_accepted': False,
        'boundary': 'Local review UI; no report approval or fabricated reviewer result.'}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
