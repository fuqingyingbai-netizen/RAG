"""Build a self-contained chapter comparison from actual archived reports.

Run with --help for input directories. No network, model calls or credentials.
"""
import argparse
import base64
import hashlib
import html
import json
import re
import shutil
from pathlib import Path


def chapters(text):
    return {int(m[1]): m[0].strip() for m in re.finditer(
        r'^## (\d+)\.[\s\S]*?(?=^## \d+\.|\Z)', text, re.M)}


def selected_table(text, pattern, maximum=5):
    """Keep whole source rows and their own header; never clip table cells."""
    blocks = re.findall(r'(?m)(?:^\|[^\n]*\n?)+', text)
    result = []
    for block in blocks:
        lines = block.splitlines()
        matches = [line for line in lines[2:] if re.search(pattern, line)]
        if matches:
            result.append('\n'.join(lines[:2] + matches[:maximum]))
    return '\n\n'.join(result)


def section(text, title):
    match = re.search(r'(?m)^### ' + re.escape(title) + r'\s*$', text)
    if not match:
        return ''
    end = re.search(r'(?m)^### ', text[match.end():])
    return text[match.start():match.end() + end.start() if end else len(text)].strip()


def matching_lines(text, pattern, maximum=4):
    return '\n\n'.join([line for line in text.splitlines()
                        if line and not line.startswith('#') and re.search(pattern, line)][:maximum])


def image_data(path):
    mime = 'image/svg+xml' if path.suffix.lower() == '.svg' else 'image/png'
    return 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode()


def render(text, prefix, objects, urls):
    def inline(value):
        value = html.escape(value).replace('&lt;br&gt;', '<br>').replace('&lt;br/&gt;', '<br>')
        value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
        # Only ASCII URL characters: Chinese text following a URL is prose.
        value = re.sub(r'https?://[A-Za-z0-9_./?=%&;:#@+~-]+', lambda m:
                       '<a href="' + html.escape(html.unescape(m[0]), quote=True) +
                       '" target="_blank" rel="noopener">原始来源 ↗</a>', value)
        return re.sub(r'\[(E-[A-F0-9]{12})\]', lambda m:
                      '<a class="eid" href="' + html.escape(urls[m[1]], quote=True) +
                      '" target="_blank" rel="noopener">[' + m[1] + ']</a>'
                      if m[1] in urls and urls[m[1]].startswith(('http://', 'https://'))
                      else '<span class="eid">[' + m[1] + ']</span>', value)

    lines = text.splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                def row(cells, tag):
                    return '<tr>' + ''.join('<' + tag + '>' + inline(c) + '</' + tag + '>' for c in cells) + '</tr>'
                result.append('<div class="table-scroll"><table><thead>' + row(rows[0], 'th') +
                              '</thead><tbody>' + ''.join(row(r, 'td') for r in rows[1:]) + '</tbody></table></div>')
            continue
        picture = re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)', line)
        heading = re.match(r'^(#{1,6})\s+(.*)', line)
        if picture:
            path = objects / picture[2]
            if not path.is_file():
                raise FileNotFoundError(path)
            result.append('<figure><img class="zoomable" alt="' + html.escape(prefix + ' · ' + picture[1], quote=True) +
                          '" src="' + image_data(path) + '"><figcaption>' + inline(picture[1]) + '</figcaption></figure>')
        elif heading:
            level = min(6, len(heading[1]) + 1)
            result.append(f'<h{level}>' + inline(heading[2]) + f'</h{level}>')
        else:
            result.append('<p>' + inline(line.lstrip('> ')) + '</p>')
        i += 1
    return '\n'.join(result)


