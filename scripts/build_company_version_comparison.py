"""Compare the previous accepted optimized report with the latest real output.

This is a version comparison, not the same-run bug reproduction comparison.
"""
import argparse
import hashlib
import html
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from build_company_comparison import CSS, chapters, image_data, matching_lines, render, section, selected_table


NOTES = {
    1: ('change', '从已有财务摘要，调整为跨章节综合摘要',
        '原优化版已经列出2026年半年报收入、利润及同比，并明确登记持股和司法记录边界；竞争格局侧重新能源客车出口。',
        '新版保留收入、利润，补入经营现金流和已完成配售；关注信号改为具体召回，同业段引用电池使用量的统一统计口径。',
        '新增摘要覆盖：现金流、配售及具体召回',
        '不是本次首次修好财务摘要。变化在信息取舍和正文证据复用，客车出口与电池份额仍属于不同细分口径。'),
    2: ('carry', '延续已经优化的股权与治理口径',
        '原优化版已区分股东登记、主要人员、明确控制关系与名义持有人，并已有两张关系图。',
        '新版继续按相同原则呈现工商、持股及任职，使用本次来源和采集记录重建图谱。',
        '图谱与名义持有人边界属于原有优化',
        '下方是两版实际图谱，不将图片重新生成或证据编号变化算成新的治理发现。'),
    3: ('coverage', '既有主体识别原则保持，历史节点覆盖有变化',
        '原优化版已无松禾投资成立事项，并保留官网创业起点、海外分公司等历史节点，区分官网自述与工商登记成立。',
        '新版同样不含松禾事项；保留登记成立、改制及资本节点，但部分旧官网沿革没有在本次正文复现。',
        '两版均无松禾成立事项；节点集合不同',
        '本次新资料暴露过主体识别回归，已在10月20日同轮修复；不能据此说10月16日最终优化稿原本就有该错误。'),
    4: ('carry', '治理制度与执行证据的区分继续保留',
        '原优化版已经分开制度要求、实际会议或控制记录以及尚需补充的运行证据。',
        '新版延续章节结构和上述判断边界，具体表述随本次来源调整。',
        '原有治理核验框架延续',
        '这是已有优化的复现，不再描述为本轮从笼统治理评价首次改成证据核验。'),
    5: ('coverage', '已有评价指标复现，合作方等来源覆盖减少',
        '原优化版已含员工满意度74.88分、售后NPS 97.4%、BYD电池使用量份额15.1%和同口径竞品表；还包含合作方公开公告等材料。',
        '新版再次取得相同调查和统计指标，并保留公司自报、NPS及统计范围边界；原有合作方公告等内容未全部复现。',
        '核心指标：已有 → 复现；不是0 → 10',
        '本次修复的是新检索结果下漏用原件的问题。这两份最终稿之间，不能把旧版已有的满意度和份额算成新增加的事实。'),
    6: ('change', '经营数据延续，跨页项目展示发生调整',
        '原优化版已有产品收入、毛利、产销数量和12项研发进展，并区分计划、发布与量产；选取的项目中未展示完整CTB和一体式大梁车架。',
        '新版继续使用经营数据，调整跨页单元格拼接及展示选取，明确展示CTB电池车身一体化技术、一体式大梁车架及对应连续页。',
        '重点增量：完整跨页项目进入正文',
        '新版项目名单有所替换，并非在原12项上全部叠加；完整前后表保留供核对。'),
    7: ('change', '原优化名册继续使用，新增资料下更稳健',
        '原优化版已输出正常职务表，涉及26名人员；并没有把11条会议内容列成职务。',
        '新版涉及27名人员，继续区分职务、任期和履历；新增来源触发的会议表串入问题已在本次解析逻辑中拦截。',
        '两版职务表均正常；已得人员26 → 27',
        '“11 → 0”属于10月20日同轮初稿到修复稿的调试指标，不能套到这里的10月16日最终优化稿。'),
    8: ('carry', '员工流失率与原式口径是已有成果',
        '原优化版已经展示2025年员工流失率2.89%、2024年2.53%，并保留含“/12”的原公式和统计范围。',
        '新版复现同一指标及公式，改为本次原件的繁体原文和新的证据定位；分岗位流失率仍保留待核。',
        '2.89% → 2.89%，不是本次首次补齐',
        '本次加强的是清洗卡漏掉时的原件恢复路径；指标本身并非新增，也不能从繁简字形或编号变化推定数值变动。'),
    9: ('coverage', '司法核验原则保持，回执与明细重新组织',
        '原优化版已区分117条文书总量、已返回明细及程序结果，并保留查询日期和案件主体边界。',
        '新版沿用上述原则，使用10月20日回执和本轮取得的具体明细重建章节，来源编号和部分明细发生变化。',
        '查询记录与正文覆盖变化，不等于风险升降',
        '司法总量、已核明细、不同程序记录和实际风险敞口仍分别判断，不能仅用篇幅或编号数量比较质量。'),
    10: ('coverage', '专项对象和公开披露覆盖发生变化',
        '原优化版已有资金与交易勾稽、专项触发依据和未闭环材料，相关内容较详细。',
        '新版按本轮来源重新生成专项任务与公开披露，篇幅和具体对象覆盖有所变化；银行流水和合同独立核验仍未被替代。',
        '两版专项内容需按对象核对',
        '这里不把篇幅缩短称为全面提升，也不声称新版已完整承接旧版每一笔交易与材料。'),
    11: ('carry', '已有事件级风险与人员解释边界延续',
        '原优化版已经按具体召回、司法等事项组织风险，并已有“人员指标的解释边界”。',
        '新版更新本轮来源下的风险事件和核查条件，继续保留员工净变化、流失及裁员不能混用的说明。',
        '人员解释边界在两版中均存在',
        '不能再把该说明计为相对10月16日的新增加项；具体风险事件变化按各自日期、主体和批次核对。'),
    12: ('carry', '融资3/5原本已有，新版增加明细展示',
        '原优化版已将“近期融资执行”评为3/5，并引用配售完成相关材料；并非未评分。',
        '新版分项仍为3/5，另用表格直接展示2025-03-11完成配售、净额约43,383百万港元及物理页5、6。',
        '3/5 → 3/5；新增清晰的完成事实展示',
        '“未评分 → 3/5”只是10月20日新一轮初稿中的漏证恢复，不能用于本页旧优化稿的前后比较。'),
    13: ('change', '索引按新来源和正文引用重建',
        '原优化版的51个正文证据编号已有索引；当时清洗事实库可追溯来源为491。',
        '新版39个正文证据编号全部有索引；本次清洗可追溯来源1559，并补强原件恢复证据和实际引用章节的对应。',
        '索引编号51 → 39；两版均有完整索引',
        '两次来源池不同，编号减少不是质量提升，也不能证明旧版内容全部保留。未实际被某章引用的卡不再误挂该章标签。'),
    14: ('change', '后续清单去掉已经绑定的定义项',
        '原优化版已按章节归并后续核验；第八章代表性项目被已取得的原页范围说明占用。',
        '新版从最终正文重新归并，员工原表定义留在指标旁，把分岗位统计、公式分母和执行材料等真正的后续行动列入清单。',
        '从已有集中清单，进一步改进选取',
        '这次确有展示增量，但不能说原优化版没有后续建议或所有旧待核事项都已完成。'),
}


