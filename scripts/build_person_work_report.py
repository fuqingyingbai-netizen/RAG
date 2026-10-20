"""Build the Friday briefing from tracked audits; no research/model requests."""
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'deliverables/person-work-report-20261023/dist'

# Editorial summaries of the changes, not verbatim quotes or verified findings.
CHAPTERS = [
    dict(n=1, short='摘要', group='结论与交付', headline='摘要跟随正文，不先替人物下结论',
         before='摘要容易混入公司概况和泛化评价；正文尚有缺口时，摘要的语气与依据不一致。',
         after='只汇总正文实际引用的材料，区分已知信息、待复核分析和研究限制。正文未解决的问题继续传到摘要。',
         method='从已入选的章节事实生成摘要候选；同行资料与单方观点不进入确定发现，保留上游复核状态。',
         effect='最终摘要引用10个编号，继承正文的待复核状态。重点是收紧结论来源，不是增加摘要长度。',
         gap='关键章节仍有缺口，摘要不能独立给出人物信用等级或正式验收结论。',),
    dict(n=2, short='创始人底色画像', group='人物与团队', headline='把公司背景与本人履历分开',
         before='整段企业资料曾进入履历章；公司成立日、网页日期和任职时间容易混用。',
         after='保留身份附带线索，将人员任职、机构、事件时间分别记录；公司材料不再直接充当个人履历。',
         method='使用姓名、机构及用户提供别名锚定身份；按可定位的短记录选材，出生与公司成立日期不充当任职起点。',
         effect='本章仍有12个引用编号，但记录粒度和归属收紧；引用数量相同不表示内容没有变化。',
         gap='教育与早年经历、履历断点和现任时期仍需原件核对；家庭健康资料缺失不作为负面。',),
    dict(n=3, short='人格特质风险', group='人物与团队', headline='公开发言可以记录，人格诚信不能硬推',
         before='公司业绩、法定责任声明或公开发言可能被拿来推导人格、诚信和抗压能力。',
         after='只保留与本人有关的行为和表达线索；有证据边界的分析待复核，无依据的人格结论继续拦截。',
         method='排除年报通用责任声明；检查主体与推理跨度，禁止把公司结果或一次发言当成人格鉴定。',
         effect='引用编号从4个收紧为3个。减少误选比凑齐篇幅更重要。',
         gap='缺少跨事件、跨时期、不同立场的直接材料，当前不能确认人格或诚信特质。',),
    dict(n=4, short='经营胜任力与创新', group='能力与管理', headline='公司取得结果，不等于已证明个人贡献',
         before='企业经营、融资或创新资料以整块材料进入分析，个人职责与公司结果容易混在一起。',
         after='按事件记录个人角色、指标、数值、单位与时期，公司经营资料保留在公司归属下。',
         method='拆分结构化记录；比较时检查主体、指标和时期，间接企业记录不允许追加个人能力分析。',
         effect='保留12个引用编号；现在先核对职责与结果之间的关系，再决定是否可作能力分析。',
         gap='战略、执行、资本资源及创新成果的个人贡献仍需补证，暂不做能力评分。',),
    dict(n=5, short='识人用人与经营管控', group='能力与管理', headline='从管理口号，回到授权、用人与具体事件',
         before='概括性的管理评价较多，缺少可追溯的授权、关键岗位与冲突处理资料。',
         after='围绕权责、授权、用人与经营管控选材；把管理事实和模型评价分开。',
         method='按章节任务分配原文，写作模型只收到允许分析的记录，不能使用内部控制字段编写结论。',
         effect='引用编号从6个增至12个，增加了可追溯的材料入口；部分分析仍需复核。',
         gap='权责边界、实际用人决策和组织稳定性的事件链还不完整。',),
    dict(n=6, short='核心管理团队背景', group='人物与团队', headline='团队成员的经历，不能记到目标人物名下',
         before='同姓亲属、团队成员和目标本人可能因附近共现而混选。',
         after='明确其他人员只用于团队背景，保留成员姓名、职责与关系边界。',
         method='增加同姓亲属与其他成员归属检查；目标人物分析输入排除他人经历，人员记录带章节标签。',
         effect='保留12个引用编号；修复了把兄长资格说明误当目标人物材料的实际问题。',
         gap='实际任期、关键人员变动及成员间的治理关系仍需核实。',),
    dict(n=7, short='商业操守与个人信用', group='重点补证', headline='先剔除企业信用杂项，再补本人承诺与具名陈述',
         before='统一社会信用代码、公司简介等曾进入个人信用章；这类引用看似有材料，实际不能回答个人操守。',
         after='按具名评价者、个人契约与履约事件定向检索，保留原文、评价者、关系、日期及核验边界。',
         method='排除匿名、自夸和公司产品评价；报道日期与事件时间分开；单方争议不作为已证实事实或自动风险评分。',
         effect='首轮4个杂项引用先清到0，再补至6个来源陈述，包含承诺披露及一条具名历史争议陈述。6个编号不等于6个独立事件。',
         gap='承诺是否履行、评价者利益关系、目标回应及原始处理结果仍待核查，授权访谈尚未完成。',),
    dict(n=8, short='同业对标', group='重点补证', headline='从“感谢同行”，改为有依据地选人、分别查人',
         before='同行致谢、全球竞争力宣传和公司概况曾被当成横向比较材料，缺少真正的可比人物。',
         after='先从原文提名候选，再按候选姓名与机构分别检索；候选资料与目标人物账本隔离。',
         method='提名保存姓名、机构、职务和比较依据；分别检查行业、阶段、职责、时期、指标与单位。未对齐就不排名。',
         effect='首轮3个误选引用清到0，再补至11条资料及提名依据，建立2位候选。现有页面含百科和机构介绍，不能当作官方任职证明。',
         gap='候选的一手披露、发展阶段、对应时期和同口径指标仍缺，尚不支持能力或品行排名。',),
    dict(n=9, short='关联利益与司法核查', group='司法与治理', headline='先核实人企关系，再解释司法记录',
         before='已有任职材料未充分进入关联章节；公司风险、扫描摘要和个人责任容易混为一谈。',
         after='主定位公司先核对任职与关联关系，再查司法、执行、失信和历史记录。',
         method='为关键查询保留专业预算；区分查到、明确空结果、失败、未查及返回待核验，保持当事人与时期边界。',
         effect='引用编号从8个变为9个；平台返回无记录或访问限制分别展示，不写成“本人无风险”。',
         gap='案件当事人、案号、时期、实际责任及关联交易原件仍需逐条核查。',),
    dict(n=10, short='专项调研', group='重点补证', headline='用户问什么，就按问题组织证据和缺口',
         before='持股、任职等材料已有留存，却未稳定进入对应专项；公司概况容易填充专项。',
         after='重点问题、专项要求与身份线索贯穿创建、启动、续跑和写作，专项逐问题列材料与未解事项。',
         method='按个人主体、持股及任职、关联关系、事件时期等匹配材料；股数、比例及公司其他股东不混用。',
         effect='引用编号从1个增至12个，建立问题到材料的对应关系；有材料不等于历史变化已证明。',
         gap='持股及任职变化仍需前后两个可核对时点，专项中的司法、经营及对标问题仍有缺口。',),
    dict(n=11, short='投后治理与退出', group='司法与治理', headline='补治理权限与历史约束，不凭职位推导退出权',
         before='泛化治理和退出建议较多，授权、锁定和适用条件材料不足。',
         after='围绕决策权限、重大事项、历史锁定、回购及退出条款补证，历史与现行分开。',
         method='治理权限与退出安排列为定向缺口；来源条款保留时期，不把历史锁定资料解释为当前退出权利。',
         effect='引用编号从4个增至12个，已有授权与历史锁定资料入口，结论仍受条款适用条件限制。',
         gap='当前协议、实际决策权限、投资方沟通及退出触发条件需要进一步核实。',),
    dict(n=12, short='风险核查', group='司法与治理', headline='风险写发现与查询范围，不靠词语误命中',
         before='“执行董事”可能误触发司法执行；企业记录和查询空白容易被误写成个人风险或无风险。',
         after='分别列直接信号、关联企业间接信息与未核验事项，司法查询状态另外记录。',
         method='排除职务词与司法词歧义，间接企业记录不进入个人风险评分；供应商空结果不充当无风险证明。',
         effect='首轮7个混合引用收紧至3个相关来源陈述。减少错误归因，而非追求风险条目变多。',
         gap='直接信号、间接关系及司法覆盖范围尚需逐项人工确认。',),
    dict(n=13, short='综合评估', group='结论与交付', headline='保留有依据的分析，同时写清复核理由',
         before='推理有问题时可能整段被拦截，用户难以看出哪些材料可用、哪些判断待确认。',
         after='有真实支持但仍需判断的分析，以“待复核＋原因＋引用＋核验动作”保留；明确错误继续拦截。',
         method='把可复核分析与确定事实分开；不存在编号、错误主体、改写原文、未知数字和无依据人格结论不能靠标记放行。',
         effect='引用编号从11个变为10个，综合评估继承上游缺口，不自动评级或宣布通过。',
         gap='复核规则不能替代完整语义验证，关键结论仍需人工决定采用、修改或删除。',),
    dict(n=14, short='信息来源', group='结论与交付', headline='引用能回原文，查询结果也能区分状态',
         before='搜索摘要、整段专业平台返回和实际正文的边界不够清晰，编号与来源数量容易混看。',
         after='统一证据编号、原文、归属与来源索引；保留专业查询状态和引用边界。',
         method='事实与引用由程序输出，模型不重抄原文；同行、个人和关联企业分开，转载按证据家族去重。',
         effect='索引中实际引用编号从33个变为65个；当前归档76个来源。编号、来源、独立事件和已核实事实是不同口径。',
         gap='来源可信度、同源转载及原始出处仍需复核，索引完整不代表内容真实。',),
    dict(n=15, short='后续研究点', group='结论与交付', headline='从泛化建议，改成逐章可执行的补证清单',
         before='后续建议偏通用，模型拦截和检索缺口不容易转成具体行动。',
         after='逐章收集未解决维度，给出所需原件、核验动作及查询范围，不用推测填空。',
         method='缺口从章节证据包汇总；专业查询覆盖保留，去掉重复泛化清单。Word导出与内容验收分别记录。',
         effect='本章继续不新增事实引用，负责汇总行动；此前复验已保留47项合并查询范围记录。',
         gap='按清单补关键原件、人工核对人物与结论，并完成Word逐页视觉验收。',),
]


