"""Industry scoring guidance and observable evidence support, without fake confidence.

This is a review rubric, not an empirically calibrated predictor. Evidence coverage
is measured only inside the retained scoring input, never the whole source pool.
"""
from copy import deepcopy

RUBRIC_VERSION = 'industry-risk-rubric-v1'
CALIBRATION_NOTICE = '评分来自模型判断，尚未经过人工标注样本校准；引用校验通过不代表评分合理或可信概率。'
FACTORS = {
    '政策与监管风险': ['现行准入与合规义务', '已发生的限制与执行影响', '政策目标与生效措施的区别'],
    '市场增长与需求风险': ['同口径历史需求趋势', '增长持续性与需求兑现', '实际统计与预测的区别'],
    '竞争格局与集中度风险': ['份额与集中度的年度和分母', '进入壁垒与替代竞争', '定性信号不能证明集中度水平'],
    '商业化与盈利模式风险': ['实际收费机制', '行业盈利与客户留存', '企业样本的外推限制'],
    '技术迭代与替代风险': ['可比测试条件与成本', '替代路径及切换障碍', '已实测与规划预测的区别'],
    '资本热度与估值风险': ['同口径行业融资与估值', '融资兑现与流动性压力', '价格波动与经营风险的区别'],
    '数据口径与证据可靠性风险': ['统计定义与范围一致性', '原文可追溯和证据冲突', '缺少材料本身不能推定高风险'],
}
BANDS = [
    {'level': 'low', 'range': [0, 40], 'upper_inclusive': False, 'anchor': '有适用证据支持风险影响有限且应对机制明确，不能因未发现负面就判低风险。'},
    {'level': 'medium', 'range': [40, 70], 'upper_inclusive': False, 'anchor': '存在已获证据支持的实质压力，影响范围或持续性仍有限。'},
    {'level': 'high', 'range': [70, 85], 'upper_inclusive': False, 'anchor': '有明确证据支持较广泛或持续的重大不利影响，须说明受影响范围。'},
    {'level': 'critical', 'range': [85, 100], 'upper_inclusive': True, 'anchor': '有明确证据支持已发生或迫近的系统性严重影响，不能仅凭预测或缺证。'},
]


def scoring_rubric(scope=None):
    from industry_research import active_risk_dimensions
    return {'version': RUBRIC_VERSION, 'calibration_status': 'not_calibrated',
            'notice': CALIBRATION_NOTICE, 'bands': deepcopy(BANDS),
            'dimensions': [{'name': name, 'factors': list(FACTORS[name])}
                           for name in active_risk_dimensions(scope)],
            'instruction': '先识别证据支持的风险影响、范围及时间性质，再按等级锚点给风险分；证据不足仍unknown。等级内分值为模型判断，不表示损失概率；不把证据覆盖率当风险分。'}


def attach_risk_support(result, facts, scope=None):
    """Overwrite model-supplied confidence/coverage with deterministic observations."""
    from industry_research import RISK_MODULES, risk_fact_applicable, source_document_key
    from industry_evidence import evidence_requirements, fact_coverage
    scope = scope or {}
    # Repeated cards cannot increase support counts.
    eligible = {f['evidence_id']: f for f in facts if f.get('evidence_id')
                and any(risk_fact_applicable(f, name) for name in FACTORS)
                and not (scope.get('capital_market') == 'none' and f.get('module') == '投融资与资本市场')}
    enabled_modules = set().union(*(RISK_MODULES.get(r['name'], set()) for r in result.get('dimensions', [])))
    all_requirements = evidence_requirements(list(enabled_modules), scope)
    rows = []
    for row in result.get('dimensions', []):
        name = row['name']
        candidates = [f for f in eligible.values() if risk_fact_applicable(f, name)]
        cited_ids = set(row.get('evidence_ids') or [])
        cited = [f for f in candidates if f['evidence_id'] in cited_ids]
        requirements = [r for r in all_requirements if name not in RISK_MODULES or r['module'] in RISK_MODULES[name]]
        coverage = fact_coverage(candidates, requirements)['requirements']
        verified = sum(r['status'] == 'verified' for r in coverage)
        numeric = [f for f in cited if (f.get('numeric_validation') or {}).get('passed') is True]
        support = {'scope': 'retained_scoring_input', 'applicable_fact_count': len(candidates),
            'cited_fact_count': len(cited),
            'located_cited_fact_count': sum((f.get('provenance') or {}).get('locator', {}).get('status') == 'verified' for f in cited),
            'validated_numeric_fact_count': len(numeric),
            'forecast_numeric_fact_count': sum(bool((f.get('numeric_context') or {}).get('is_forecast')) for f in numeric),
            'cited_document_count': len({key for f in cited if (key := source_document_key(f.get('source_url', '')))}),
            'required_metric_count': len(coverage), 'verified_metric_count': verified,
            'metric_coverage_ratio': round(verified / len(coverage), 3) if coverage else None,
            'requirements': [{'id': r['requirement_id'], 'question': r['question'], 'status': r['status']}
                             for r in coverage],
            'limitations': ['仅统计本次评分包，未覆盖并不证明行业不存在该指标。',
                           '文档数量不等于独立来源印证，指标覆盖不代表风险判断正确。']}
        confidence = {'status': 'not_calibrated', 'probability': None, 'notice': CALIBRATION_NOTICE}
        row.update(evidence_support=support, assessment_confidence=confidence,
                   rubric_version=RUBRIC_VERSION, assessment_status='assessed' if row.get('score') is not None else 'unknown')
        # Unknown raw-model diagnostics stay in the private audit JSON, not this UI summary.
        rows.append({key: row.get(key) for key in ('name', 'score', 'level', 'assessment_status', 'unknown_cause',
                                                  'evidence_support', 'assessment_confidence')})
    transparency = {'version': RUBRIC_VERSION, 'calibration_status': 'not_calibrated',
        'notice': CALIBRATION_NOTICE, 'aggregation': 'equal_weight_mean_only_when_all_enabled_dimensions_assessed',
        'aggregation_notice': '总分为全部启用维度风险分的等权均值；任一未评估则不出总分，权重尚未经过业务校准。',
        'overall_score': result.get('overall_score'), 'risk_level': result.get('risk_level'), 'dimensions': rows}
    result['scoring_methodology'] = scoring_rubric(scope)
    result['risk_transparency'] = transparency
    return result


def risk_support_markdown(transparency):
    """User-facing explanation also used in the independent quality diagnostic."""
    if not transparency:
        return ''
    def cell(value):
        return str(value).replace('|', '/').replace('\n', ' ')
    rows = []
    for row in transparency.get('dimensions', []):
        support = row['evidence_support']
        rows.append(f"| {cell(row['name'])} | {row['score'] if row.get('score') is not None else '未评估'} | "
                    f"{support['verified_metric_count']}/{support['required_metric_count']} | "
                    f"{support['located_cited_fact_count']}/{support['cited_fact_count']} | 尚未校准 |")
    return ('## 风险评分与证据支持\n\n' + CALIBRATION_NOTICE + '\n\n' + transparency['aggregation_notice']
            + '\n\n指标覆盖按本次评分包统计；原文定位只证明引文可回查。\n\n'
            '| 风险维度 | 风险分 | 已核验指标/要求指标 | 已定位引用/引用事实 | 评分可信度 |\n'
            '| --- | --- | --- | --- | --- |\n' + '\n'.join(rows) + '\n\n')