NOTES = {
    1: ('sync', '摘要跟随正文证据更新',
        '摘要可引用的材料与已核验正文分开选择，未充分带入本轮融资完成、最新利润变化和同口径对标。',
        '摘要复用已核验字段，纳入2026年半年报、2025年配售完成、具体召回及2026年1—8月电池使用量份额。',
        '正文与摘要共享核验结果', '模型草稿出现越界表述时，程序改用已核验事实重建；本次实际触发且最终校验通过。'),
    2: ('keep', '工商、股权及关系图谱保持',
        '已经区分登记股东、名义持有人、主要人员和明确披露的控制关系。',
        '本轮保留上述事实及图谱内容；只重新生成图片文件。HKSCC名义登记持股不改写为实际控制。',
        '主体正文保持一致', '两组图谱均取自真实报告。前后图的内容保持，不能把图片重新生成算作新的治理结论。'),
    3: ('fix', '剔除他企成立事项',
        '将松禾投资的1996年成立事项混入比亚迪沿革，原因是把“有限公司”中的“公司”当成发行人自称。',
        '改用局部语境识别事件主体，删除他企成立事项；保留比亚迪登记成立、改制及资本事件。',
        '他企成立事项：有 → 无', '修复针对主体识别规则，没有按比亚迪或松禾名称写特例。'),
    4: ('keep', '治理制度与运行记录保持',
        '已分别列示制度规定、董事会等运行记录及尚需补充的执行材料。',
        '本轮正文逐字保持；继续区分“制度存在”和“制度实际有效运行”，不新增无依据判断。',
        '正文保持一致', '复测重新执行了章节构建与校验，保留通过核对的内容。'),
    5: ('fix', '补入评价指标与同口径对标',
        '可交付评价与对标记录为0，无法形成有来源支持的员工、客户或同业比较。',
        '补采港交所可持续发展报告与SNE原发布统计，形成6项调查/服务指标和4家企业的电池使用量份额。',
        '可引用评价/对标记录：0 → 10', '满意度、敬业度、投诉数、回应率与售后NPS分别保留口径；公开自报不当作独立访谈。'),
    6: ('fix', '跨页项目名称与进展完整展示',
        'PDF跨页被当成两条项目，出现“化技术”“车架”等截断名称，进展文字也被拆开。',
        '拼接连续原页的对应单元格，恢复CTB电池车身一体化技术与一体式大梁车架，并保留两页出处。',
        '截断名称 → 完整项目与连续页码', '同时修正展示选取规则，保证拼接后的项目出现在最终正文；进展、目标和未来计划仍分别核对。'),
    7: ('fix', '会议记录不再进入职务字段',
        '人员表结束后仍沿用人员上下文，把11条会议记录识别为职务，造成异常长表格。',
        '遇会议表即终止人员名册上下文，并对职务字段再次校验；真实跨页任职记录仍保留。',
        '会议误归职务记录：11 → 0', '人员事实记录由112条整理为104条，不以记录变少评价团队风险高低。'),
    8: ('fix', '新员工资料进入正常生成链路',
        '已有人员事实19条，但尚未形成可绑定公式和时期的流失率记录。',
        '认证发行人原件后恢复来源定位，识别47条人员事实，纳入2025年流失率、培训及相关定义。',
        '人员事实：19 → 47', '员工流失率2025年2.89%、2024年2.53%；保留原表“/12”公式，不擅自换算成年化离职率。分岗位流失仍待核。'),
    9: ('keep', '司法事实与程序边界保持',
        '已区分案件主体、案号、诉请、裁判、撤诉、执行和履行状态。',
        '本轮正文逐字保持，未因其他章节修复改变原有司法事实；未知金额和后续程序继续保留待核。',
        '正文保持一致', '平台计数为0、未命中或未取得后续材料，仍不作为全历史无风险的证明。'),
    10: ('keep', '专项尽调范围与待核材料保持',
        '已区分融资、资金用途、业务真实性及客户/供应商等专项对象，并注明公开资料的核验范围。',
        '本轮正文逐字保持。已有披露继续引用，银行流水、合同和业务背景的逐笔核验仍待实际开展。',
        '正文保持一致', '本轮没有把公开披露改写为已完成资金穿透或独立尽调。'),
    11: ('sync', '风险章节同步人员指标边界',
        '已有具体风险记录、召回事项和核查目录；本轮前尚未带入新增的员工流失率口径。',
        '原有内容保持，新增“人员指标的解释边界”：净人数变化不等于流失或裁员，不能无基准认定高流失。',
        '仅新增1项口径说明', '随第八章新增原件同步，不凭流失率直接提高或降低企业风险等级。'),
    12: ('fix', '已完成融资进入综合评价',
        '其他章节已经取得配售完成证据，本章仍写“观察窗内未取得完成及净额披露”，融资分项未评分。',
        '核验连续原页5、6，识别2025-03-11完成配售、净额约43,383百万港元，按既有锚点评为3/5。',
        '融资分项：未评分 → 3/5', '这是系统框架中的融资执行分项，不是外部信用评级，也不证明未来偿债能力或资金可自由调用。'),
    13: ('sync', '来源索引对应实际正文引用',
        '索引主要依赖清洗卡；章节从原件恢复的新证据可能漏定位，未被摘要引用的卡也可能带入摘要标签。',
        '所有章节恢复的原件证据先登记定位，再按正文实际引用章节生成索引；合并引用保留各自原始URL。',
        '39个正文编号 → 39个索引定位', '新增员工原件正确关联第五、八、十一章；未被摘要引用的卡不再标成“第一章原文核对”。'),
    14: ('sync', '后续清单随正文重新归并',
        '原清单基于修复前章节；新补资料后，已绑定的脚注与范围说明可能占用代表性核验项。',
        '从最终正文重建后续核验清单，保留真正未闭环的行动、优先级与材料；脚注定义留在对应指标旁。',
        '已取得证据与未完成行动分开', '融资不再列为“未取得完成证据”；独立访谈、分岗位离职统计及风险整改等实际待核事项继续保留。'),
}


