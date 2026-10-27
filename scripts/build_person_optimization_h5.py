"""Package the archived two-person comparisons as a standalone static H5."""
from pathlib import Path
import html
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'deliverables/person-report-quality-20261021'
OUT = ROOT / 'deliverables/person-optimization-h5-20261023/dist'
H = html.escape

CSS = '''
:root{--ink:#192f42;--muted:#617587;--teal:#087f73;--line:#dae4ea;--bg:#f3f6f8}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:95px}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.8 "Microsoft YaHei",system-ui,sans-serif}a{color:var(--teal);text-decoration:none}a:hover{text-decoration:underline}button,select{font:inherit;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:8px;padding:7px 12px;cursor:pointer}a:focus-visible,button:focus-visible,select:focus-visible{outline:3px solid #dfaa40;outline-offset:4px}header{position:sticky;top:0;background:#fffffff5;border-bottom:1px solid var(--line);z-index:10}.bar{max-width:1460px;margin:auto;padding:13px 26px;display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{font-weight:750;letter-spacing:1px;color:var(--ink)}.tools{display:flex;gap:16px;align-items:center;flex-wrap:wrap;font-size:13px}.wrap{max-width:1200px;margin:auto;padding:38px 24px 60px}.hero{padding:45px 44px;background:#152f43;color:white;border-radius:20px;position:relative;overflow:hidden}.hero:after{content:'';position:absolute;width:210px;height:210px;border:42px solid #ffffff06;border-radius:50%;right:-60px;top:-70px;pointer-events:none}.eyebrow{text-transform:uppercase;font-size:11px;font-weight:700;letter-spacing:2px;color:#90d5c9}h1{font-size:clamp(29px,4vw,43px);line-height:1.35;margin:12px 0 16px;letter-spacing:-1px}.hero p{max-width:780px;color:#c8d8e2}.meta{font-size:12px;color:#9db9c9!important}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:22px 0 30px}.stat{padding:19px 22px;background:#fff;border:1px solid var(--line);border-radius:12px}.stat b{font-size:28px;display:block;line-height:1.5}.stat span,.muted{color:var(--muted);font-size:13px}.section-title{display:flex;justify-content:space-between;align-items:baseline;margin-top:34px}h2{font-size:23px;margin:0 0 15px}h3{font-size:18px}p{margin:9px 0}.cards{display:grid;grid-template-columns:1fr 1fr;gap:22px}.card,.panel{padding:28px;background:white;border:1px solid var(--line);border-radius:16px}.card .num{font-size:12px;letter-spacing:2px;color:#8195a3}.card h2{font-size:29px;margin:12px 0 0}.tags{color:var(--muted);margin-bottom:20px}.mini{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:18px 0;border-block:1px solid var(--line);margin:18px 0}.mini b{display:block;font-size:24px}.mini span{font-size:11px;color:var(--muted)}.cta{display:inline-block;background:var(--teal);color:white;border-radius:8px;padding:10px 18px;font-weight:650;margin-top:12px}.cta:hover{background:#07665d;text-decoration:none}.card ul{padding-left:20px;font-size:14px;min-height:105px}.panel{margin-top:24px}.notice{background:#fff8eb;border-left:3px solid #d4a14c;padding:18px 22px;margin-top:24px;border-radius:6px}.notice strong{color:#7c5925}.notice p{font-size:13px;color:#705f48}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:14px 0}th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}th{background:#edf3f5}footer{padding:25px 2px;color:var(--muted);font-size:12px}.layout{display:grid;grid-template-columns:215px minmax(0,1fr);gap:28px;max-width:1480px;margin:auto;padding:30px 24px 60px}aside{position:sticky;top:85px;align-self:start;max-height:calc(100vh - 105px);overflow:auto}aside a{display:block;padding:7px 10px;color:#607486;font-size:12px;border-radius:7px}aside a:hover,aside a.active{background:#dceee8;color:#07695e;text-decoration:none}aside span{color:#8ba49e;margin-right:8px}.chapter{padding:27px;background:white;border:1px solid var(--line);border-radius:16px;margin:22px 0;scroll-margin-top:85px}.chapter-top{display:flex;gap:16px;align-items:center}.number{font-size:32px;color:#91a7b4;border-right:1px solid var(--line);padding-right:16px;font-weight:300}.chapter h2{font-size:22px;margin:0}.note{background:#eaf5ef;padding:14px 18px;border-radius:8px;font-size:14px;margin:18px 0;color:#265d50}.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}.pane{min-width:0;overflow-wrap:anywhere;border:1px solid var(--line);border-radius:10px;overflow:hidden}.pane-label{padding:12px 16px;font-size:12px;letter-spacing:1px;font-weight:700;display:flex;justify-content:space-between;background:#f9eeea;color:#955d49}.after .pane-label{background:#e4f4ed;color:#126e59}.doc{padding:17px;font-size:13px;line-height:1.85;overflow:auto}.doc h2{font-size:19px;margin:12px 0}.doc h3{font-size:16px}.doc h4{font-size:14px}.doc table{font-size:12px;min-width:380px}.doc td{padding:7px}.doc blockquote{border-left:3px solid #c4d5d9;margin:14px 0;padding:9px 12px;background:#f4f7f8;white-space:pre-wrap;color:#506575}.doc code{white-space:pre-wrap}details{margin-top:15px}summary{cursor:pointer;color:var(--teal)}.fold-originals .doc blockquote{display:none}.reading-after .columns{grid-template-columns:1fr}.reading-after .before{display:none}.top-link{font-size:12px;display:block;text-align:right;margin-top:14px}.mobile-picker{display:none}.progress{height:3px;background:var(--teal);width:0}button[aria-pressed=true]{background:#e0eee9;color:#08695e}
@media(max-width:1050px){.layout{display:block}aside{display:none}.mobile-picker{display:block;margin:18px 0}.mobile-picker select{width:100%}.columns{grid-template-columns:1fr}.hero{padding:30px}.bar{padding:12px 18px}.tools{gap:10px}.chapter{padding:18px}}@media(max-width:650px){.wrap,.layout{padding:20px 14px 40px}.cards{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.stat{padding:14px}.hero{padding:26px 23px}.bar{align-items:flex-start}.tools{justify-content:flex-end}.tools a{font-size:12px}.card,.panel{padding:22px}.chapter h2{font-size:19px}.card ul{min-height:0}.pane-label{position:sticky;left:0}.section-title{display:block}.section-title p{font-size:12px}}@media print{header,aside,.tools,.mobile-picker,.top-link{display:none}.layout,.columns,.cards{display:block}.chapter{break-before:page;border:0;padding:0}.hero{background:#fff;color:#192f42}.hero p,.hero .eyebrow{color:#192f42}.doc blockquote{display:block!important}.pane{margin:18px 0}.reading-after .before{display:block}.notice{break-inside:avoid}}
'''