def main():
    original = json.loads((ROOT/'docs/PERSON_FULL_RUN_VALIDATION_20261020.json').read_text(encoding='utf-8'))
    current = json.loads((ROOT/'docs/PERSON_REPUTATION_PEERS_VALIDATION_20261020.json').read_text(encoding='utf-8'))
    old = {c['chapter']: c for c in original['chapters']}
    new = {c['chapter']: c for c in current['chapters']}
    esc = html.escape
    sections, nav, rows = [], [], []
    for item in CHAPTERS:
        n = item['n']
        first, latest = old[n]['before_eids'], new[n]['after_cited_ids']
        count = f'{first} → {latest}'
        if n in (7, 8):
            count = f'{first} → 0 → {latest}'
        nav.append(f'<a href="#chapter-{n}" data-jump="chapter-{n}"><span>{n:02}</span>{esc(item["short"])}</a>')
        stage_note = '误选清理后，再补证' if n in (7, 8) else '首轮 → 当前 · 引用编号'
        sections.append(f'''<article id="chapter-{n}" class="slide chapter" data-number="{n}" data-title="{esc(item['short'])}" data-group="{esc(item['group'])}">
          <div class="chapter-heading"><span class="chapter-no">{n:02}</span><div><p class="eyebrow">第{n}章 · {esc(item['short'])}</p><h2>{esc(item['headline'])}</h2></div><span class="category">{esc(item['group'])}</span></div>
          <div class="comparison"><section class="before"><span class="label">优化前 · 问题</span><p>{esc(item['before'])}</p></section><section class="after"><span class="label">现在 · 做法</span><p>{esc(item['after'])}</p></section></div>
          <div class="mechanism"><span class="label">具体怎么改</span><p>{esc(item['method'])}</p></div>
          <div class="result"><div class="count"><b>{count}</b><span>{stage_note}</span></div><p>{esc(item['effect'])}</p></div>
          <div class="pending"><span>仍需完善</span><p>{esc(item['gap'])}</p></div>
        </article>''')
        rows.append({**item, 'first_run_cited_ids': first, 'after_cited_ids': latest,
                     'after_review_status': new[n]['after_review_status'],
                     'current_remaining_gaps': new[n]['remaining_gaps']})
    template = (ROOT/'scripts/templates/person-work-report.html').read_text(encoding='utf-8')
    page = template.replace('<!-- CHAPTER_NAV -->', ''.join(nav)).replace('<!-- CHAPTERS -->', '\n'.join(sections))
    evidence = {
        'purpose': 'Friday_work_briefing_not_person_investigation_delivery',
        'briefing_date': '2026-10-23', 'evidence_as_of': '2026-10-20',
        'reference': 'https://test-d9gn6tepedabd30fb-1451499210.tcloudbaseapp.com/work-report/company/index.html',
        'comparison': {'before_run': original['baseline_run'], 'after_run': current['after'],
                       'before_sources': 35, 'after_sources': current['retained_source_count'],
                       'same_subject': True, 'same_source_corpus': False,
                       'not_original_main_branch_baseline': True,
                       'middle_zero_for_chapters_7_8': current['before']},
        'person_test_passed': current['cross_person_regression']['person_suite_passed'],
        'cross_person_tests': current['cross_person_regression'],
        'formal_report_accepted': False, 'word_visual_qa': current['word_visual_qa'],
        'website_build_new_research_or_model_requests': 0, 'chapters': rows,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT/'index.html').write_text(page, encoding='utf-8')
    (OUTPUT/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    readme = '''# 人物报告优化工作汇报 · 2026-10-23

`dist/index.html`是独立H5，双击可离线使用，不依赖外部字体、脚本、图片或API。支持章节导航、重点章节筛选和打印，六步工作流及15章对比均直接展开。页面已标明材料截至2026-10-20。

`dist/evidence.json`保存逐章工作描述和引用计数口径，未包含API密钥、原始平台返回、人物争议引语或司法明细。

真实对照采用同一人物的首轮完整运行（35来源）与当前补证复验（76来源），材料不同，不作为准确率、稳定提速或账单节省实验；不是原始main分支对照。第7/8章中间0引用指剔除不适用材料后的上一轮稿，不代表首次完全没有引用。

四行业用例是模拟来源的工作流回归，不是四位真实人物的完整线上验收。165项人物测试通过不等于报告内容已经验收。Word逐页视觉检查仍未完成。

重新生成：在仓库根目录运行`python scripts/build_person_work_report.py`。不调用研究、模型或专业平台API。

腾讯云静态托管：上传`dist`内两个文件到`/work-report/person/`，将获得`/work-report/person/index.html`入口。该包不修改已有公司汇报。仓库另保留Sites托管配置；线上地址以实际发布返回为准。
'''
    (OUTPUT.parent/'README.md').write_text(readme, encoding='utf-8')
    print(json.dumps({'output': str(OUTPUT), 'chapters': len(rows), 'sha256': hashlib.sha256(page.encode()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