def excerpts(number, old, new):
    if number == 1:
        return section(old, '核心发现点') + '\n\n' + section(old, '公司所属赛道竞争格局'), section(new, '核心发现点') + '\n\n' + section(new, '公司所属赛道竞争格局')
    if number == 2:
        return selected_table(old, r'HKSCC|王传福|香港中央结算', 4), selected_table(new, r'HKSCC|王传福|香港中央结算', 4)
    if number == 3:
        return selected_table(old, r'松禾|1995-02-10|2025-03-11', 3), selected_table(new, r'1995-02-10|2002-06-10|2025-03-11', 3)
    if number == 4:
        return section(old, '决策机制'), section(new, '决策机制')
    if number == 5:
        return old, section(new, '员工评价') + '\n\n' + section(new, '同业对标')
    if number == 6:
        return selected_table(old, r'\|\s*(?:化技术|车架)\s*\|', 2), selected_table(new, r'电池车身一体化技术|一体式大梁车架', 2)
    if number == 7:
        rows = selected_table(old, r'会议', 1)
        return rows, selected_table(new, r'王传福|周亚琳', 2)
    if number == 8:
        return matching_lines(old, r'尚未形成可绑定公式|总体与分类公式'), selected_table(new, r'員工流失率|高級管理層流失率', 2) + '\n\n' + matching_lines(new, r'原文标号68', 1)
    if number == 9:
        return selected_table(old, r'撤回起诉|民初47819', 2), selected_table(new, r'撤回起诉|民初47819', 2)
    if number == 10:
        return selected_table(old, r'融资|资金用途|资金使用', 2), selected_table(new, r'融资|资金用途|资金使用', 2)
    if number == 11:
        return matching_lines(old, r'核查顺序|整改', 2), section(new, '人员指标的解释边界')
    if number == 12:
        return selected_table(old, r'近期融资执行', 1), selected_table(new, r'近期融资执行|2025-03-11', 1)
    if number == 13:
        return selected_table(old, r'E-BE56354CE374|E-260D66DB1EAE', 2), selected_table(new, r'E-05D9ED3A429D|E-BE56354CE374|E-260D66DB1EAE', 3)
    return selected_table(old, r'第8章|第12章', 2), selected_table(new, r'第8章|第12章', 2)