JS = '''
document.querySelectorAll('[data-toggle]').forEach(b=>b.addEventListener('click',()=>{const on=document.body.classList.toggle(b.dataset.toggle);b.setAttribute('aria-pressed',String(on));}));
document.querySelector('[data-print]')?.addEventListener('click',()=>window.print());
document.querySelector('#chapter-picker')?.addEventListener('change',e=>{location.hash=e.target.value;});
const sections=[...document.querySelectorAll('.chapter')];
if(sections.length){const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){document.querySelectorAll('aside a').forEach(a=>a.classList.toggle('active',a.hash==='#'+e.target.id));const picker=document.querySelector('#chapter-picker');if(picker)picker.value=e.target.id;}});},{rootMargin:'-90px 0px -65% 0px'});sections.forEach(s=>io.observe(s));}
function progress(){const p=document.querySelector('.progress');if(p)p.style.width=(100*scrollY/Math.max(1,document.documentElement.scrollHeight-innerHeight))+'%';}addEventListener('scroll',progress,{passive:true});progress();
'''

def page(title, body, controls=''):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="人物报告优化前后完整对照、来源使用与质量复核记录"><title>{title}</title><link rel="stylesheet" href="style.css"></head><body id="top"><header><div class="bar"><a class="brand" href="index.html">人物报告优化</a><div class="tools">{controls}<button data-print>打印 / 保存 PDF</button></div></div><div class="progress"></div></header>{body}<script src="app.js"></script></body></html>'''

def stats(values):
    return '<div class="stats">'+''.join(f'<div class="stat"><b>{a}</b><span>{b}</span></div>' for a,b in values)+'</div>'

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    source_text=(SOURCE/'index.html').read_text(encoding='utf-8')
    data=json.loads(re.search(r'const D=(.*?);let person=',source_text,re.S).group(1))
    for p in SOURCE.iterdir():
        if p.is_file() and p.name!='index.html':
            shutil.copyfile(p,OUT/p.name)
    baseline = Path('C:/Users/wangli/.codex/worktrees/company-knowledge-workbench/RAG/work/person-optimization')
    for run in ['same-corpus-20261021T005547-ef6911', 'same-corpus-20261021T005547-20608c']:
        for p in (baseline/run/'objects/projects/1/visual_evidence').glob('relationship_graph_202610201656*.svg'):
            dest = OUT/p.relative_to(baseline/run/'objects')
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,dest)
    (OUT/'style.css').write_text(CSS,encoding='utf-8')
    (OUT/'app.js').write_text(JS,encoding='utf-8')
    people=[('wang','王传福','比亚迪',95,46,33,192),('zhang','张勇','海底捞',53,18,17,128)]
    cards=[]
    highlights={
      'wang':['企查查157条任职及关联记录全部进入研究，正文引用6条。','修正董事长任期、授权条件及混合履历日期归属。','区分个人事实与比亚迪公司背景，保留可回查证据。'],
      'zhang':['区分海底捞与颐海国际的任职主体及任职时间。','分别呈现个人、夫妻共同及间接持股关系。','区分管理意向、下令与实际执行，恢复材料原有条件。']}
    notice='<div class="notice"><strong>当前状态：内部评审稿</strong><p>本页展示已完成的报告优化，不代表已经完成独立事实核验。来源获取与证据利用仍有缺口，尚未作为正式尽调报告验收。</p></div>'
    for key,name,company,total,research,body,hits in people:
        d=data[key]
        cards.append(f'''<article class="card"><div class="num">CASE {'01' if key=='wang' else '02'} / 15 CHAPTERS</div><h2>{name}</h2><div class="tags">{company} · 人物公开资料研究</div><div class="mini"><div><b>{total}</b><span>保存来源</span></div><div><b>{research}</b><span>进入写作研究</span></div><div><b>{body}</b><span>正文引用来源</span></div></div><ul>{''.join('<li>'+H(t)+'</li>' for t in highlights[key])}</ul><a class="cta" href="{key}.html">查看15章优化前后对比 →</a></article>''')
        nav=''.join(f'<a href="#chapter-{c["n"]}"><span>{c["n"]:02d}</span>{H(c["title"])}</a>' for c in d['chapters'])
        options=''.join(f'<option value="chapter-{c["n"]}">{c["n"]:02d} · {H(c["title"])}</option>' for c in d['chapters'])
        chapters=[]
        for c in d['chapters']:
            panes=[]
            for side,label in [('before','优化前'),('after','优化后')]:
                content=c[side]
                # Existing evidence anchors reference the copied evidence ledger.
                content=re.sub(r'data-side="[^"]*"','',content)
                content=re.sub(r'<a([^>]*?)href="[^"]*"([^>]*?)data-eid="([^"]+)"',lambda m:f'<a{m[1]}href="{key}-evidence.html#{m[3]}"{m[2]}data-eid="{m[3]}"',content)
                panes.append(f'<section class="pane {side}" aria-label="{label}"><div class="pane-label"><span>{label} · 完整章节</span><span>{c[side+"_chars"]:,} 字符</span></div><div class="doc">{content}</div></section>')
            chapters.append(f'<article class="chapter" id="chapter-{c["n"]}"><div class="chapter-top"><span class="number">{c["n"]:02d}</span><h2>{H(c["title"])}</h2></div><div class="note">{H(c["note"])}</div><div class="columns">'+''.join(panes)+'</div><a class="top-link" href="#top">返回顶部 ↑</a></article>')
        intro=f'''<section class="hero"><div class="eyebrow">PERSON REPORT / {company}</div><h1>{name} · 报告优化前后对比</h1><p>逐章查看实际报告原文、修正说明与引用依据。电脑端左右对照，手机端按优化前、优化后的顺序阅读。</p><p class="meta">对比口径：现有对照归档的优化前版本 → 第21轮最终版本 · 研究截止日期 2026-10-20<br>本轮固定使用已有材料，新增检索、原文抓取及专业平台请求均为0。</p></section>'''
        links=f'<div class="tools"><a href="{key}-report.html">优化后全文 ↗</a><a href="{key}-source-use.html">逐条来源去向 ↗</a><a href="{key}-evidence.html">完整证据台账 ↗</a><a href="{key}-before.md" download>优化前 Markdown</a><a href="{key}-after.md" download>优化后 Markdown</a></div>'
        bodyhtml='<div class="layout"><aside><p class="muted">完整章节导航</p>'+nav+'</aside><main>'+intro+stats([(hits,'网页结果命中（含重复）'),(total,'最终保存来源（含平台）'),(research,'进入写作研究的来源'),(body,'正文直接引用的来源')])+links+notice+f'<div class="mobile-picker"><label for="chapter-picker">跳转章节</label><select id="chapter-picker">{options}</select></div>'+''.join(chapters)+'<footer>原文保留；章节修正说明不等于独立真实性确认。<a href="validation.json">查看验证记录</a> · <a href="index.html">返回人物报告优化入口</a></footer></main></div>'
        controls=f'<a href="index.html">← 返回入口</a><button data-toggle="reading-after" aria-pressed="false">仅看优化后</button><button data-toggle="fold-originals" aria-pressed="false">收起原文引文</button>'
        (OUT/f'{key}.html').write_text(page(f'{name} · 15章优化前后对比',bodyhtml,controls),encoding='utf-8')
    table=''.join(f'<tr><td>{name} · {company}</td><td>{hits}</td><td>{total}</td><td>{research}</td><td>{body}</td></tr>' for _,name,company,total,research,body,hits in people)
    landing='''<main class="wrap"><section class="hero"><div class="eyebrow">RESEARCH QUALITY / PROGRESS REVIEW</div><h1>人物报告优化</h1><p>从来源到结论，逐章核对报告如何变化。两位人物、两份真实报告，完整呈现优化前后文本和仍待解决的问题。</p><p class="meta">成果整理 · 2026.10.23　/　固定材料迭代 · 第21轮　/　内部评审稿</p></section>'''+stats([('02','真实人物报告'),('15 × 2','完整章节前后对照'),('148','两份报告保存来源条目合计'),('50','两份报告正文引用来源数合计')])+'''<div class="section-title"><h2>选择报告，查看优化前后</h2><p class="muted">保留完整正文与证据回查入口</p></div><div class="cards">'''+''.join(cards)+'''</div><section class="panel"><h2>来源到了哪一步？</h2><p class="muted">各阶段使用不同统计口径；搜索命中含重复，保存来源还包含专业平台材料，不能直接相减当作淘汰数量。</p><div class="scroll"><table><thead><tr><th>报告</th><th>网页结果命中<br>含重复</th><th>保存来源<br>含专业平台</th><th>进入写作研究</th><th>正文直接引用</th></tr></thead><tbody>'''+table+'''</tbody></table></div><p class="muted">进入研究：材料进入模型研读输入或确定性表格处理；正文引用：报告中实际标注了该来源的证据。两者均不代表来源已经独立核实，也不表示其中所有有价值信息都已写入结论。</p><details><summary>专业平台数据与检索局限</summary><ul><li>王传福：企查查4份来源共157条记录全部进入研究，正文引用6条；烯牛两份公司材料均有内容进入研究，正文直接引用为0。</li><li>张勇：企查查受地区限制，未取得可用记录；不能据此作出无风险判断。</li><li>原检索存在调用次数、单次返回数量及原文抓取预算，部分平台查询未执行。当前对比未补查，也未完成逐条搜索结果到保存来源的差额对账。</li></ul></details></section><section class="panel"><h2>这次已改善，下一步仍需完成</h2><div class="cards"><div><h3>已完成的修正</h3><p>修复专业记录误拦截；校正人物与公司归属、任职日期、持股方式和事件状态；保留来源台账，减少跨章重复引文。</p></div><div><h3>仍待解决的问题</h3><p>补齐可取得的原文，复查未进入写作的来源；把有价值但未引用的材料转成有效证据；完成事实核验、全文编辑和交付验收。</p></div></div></section>'''+notice+'''<footer>页面按项目内公司报告优化汇报页的结构整理。报告以归档版本为准，文字变化和测试通过均不能换算成准确率。<br><a href="validation.json">验证记录</a> · <a href="https://test-d9gn6tepedabd30fb-1451499210.tcloudbaseapp.com/work-report/company/index.html" target="_blank" rel="noopener">公司报告参考页面 ↗</a></footer></main>'''
    if (OUT/'coverage/index.html').exists():
        landing=landing.replace('<main class="wrap">','<main class="wrap"><div class="notice"><strong>已有后续优化版</strong><p><a href="coverage/index.html">查看补取原文、扩大材料利用后的最新报告 →</a> 本页保留第21轮固定材料对照。</p></div>',1)
    (OUT/'index.html').write_text(page('人物报告优化 · 两份报告前后对比',landing),encoding='utf-8')
    print(json.dumps({'output':str(OUT),'reports':2,'chapters_per_report':15,'offline':True},ensure_ascii=False))

if __name__=='__main__':
    build()