def excerpts(n, old, new):
    if n == 1:
        return section(old, '核心发现点') + '\n\n' + section(old, '公司所属赛道竞争格局'), section(new, '核心发现点') + '\n\n' + section(new, '公司所属赛道竞争格局')
    if n == 2:
        return selected_table(old, r'HKSCC|王传福|香港中央结算', 3), selected_table(new, r'HKSCC|王传福|香港中央结算', 3)
    if n == 3:
        return selected_table(old, r'1994|1995-02-10|1998|2002-06-10', 4), selected_table(new, r'1995-02-10|2002-06-10|2025-03-11', 3)
    if n == 4:
        return section(old, '决策机制'), section(new, '决策机制')
    if n == 5:
        return section(old, '员工评价') + '\n\n' + section(old, '合作方评价') + '\n\n' + section(old, '同业对标'), section(new, '员工评价') + '\n\n' + section(new, '合作方评价') + '\n\n' + section(new, '同业对标')
    if n == 6:
        return selected_table(old, r'GCFlux|DMO|天神之眼|易四方技术', 4), selected_table(new, r'电池车身一体化技术|一体式大梁车架', 2)
    if n == 7:
        return matching_lines(old, r'已得任职', 1) + '\n\n' + selected_table(old, r'王传福|周亚琳', 2), matching_lines(new, r'已得任职', 1) + '\n\n' + selected_table(new, r'王传福|周亚琳', 2)
    if n == 8:
        return selected_table(old, r'员工流失率|高级管理层流失率', 2) + '\n\n' + matching_lines(old, r'原文标号68|员工流失率=', 1), selected_table(new, r'員工流失率|高級管理層流失率', 2) + '\n\n' + matching_lines(new, r'原文标号68', 1)
    if n == 9:
        return section(old, '查询覆盖与计数边界'), section(new, '查询覆盖与计数边界')
    if n == 10:
        return selected_table(old, r'14,077|14,669|融资|资金用途|交割', 3), selected_table(new, r'14,077|14,669|融资|资金用途|交割', 3)
    if n == 11:
        return section(old, '人员指标的解释边界'), section(new, '人员指标的解释边界')
    if n == 12:
        return selected_table(old, r'近期融资执行', 1), selected_table(new, r'近期融资执行|2025-03-11', 1)
    if n == 13:
        return selected_table(old, r'E-AC724DAB863B|E-BE56354CE374', 2), selected_table(new, r'E-05D9ED3A429D|E-BE56354CE374', 2)
    return selected_table(old, r'第8章|第12章', 2), selected_table(new, r'第8章|第12章', 2)