CSS = '''
:root{--ink:#203249;--muted:#63758a;--line:#dfe7ee;--teal:#087d70;--bg:#f3f6f9}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:90px}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.8 "Microsoft YaHei","PingFang SC",sans-serif}a{color:#1f648e;text-decoration:none}button{font:inherit;cursor:pointer;border:1px solid #cddbe4;border-radius:7px;background:white;color:var(--ink);padding:7px 13px}button:hover,button.active{background:#e1f1eb;color:#087563;border-color:#91bcae}header{position:sticky;top:0;z-index:10;background:#fffffff5;border-bottom:1px solid var(--line)}.bar{max-width:1500px;margin:auto;padding:12px 26px;display:flex;justify-content:space-between;align-items:center;gap:14px}.bar strong{font-size:15px}.bar .actions{display:flex;gap:8px;flex-wrap:wrap}.layout{max-width:1500px;margin:auto;display:grid;grid-template-columns:215px minmax(0,1fr);gap:28px;padding:30px 26px 60px}aside{position:sticky;top:90px;align-self:start;max-height:calc(100vh - 115px);overflow:auto}aside a{display:block;font-size:12px;padding:8px;color:#536b80;border-radius:5px}aside a:hover{background:#e0ede7}aside b{display:inline-block;width:25px;color:#829ba5}main{min-width:0}.hero{padding:36px 38px;border-radius:15px;background:#152f45;color:white}.hero h1{font-size:32px;line-height:1.4;margin:8px 0 18px}.hero p{color:#c9dbe5;margin:9px 0;max-width:920px}.eyebrow{font-size:12px;letter-spacing:2px;color:#8ad6c2}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.stat{background:white;border:1px solid var(--line);padding:18px;border-radius:10px}.stat strong{display:block;font-size:27px;line-height:1.3}.stat span{font-size:12px;color:var(--muted)}.scope{background:#fff8e8;border:1px solid #eddfb8;padding:16px 20px;border-radius:9px;font-size:13px;margin-bottom:20px}.toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:10px 0 23px}.chapter{background:white;border:1px solid var(--line);border-radius:13px;padding:28px;margin-bottom:24px;scroll-margin-top:88px}.chapter-top{display:flex;gap:18px;align-items:center}.chapter-top .num{font-size:34px;color:#91a9b8;font-weight:300;border-right:1px solid var(--line);padding-right:18px}.chapter-top h2{font-size:21px;line-height:1.45;margin:4px 0}.subtitle{color:var(--muted);font-size:12px;margin:0}.badge{display:inline-block;padding:2px 9px;background:#e6f4ed;color:#087565;border-radius:5px;font-size:12px;margin:0 0 5px}.badge.sync{background:#eaf0fa;color:#345e9e}.badge.keep{background:#eef1f4;color:#667785}.overview,.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-top:20px}.overview>div{padding:18px;border-radius:8px}.old{background:#fbf2ef;border-top:3px solid #c79581}.new{background:#ebf6f1;border-top:3px solid #359b7e}.label{font-size:11px;font-weight:700;letter-spacing:1px}.overview p{font-size:14px;margin:7px 0 0}.result{display:flex;gap:18px;align-items:baseline;flex-wrap:wrap;margin:20px 0 12px}.result strong{font-size:19px;color:var(--teal)}.result span{font-size:12px;color:var(--muted)}.why{font-size:13px;color:var(--muted);background:#f4f7fa;padding:13px 16px;border-radius:7px}.pair>div{min-width:0;border:1px solid var(--line);border-radius:9px;overflow:hidden}.doc-label{padding:10px 15px;border-bottom:1px solid var(--line);font-size:12px;font-weight:bold;background:#f6f8fa}.doc-body{padding:16px;max-height:520px;overflow:auto;font-size:13px;line-height:1.85;overflow-wrap:anywhere}.doc-body h3{font-size:18px}.doc-body h4{font-size:15px}.doc-body h5{font-size:14px}.doc-body p{margin:10px 0}.table-scroll{overflow-x:auto;margin:12px 0}table{width:100%;min-width:430px;border-collapse:collapse;font-size:12px;line-height:1.7}th,td{border:1px solid #dce5ec;padding:9px;vertical-align:top;text-align:left;overflow-wrap:anywhere}th{background:#edf3f7}td:first-child{min-width:70px}tr:nth-child(even){background:#fafbfd}.eid{font-size:10px;color:#2b6b96;white-space:nowrap}details{border-top:1px solid var(--line);padding-top:13px;margin-top:17px}summary{cursor:pointer;font-size:13px;color:#4e6d7d}details[open]>summary{margin-bottom:14px}details .doc-body{max-height:720px}figure{margin:13px 0}img{max-width:100%;height:auto}.zoomable{cursor:zoom-in}figcaption{font-size:11px;color:var(--muted);margin-top:7px}.images{display:grid;grid-template-columns:1fr 1fr;gap:15px}.images img{max-height:360px;object-fit:contain;border:1px solid var(--line);background:white}.conclusion{padding:28px;background:#e3efe9;border-radius:13px;margin:28px 0}.conclusion h2{font-size:21px}.conclusion p{font-size:14px}.footer{font-size:12px;color:var(--muted)}.present aside{display:none}.present .layout{display:block;max-width:1250px}.present .doc-body{font-size:16px}.present .overview p{font-size:17px}dialog{border:0;border-radius:10px;max-width:96vw;max-height:96vh;padding:45px 14px 14px}dialog::backdrop{background:#0a1a2bd9}dialog img{display:block;max-height:85vh;object-fit:contain}dialog button{position:absolute;right:10px;top:7px}.hidden{display:none!important}@media(max-width:1050px){.layout{display:block;padding:20px}aside{display:none}}@media(max-width:650px){.bar{padding:10px 13px}.bar strong{font-size:12px}.bar button,.bar a{font-size:11px}.hero{padding:25px 20px}.hero h1{font-size:25px}.stats{grid-template-columns:repeat(2,1fr)}.layout{padding:12px}.chapter{padding:20px 14px}.chapter-top h2{font-size:19px}.chapter-top .num{font-size:28px}.overview,.pair,.images{grid-template-columns:1fr}.doc-body{max-height:420px}.result strong{font-size:17px}}@media print{header,aside,.toolbar,.footer,dialog{display:none}.layout{display:block;padding:0}.hero{background:white;color:black}.hero p{color:#344}.chapter{break-before:page;border:0}.doc-body{max-height:none;overflow:visible}details{display:none}table{min-width:0}.images{break-inside:avoid}}
'''


