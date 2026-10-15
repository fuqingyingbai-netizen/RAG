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
