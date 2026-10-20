"""Company-only delivery claim checks with bounded negation handling."""
import re


OVERCLAIMS = (
    r'(?:司法与)?合规底盘干净',
    r'(?:无|不存在)(?:任何|历史)?(?:行政处罚|诉讼|失信|被执行|违法记录)',
    r'法律合规风险\s*[：:]?\s*0(?:\s|$)',
    r'企业无历史遗留违规',
)
BOUNDARY = re.compile(r'不能(?:直接)?(?:证明|认定|推定|得出|视为)|不(?:代表|等于|足以证明|意味着|构成)|不得(?:写成|表述为|据此认定)|未能证明')


def company_overclaims(report):
    """Return actual unsupported clean conclusions, including table cells.

    A warning such as '不能证明全历史无处罚、无失信' is not that
    conclusion. A later affirmative clause is checked independently; a prior
    disclaimer never exempts the remainder of a paragraph or the report.
    """
    findings = []
    for pattern in OVERCLAIMS:
        for match in re.finditer(pattern, report or '', re.I):
            prefix = (report or '')[max(0, match.start() - 100):match.start()]
            prefix = re.split(r'[。！？\n|；]|但是|然而|不过|实际上|但', prefix)[-1]
            boundary = list(BOUNDARY.finditer(prefix))
            if boundary and len(prefix) - boundary[-1].end() <= 55:
                continue
            findings.append({'claim': match[0], 'offset': match.start()})
    return findings


def source_excerpt(text,limit=90):
    text=re.sub(r'\s+',' ',str(text or '')).strip()
    if len(text)<=limit:return text
    prefix=text[:limit]
    boundaries=list(re.finditer(r'[。！？；;，]|(?<!\d)\.(?=\s|$)',prefix))
    boundary=next((m.end() for m in reversed(boundaries) if m.end()>=limit*.4),None)
    if boundary is not None:prefix=prefix[:boundary]
    else:
        # Do not turn a clipped 5,000,000 into a different apparent amount,
        # nor leave a partial English word as an unmarked original quote.
        token=re.search(r'[A-Za-z0-9][A-Za-z0-9,./%+\-]*$',prefix)
        if token and limit<len(text) and re.match(r'[A-Za-z0-9,./%]',text[limit]):prefix=prefix[:token.start()].rstrip()
    return prefix.rstrip()+'…（节选）'


def company_followup_rows(report,per_chapter=2):
    """Representative actions per chapter; originals remain in each chapter."""
    candidates={};chapter=0;active=False;seen=set()
    heading_pattern=r'核验重点|后续.*(?:核验|材料)|待核验事项|核验判断|需要补充|核心制约与下一步|核查范围与未闭环|原件覆盖界限|模板核查覆盖|需关注信号'
    action_pattern=r'补充|核对|核验|确认|追踪|追索|取得|调取|复核|原页|访谈|尚未形成|尚未取得|仍需|需补|需按|需结合'
    for line in report.splitlines():
        main=re.match(r'^##\s*(\d+)[.、．]',line)
        if main:chapter=int(main[1]);active=False;continue
        if not 1<=chapter<=12:continue
        if line.startswith('#'):
            active=bool(re.search(heading_pattern,line));continue
        explicit=bool(re.match(r'^\s*(?:[-*>]\s*)?(?:待核验(?:重点|事项)?|跟进)[:：]',line))
        if not (active or explicit or (chapter==12 and line.startswith('|') and '未评分' in line)):continue
        if line.lstrip().startswith('|'):
            if chapter!=12 or '未评分' not in line:continue
            cells=[c.strip() for c in line.strip().strip('|').split('|')]
            if len(cells)<3:continue
            text=cells[0]+'：'+cells[2]
        else:text=line.strip(' >-*\t')
        text=re.sub(r'^(?:待核验(?:重点|事项)?|跟进)\s*[:：]\s*','',text)
        # Definitions already bound to chapter 8 metrics are not new actions.
        # Keep the representative appendix slots for actual unresolved work.
        if re.match(r'原页(?:范围/说明|公式|定义)[:：]',text):continue
        if not re.search(action_pattern,text) or not 8<=len(text)<=1200:continue
        if re.match(r'已取得的原件支持|本章尚未取得可据以评估|本章尚未形成可核对的具体历史遗留事件',text):continue
        key=re.sub(r'\s+','',text).strip('。；;')
        if key in seen:continue
        seen.add(key);candidates.setdefault(chapter,[]).append(text)
    return [{'chapter':chapter,'items':items[:per_chapter],'additional':max(0,len(items)-per_chapter)}
            for chapter,items in sorted(candidates.items())]


def company_followup_plan(text):
    if re.search(r'OCR|低文字|扫描(?:页|件)|图像|原页|版面|字形',text,re.I):
        return '回到原PDF对应物理页，复核版面/脚注；按需重提取或OCR并逐项比对。','中','原始PDF、物理页码、页面图像和提取/OCR记录。'
    if re.search(r'平台|接口|数据库',text) and re.search(r'失败|权限|额度|鉴权|未查询|未成功|不可用|接入',text):
        return '核对接入参数及查询范围；恢复可用权限/额度后重查并保存真实返回。','中','查询主体标识、平台回执、查询时间与范围、原始结果及失败记录。'
    if re.search(r'股权|股东|实控|出资|减资',text):
        return '按事件日期核对工商档案、股东名册、协议及实际出资/变更凭证。','高','工商变更档案、股东名册、投资协议和出资凭证。'
    if re.search(r'任职|任期|任命|换届|辞任',text):
        return '核对基准日后的正式公告、任期和生效条件，逐人区分不同岗位。','中','正式任免/换届公告、任期条款、最新名册及生效日期。'
    if re.search(r'裁判|案件|诉讼|仲裁|执行|召回|整改|事故',text):
        return '按具体主体、案号或召回编号追踪后续状态及实际履行/整改结果。','高','原始裁判/执行文件或召回公告、后续履行/整改凭证及金额范围。'
    if re.search(r'资金|现金|融资|回款|合同|订单|客户|供应商',text):
        return '围绕具体对象抽核合同、资金凭证与业务背景；需要时开展独立访谈。','高','合同/订单、银行流水、发票、回款记录与核验对象清单。'
    if re.search(r'员工|流失|培训|绩效|激励|人事',text):
        return '核对人资原始统计、计算分母、制度及执行记录，必要时独立访谈。','中','分岗位人员/离职统计、原始公式、培训/激励执行记录与访谈材料。'
    if re.search(r'内控|组织架构|汇报|授权|决策|议案|董事会',text):
        return '把制度、授权与实际运行记录逐项对照，核对日期、责任主体及闭环结果。','中','组织架构/授权矩阵、议案与表决记录、控制测试和执行材料。'
    return '按所列具体事项复核原始披露、统计范围和后续证明，保留未解决差异。','中','相关原始文件、日期/主体/范围说明及后续核验记录。'