JS = '''
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));
 const filter=button.dataset.filter;
 document.querySelectorAll('.chapter').forEach(c=>c.classList.toggle('hidden',filter!=='all'&&(filter==='changed'?c.dataset.kind==='keep':c.dataset.kind!=='keep')));
}));
document.getElementById('present').addEventListener('click',()=>document.body.classList.toggle('present'));
const viewer=document.getElementById('viewer');
document.querySelectorAll('.zoomable').forEach(img=>img.addEventListener('click',()=>{viewer.querySelector('img').src=img.src;viewer.querySelector('img').alt=img.alt;viewer.showModal()}));
viewer.querySelector('button').addEventListener('click',()=>viewer.close());
viewer.addEventListener('click',e=>{if(e.target===viewer)viewer.close()});
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-dir', type=Path, required=True)
    parser.add_argument('--after-dir', type=Path, required=True)
    parser.add_argument('--old-objects', type=Path, required=True)
    parser.add_argument('--supplement-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report-link', default='company-report-verified-20261020.html')
    args = parser.parse_args()
    old_text = (args.before_dir / '阶段产物/desktop_report_v1.md').read_text(encoding='utf-8')
    new_text = (args.after_dir / '比亚迪_完整修复后报告.md').read_text(encoding='utf-8')
    old, new = chapters(old_text), chapters(new_text)
    assert set(old) == set(new) == set(range(1, 15))
    acceptance = json.loads((args.after_dir / '验收结果.json').read_text(encoding='utf-8'))
    assert acceptance['gate']['passed'] and all(acceptance['checks'].values())
    tests = (args.after_dir / '回归测试结果.txt').read_text(encoding='utf-8-sig')
    count = int(re.search(r'(\d+) passed', tests)[1])
    urls = {}
    for line in new[13].splitlines():
        eid = re.match(r'^\|\s*(E-[A-F0-9]{12})\s*\|', line)
        url = re.search(r'https?://[^\s|]+', line)
        if eid and url:
            urls[eid[1]] = url[0]
    body_ids = set(re.findall(r'\[(E-[A-F0-9]{12})\]', '\n'.join(new[i] for i in range(1, 13))))
    index_ids = set(re.findall(r'^\|\s*(E-[A-F0-9]{12})\s*\|', new[13], re.M))
    assert body_ids == index_ids and len(body_ids) == 39
    nav, cards, manifest = [], [], []
    labels = {'fix': '问题修复', 'sync': '随正文同步', 'keep': '本轮保持'}
    for n in range(1, 15):
        kind, title, prior, current, metric, why = NOTES[n]
        original_title = re.sub(r'^## \d+\.\s*', '', new[n].splitlines()[0])
        before, after = excerpts(n, old[n], new[n])
        # A missing selected excerpt must never be disguised as an empty chapter.
        if not before:
            before = '\n'.join(old[n].splitlines()[2:15])
        if not after:
            after = '\n'.join(new[n].splitlines()[2:15])
        old_render = lambda text: render(text, '修复前', args.old_objects, urls)
        new_render = lambda text: render(text, '修复后', args.after_dir / 'objects', urls)
        panels = lambda a, b: '<div class="pair"><div><div class="doc-label">修复前 · 真实生成稿节选</div><div class="doc-body">' + old_render(a) + '</div></div><div><div class="doc-label">修复后 · 自动生成稿节选</div><div class="doc-body">' + new_render(b) + '</div></div></div>'
        extra = ''
        if n == 2:
            old_images = '\n'.join(re.findall(r'(?m)^!\[[^]]+\]\([^)]+\)', old[n]))
            new_images = '\n'.join(re.findall(r'(?m)^!\[[^]]+\]\([^)]+\)', new[n]))
            assert old_images.count('![') == new_images.count('![') == 2
            extra = '<details open><summary>两组真实图谱：本轮保持，可点击放大</summary>' + panels(old_images, new_images) + '</details>'
        if n == 5:
            extra = '<details><summary>核对调查原页（2张图片已嵌入，点击放大）</summary><div class="images">'
            for filename, caption in [('员工调查原页.png', '港交所2025年可持续发展报告 · 物理页155'), ('客户调查原页.png', '港交所2025年可持续发展报告 · 物理页159')]:
                extra += '<figure><img class="zoomable" alt="' + caption + '" src="' + image_data(args.supplement_dir / filename) + '"><figcaption>' + caption + '</figcaption></figure>'
            extra += '</div></details>'
        nav.append(f'<a href="#chapter-{n}"><b>{n:02d}</b>' + html.escape(original_title) + '</a>')
        cards.append(f'<article class="chapter" id="chapter-{n}" data-kind="{kind}"><div class="chapter-top"><span class="num">{n:02d}</span><div><span class="badge {kind}">{labels[kind]}</span><p class="subtitle">' + html.escape(original_title) + '</p><h2>' + title + '</h2></div></div><div class="overview"><div class="old"><span class="label">修复前</span><p>' + prior + '</p></div><div class="new"><span class="label">修复后</span><p>' + current + '</p></div></div><div class="result"><strong>' + metric + '</strong><span>' + f'原文字符数（含引用）：{len(old[n]):,} → {len(new[n]):,}' + '</span></div><p class="why">' + why + '</p><h3>核心原文对照</h3>' + panels(before, after) + extra + '<details><summary>展开第' + str(n) + '章完整前后稿</summary>' + panels(old[n], new[n]) + '</details></article>')
        manifest.append({'chapter': n, 'title': original_title, 'kind': kind,
                         'before_chars': len(old[n]), 'after_chars': len(new[n]),
                         'before_sha256': hashlib.sha256(old[n].encode()).hexdigest(),
                         'after_sha256': hashlib.sha256(new[n].encode()).hexdigest()})
    report_link = html.escape(args.report_link, quote=True)
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>比亚迪公司报告 · 14章修复前后对比</title><style>' + CSS + '</style></head><body><header><div class="bar"><strong>公司报告优化 · 真实运行对比</strong><div class="actions"><button id="present">汇报模式</button><a href="' + report_link + '">打开修复后完整报告 ↗</a></div></div></header><div class="layout"><aside><p class="subtitle">12章正文 + 2章交付附录</p>' + ''.join(nav) + '</aside><main><section class="hero"><span class="eyebrow">BYD · VERIFIED REPORT COMPARISON · 2026.10.20</span><h1>比亚迪公司报告<br>逐章修复前后对比</h1><p>针对真实生成稿暴露的问题修复代码，再通过生产报告生成入口跑出完整14章。重点展示主体归属、可核验证据、表格解析，以及跨章节证据复用的变化。</p><p>6章直接修复 · 4章同步更新 · 4章主体内容保持</p></section><section class="stats"><div class="stat"><strong>14章</strong><span>完整前后稿均可展开</span></div><div class="stat"><strong>6项</strong><span>正文问题直接修复</span></div><div class="stat"><strong>' + str(count) + '项</strong><span>公司相关回归测试通过</span></div><div class="stat"><strong>39 / 39</strong><span>正文证据编号均有索引定位</span></div></section><div class="scope"><b>对比口径：</b>前稿为2026年10月20日真实测试初稿；后稿使用同轮1559份留存来源及补采的2份原发布材料重新生成。测试覆盖报告生成、章节校验和交付附录；本次未重新执行全量联网检索、平台查询或生产部署。比亚迪样本已通过本轮核对，不代表所有公司均已完成验收。</div><div class="toolbar"><button class="active" data-filter="all">全部14章</button><button data-filter="changed">只看修复 / 同步（10章）</button><button data-filter="keep">本轮保持（4章）</button></div>' + ''.join(cards) + '<section class="conclusion"><h2>本轮达到的效果</h2><p>比亚迪这份报告的已发现问题已经闭环：他企事项被剔除、第五章补到真实评价及对标来源、跨页项目和职务字段恢复正常、员工资料进入正文、已完成融资进入综合评价。摘要、风险解释、来源索引和后续行动随之同步。</p><p>这份材料可用于汇报和下一步上线验收。独立访谈、逐笔资金核验、分岗位离职统计及部分风险后续状态仍须实际开展，保留为研究任务，不用“报告通过”替代它们。</p><p><a href="' + report_link + '">查看修复后完整14章报告（含内嵌图谱） ↗</a></p></section><p class="footer">原文节选直接来自前后两份生成稿；字符数不作为质量评分。图谱与原页图片已内嵌，可离线查看；外部原始来源需联网。两份全文、证据包、执行日志与代码指纹均保留在本地复测目录。</p></main></div><dialog id="viewer"><button type="button">关闭 ×</button><img alt="原始图片放大"></dialog><script>' + JS + '</script></body></html>'
    assert not re.search(r'<img[^>]+src="(?!data:)', page)
    assert len(re.findall(r'class="chapter" id="chapter-', page)) == 14
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding='utf-8')
    shutil.copyfile(args.after_dir / '比亚迪_完整修复后报告.html', args.output.parent / args.report_link)
    validation = {'scope': 'BYD real archived report generation replay; not fresh full retrieval or deployment',
                  'regression_passed': count, 'chapters': manifest, 'body_evidence_ids': len(body_ids),
                  'indexed_evidence_ids': len(index_ids), 'inline_image_occurrences': page.count('src="data:image/'),
                  'comparison_sha256': hashlib.sha256(page.encode()).hexdigest(),
                  'before_report_sha256': hashlib.sha256(old_text.encode()).hexdigest(),
                  'after_report_sha256': hashlib.sha256(new_text.encode()).hexdigest()}
    args.output.with_suffix('.validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'chapters': 14, 'tests_passed': count,
                      'embedded_images': validation['inline_image_occurrences']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