def old_assets(report, docx, root):
    """Read embedded originals from the archived DOCX without changing it."""
    targets = re.findall(r'!\[[^]]+\]\(([^)]+)\)', report)
    with ZipFile(docx) as z:
        rels = ET.fromstring(z.read('word/_rels/document.xml.rels'))
        images = {r.attrib['Id']: r.attrib['Target'] for r in rels if r.attrib.get('Type', '').endswith('/image')}
        document = ET.fromstring(z.read('word/document.xml'))
        embeds = [node.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed']
                  for node in document.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}blip')]
        assert len(targets) == len(embeds) == 2
        for target, rid in zip(targets, embeds):
            path = root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(z.read('word/' + images[rid]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-dir', type=Path, required=True)
    p.add_argument('--after-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--assets-dir', type=Path, required=True)
    p.add_argument('--report-link', default='company-report-verified-20261020.html')
    p.add_argument('--same-run-link', default='company-report-same-run-20261020.html')
    args = p.parse_args()
    baseline = args.baseline_dir / '报告正文.txt'
    old_text = baseline.read_text(encoding='utf-8-sig')
    new_text = (args.after_dir / '比亚迪_完整修复后报告.md').read_text(encoding='utf-8')
    old, new = chapters(old_text), chapters(new_text)
    assert set(old) == set(new) == set(range(1, 15))
    old_assets(old_text, args.baseline_dir / '比亚迪股份有限公司_桌面研究整体验收稿.docx', args.assets_dir)
    acceptance = json.loads((args.after_dir / '验收结果.json').read_text(encoding='utf-8'))
    assert acceptance['gate']['passed']
    for t in (old[8], new[8]):
        assert '2.89%' in t and '2.53%' in t
    assert all(re.search(r'近期融资执行 15% \| 3 \|', t) for t in (old[12], new[12]))
    assert all('人员指标的解释边界' in t for t in (old[11], new[11]))
    assert all('松禾' not in t for t in (old[3], new[3]))
    urls = {}
    for t in (old[13], new[13]):
        for line in t.splitlines():
            eid = re.match(r'^\|\s*(E-[A-F0-9]{12})\s*\|', line)
            url = re.search(r'https?://[^\s|]+', line)
            if eid and url:
                urls[eid[1]] = url[0]
    old_ids = set(re.findall(r'\[(E-[A-F0-9]{12})\]', '\n'.join(old[i] for i in range(1, 13))))
    new_ids = set(re.findall(r'\[(E-[A-F0-9]{12})\]', '\n'.join(new[i] for i in range(1, 13))))
    assert len(old_ids) == 51 and len(new_ids) == 39
    labels = {'change': '本次增量调整', 'carry': '已有优化延续', 'coverage': '来源 / 覆盖变化'}
    nav, cards, manifest = [], [], []
    for n in range(1, 15):
        kind, title, previous, current, metric, caveat = NOTES[n]
        original_title = re.sub(r'^## \d+\.\s*', '', new[n].splitlines()[0])
        a, b = excerpts(n, old[n], new[n])
        a = a or '\n'.join(old[n].splitlines()[2:14])
        b = b or '\n'.join(new[n].splitlines()[2:14])
        def pair(left, right):
            return '<div class="pair"><div><div class="doc-label">此前已优化版 · 2026-10-16</div><div class="doc-body">' + render(left, '10月16日已优化版', args.assets_dir, urls) + '</div></div><div><div class="doc-label">最新实测修复版 · 2026-10-20</div><div class="doc-body">' + render(right, '10月20日最新实测版', args.after_dir / 'objects', urls) + '</div></div></div>'
        extra = ''
        if n == 2:
            a_images = '\n'.join(re.findall(r'(?m)^!\[[^]]+\]\([^)]+\)', old[n]))
            b_images = '\n'.join(re.findall(r'(?m)^!\[[^]]+\]\([^)]+\)', new[n]))
            extra = '<details open><summary>两版实际图谱（此前版本已有，不作为本轮新建成果）</summary>' + pair(a_images, b_images) + '</details>'
        badge = 'sync' if kind == 'change' else 'keep' if kind == 'carry' else 'coverage'
        nav.append(f'<a href="#chapter-{n}"><b>{n:02d}</b>' + html.escape(original_title) + '</a>')
        cards.append(f'<article class="chapter" id="chapter-{n}" data-kind="{kind}"><div class="chapter-top"><span class="num">{n:02d}</span><div><span class="badge {badge}">{labels[kind]}</span><p class="subtitle">' + html.escape(original_title) + '</p><h2>' + title + '</h2></div></div><div class="overview"><div class="old"><span class="label">此前已优化版 · 10月16日</span><p>' + previous + '</p></div><div class="new"><span class="label">最新实测修复版 · 10月20日</span><p>' + current + '</p></div></div><div class="result"><strong>' + metric + '</strong><span>' + f'字符数（含引用）：{len(old[n]):,} → {len(new[n]):,}' + '</span></div><p class="why">' + caveat + '</p><h3>两版真实原文</h3>' + pair(a, b) + extra + f'<details><summary>展开第{n}章两版完整正文</summary>' + pair(old[n], new[n]) + '</details></article>')
        manifest.append({'chapter': n, 'kind': kind, 'before_chars': len(old[n]), 'after_chars': len(new[n]),
                         'before_sha256': hashlib.sha256(old[n].encode()).hexdigest(),
                         'after_sha256': hashlib.sha256(new[n].encode()).hexdigest()})
    report_link, same_link = html.escape(args.report_link, quote=True), html.escape(args.same_run_link, quote=True)
    js = '''document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.chapter').forEach(c=>c.classList.toggle('hidden',button.dataset.filter!=='all'&&c.dataset.kind!==button.dataset.filter))}));document.getElementById('present').addEventListener('click',()=>document.body.classList.toggle('present'));const viewer=document.getElementById('viewer');document.querySelectorAll('.zoomable').forEach(img=>img.addEventListener('click',()=>{viewer.querySelector('img').src=img.src;viewer.querySelector('img').alt=img.alt;viewer.showModal()}));viewer.querySelector('button').addEventListener('click',()=>viewer.close());viewer.addEventListener('click',e=>{if(e.target===viewer)viewer.close()});'''
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>公司报告 · 此前已优化版与最新实测版对比</title><style>' + CSS + '.badge.coverage{background:#fff1df;color:#956231}</style></head><body><header><div class="bar"><strong>公司报告 · 版本增量对比</strong><div class="actions"><button id="present">汇报模式</button><a href="' + report_link + '">最新完整报告 ↗</a></div></div></header><div class="layout"><aside><p class="subtitle">已优化版 → 最新实测版</p>' + ''.join(nav) + '</aside><main><section class="hero"><span class="eyebrow">BYD · OPTIMIZED VERSION COMPARISON</span><h1>此前已优化版<br>与本次最新实测版，逐章比较</h1><p>左侧：2026年10月16日“比亚迪_最终验收交付”的完整正文。右侧：2026年10月20日完整复测、修复及交付校验后的正文。</p><p>原有成果继续保留；真正新增的调整与来源覆盖变化分别说明。</p></section><section class="stats"><div class="stat"><strong>14章</strong><span>两版真实正文均可展开</span></div><div class="stat"><strong>5章</strong><span>已有优化延续</span></div><div class="stat"><strong>5章</strong><span>本次增量调整</span></div><div class="stat"><strong>4章</strong><span>来源 / 覆盖变化</span></div></section><div class="scope"><b>基准已校正：</b>这里比较的是“此前已经优化完成的版本”和“本次最终实测版”。此前页面所用的10月20日初稿仅作为<a href="' + same_link + '">同轮问题复现记录</a>保留，不再作为本页的旧优化版本。<br><b>不能重复计算的已有成果：</b>原优化稿已有员工流失率2.89%、员工满意度74.88分、BYD同口径份额15.1%、融资执行3/5，以及风险人员口径和集中核验清单。<br><b>比较限制：</b>两轮来源池、查询时间及取得材料不同；旧版清洗可追溯来源491，本次1559，另有补采原件；正文实际证据编号51 → 39。来源、字数和编号变化不单独证明质量升降，新稿也未承诺逐条覆盖旧稿全部材料。最新比亚迪样本通过本轮生成校验及708项公司回归；这些测试不是两份报告每一个事实的独立尽调证明。</div><div class="toolbar"><button class="active" data-filter="all">全部14章</button><button data-filter="change">增量调整（5章）</button><button data-filter="carry">原有优化延续（5章）</button><button data-filter="coverage">来源 / 覆盖变化（4章）</button></div>' + ''.join(cards) + '<section class="conclusion"><h2>这次应当如何汇报</h2><p>此前已经完成的公司报告优化并未从零重做。本次是在新一轮真实检索与报告生成中检查可复现程度，修复新资料暴露的漏用和解析问题，并改善摘要、跨页项目、来源索引及后续清单。</p><p>员工、客户及同业核心指标、融资3/5和已有风险边界属于延续成果；部分合作方、历史节点与专项材料的覆盖存在变化，页面直接展示原文，不将它们笼统写成“全部升级”。</p><p><a href="' + report_link + '">最新完整报告 ↗</a>　<a href="' + same_link + '">10月20日同轮调试复测对比 ↗</a></p></section><p class="footer">基准原件：公司报告整体验收_20261016 / 比亚迪_最终验收交付 / 报告正文.txt；对应归档Word与最终验收记录已核对。图谱从该归档Word中读取嵌入原图。全文及图谱内嵌，可离线查看，外部来源需联网。</p></main></div><dialog id="viewer"><button type="button">关闭 ×</button><img alt="图谱放大"></dialog><script>' + js + '</script></body></html>'
    assert len(re.findall(r'class="chapter" id="chapter-', page)) == 14
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding='utf-8')
    shutil.copyfile(args.after_dir / '比亚迪_完整修复后报告.html', args.output.parent / args.report_link)
    validation = {'comparison_kind': 'previous_optimized_20261016_vs_latest_repaired_20261020',
                  'before_report_path': str(baseline), 'before_accepted_commit': '2464992',
                  'before_report_sha256': hashlib.sha256(old_text.encode()).hexdigest(),
                  'after_report_sha256': hashlib.sha256(new_text.encode()).hexdigest(),
                  'before_body_evidence_ids': len(old_ids), 'after_body_evidence_ids': len(new_ids),
                  'chapters': manifest, 'already_present_in_old': ['2025 turnover 2.89%', 'employee satisfaction 74.88/100', 'BYD battery usage share 15.1%', 'funding execution 3/5', 'risk personnel interpretation boundary'],
                  'input_corpora_identical': False, 'production_deployed': False,
                  'inline_image_occurrences': page.count('src="data:image/'),
                  'comparison_sha256': hashlib.sha256(page.encode()).hexdigest()}
    args.output.with_suffix('.validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'baseline': str(baseline), 'chapters': len(manifest), 'embedded_images': validation['inline_image_occurrences']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
