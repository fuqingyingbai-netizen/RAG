"""Read-only recovery guidance derived from persisted project records.

No model, network, storage lookup, automatic retry or database mutation is used.
File keys alone are not proof that a downloadable file still exists.
"""
import os
import re
from datetime import datetime


STAGES = {
    'init': '初始化', 'planning': '研究规划', 'web_search': '在线检索',
    'collecting': '资料收集', 'searching': '资料检索', 'structured_data': '专业平台采集',
    'ocr': '文件识别', 'quality': '来源质量评估', 'source_assessing': '来源质量评估',
    'cleaning': '数据清洗', 'risk': '风险研判', 'risk_scoring': '风险研判',
    'risk_assessing': '风险研判', 'report': '报告生成', 'report_generating': '报告生成',
    'proposal': '建议书生成', 'proposal_generating': '建议书生成',
}
REPORT_TYPES = {'desktop_report', 'proposal'}
RUN_NOTICE = ('继续或重跑会重新检查已存资料与成果，只有符合当前规则的阶段才可能复用；'
              '不保证从失败位置直接接续，缺失或失效的环节会重新执行，可能再次联网或调用付费模型。'
              '已有报告记录不会被此次操作删除。')


def metadata(row):
    value = getattr(row, 'artifact_metadata', None)
    return value if isinstance(value, dict) else {}


def newest(rows):
    return max(rows, key=lambda row: (row.version or 0, row.created_at or datetime.min, row.id or 0), default=None)


def failure_reason(text):
    """Expose actionable categories, never raw provider errors or credentials."""
    text = str(text or '').lower()
    for code, terms, reason, advice in [
        ('auth', ('unauthorized', 'authentication', 'invalid api', 'invalid_api', '401', '403', '鉴权', '认证失败'),
         '服务鉴权或访问权限检查未通过', '请管理员检查对应服务的凭据和权限，修复后再继续。'),
        ('limit', ('429', 'rate limit', 'ratelimit', 'quota', 'insufficient balance', 'insufficient_balance', '余额不足', '额度', '限流'),
         '服务请求受限或可用额度不足', '请稍后重试，或请管理员检查服务额度及并发限制。'),
        ('timeout', ('timeout', 'timed out', '超时'),
         '本次请求未在规定时间内完成', '可稍后继续；系统会重新检查哪些已存数据仍可复用。'),
        ('storage', ('no space left', 'disk full', '磁盘空间不足'),
         '保存数据所需的存储空间不足', '请管理员检查存储空间与服务状态，确认恢复后再继续。'),
        ('connection', ('connection', 'connecterror', '连接失败', '无法连接'),
         '本次执行未能连接所需服务', '请检查网络和对应服务状态，恢复后再继续。'),
        ('evidence', ('no evidence', 'insufficient evidence', '证据不足', '资料不足', '无可用资料'),
         '当前可用资料不足以完成本次步骤', '请补充可读取的资料或调整研究范围，再决定是否继续。'),
    ]:
        if any(re.search(r'\b' + re.escape(term) + r'\b', text) if term.isdigit() else term in text for term in terms):
            return {'code': code, 'reason': reason, 'advice': advice}
    return {'code': 'unclassified', 'reason': '本次失败未记录可识别的具体原因',
            'advice': '请结合下方工作流记录核对；必要时请管理员检查服务日志。'}


def workflow_context(trace, artifacts):
    events = [event for event in trace if isinstance(event, dict)]
    starts = [i for i, event in enumerate(events) if event.get('stage') == 'init' and event.get('status') == 'running']
    if starts:
        events = events[starts[-1]:]
    error = next((event for event in reversed(events) if event.get('status') in {'error', 'failed'}), {})
    stage = next((event.get('current_stage') or event.get('stage') for event in reversed(events)
                  if (event.get('current_stage') or event.get('stage')) in STAGES), '')
    if not stage:
        journal = newest([row for row in artifacts if row.artifact_type == 'industry_run'])
        meta = metadata(journal)
        if meta.get('run_status') in {'failed', 'paused'} and meta.get('current_stage') in STAGES:
            stage = meta['current_stage']
    return STAGES.get(stage, '未记录具体阶段'), failure_reason(error.get('detail'))


def build_recovery(project, sources, artifacts, trace, *, running=False, artifact_metadata=None, artifact_text_present=None):
    """Only confirmed database records support retention and download claims."""
    resume = os.getenv('WORKFLOW_RESUME_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
    latest = {kind: newest([row for row in artifacts if row.artifact_type == kind]) for kind in REPORT_TYPES}
    def has_text(row):
        if artifact_text_present is not None and row.id in artifact_text_present:
            return bool(artifact_text_present[row.id])
        return bool((row.content or '').strip())
    saved_text = [row for row in artifacts if row.artifact_type in REPORT_TYPES and has_text(row)]
    run_notice = RUN_NOTICE if resume else '当前未开启阶段复用，将重新执行研究流程，可能再次调用付费服务；已有报告记录仍保留。'
    result = {
        'running': bool(running), 'run_notice': run_notice,
        'saved': {'source_records': len(sources), 'report_text_records': sum(row.artifact_type == 'desktop_report' for row in saved_text),
                  'proposal_text_records': sum(row.artifact_type == 'proposal' for row in saved_text)},
        'retention_notice': '这里只统计已写入系统的记录与正文；原件可用性请实际下载核对，完成度以工作流记录为准。',
        'issues': [],
    }
    if project.status in {'failed', 'paused'}:
        stage, reason = workflow_context(trace, artifacts)
        paused = project.status == 'paused'
        result['issues'].append({
            'kind': 'workflow', 'title': '任务已暂停' if paused else '研究流程未完成', 'stage': stage,
            'reason': '任务处于暂停状态' if paused else reason['reason'],
            'advice': '可在核对已存成果后，按当前规则继续。' if paused else reason['advice'],
            'reason_code': 'paused' if paused else reason['code'],
            'actions': [] if running else [{'kind': 'run', 'label': '继续任务' if resume else '重新执行',
                'description': run_notice}],
        })
    failed_sources = [row for row in sources if (isinstance(row.source_metadata, dict) and row.source_metadata.get('extraction_status') == 'failed')]
    if failed_sources:
        result['issues'].append({
            'kind': 'parsing', 'title': '有文件未成功提取文字', 'stage': '文件解析',
            'reason': f'已有来源记录中有 {len(failed_sources)} 项记录了文字提取失败。',
            'advice': '请检查文件是否可正常打开、文字是否清晰。可补充文字版或重新整理资料；原件是否可用，请实际下载核对。',
            'actions': [] if running else [{'kind': 'review', 'label': '补充资料'}],
        })
    for row in latest.values():
        if row is None:
            continue
        meta = (artifact_metadata or {}).get(row.id, metadata(row))
        stored_text = has_text(row)
        download = [{'kind': 'download', 'label': '下载已保存成果', 'artifact_id': row.id}] if stored_text else []
        if meta.get('docx_export_error'):
            result['issues'].append({
                'kind': 'export', 'artifact_id': row.id, 'title': 'Word 文件导出未成功', 'stage': 'Word 导出',
                'reason': '成果正文已保存在系统中，但本条记录的 Word 导出失败。' if stored_text else '本条记录标记了 Word 导出失败，未确认有可用正文。',
                'advice': '可先查看历史记录或下载已有成果。目前没有只重新导出 Word 的独立入口，重跑研究可能再次调用模型。',
                'actions': download + [{'kind': 'history', 'label': '查看历史版本', 'artifact_type': row.artifact_type}],
            })
        if row.artifact_type == 'desktop_report' and meta.get('knowledge_sync_status') == 'failed':
            actions = [{'kind': 'retry_knowledge', 'label': '重试入库', 'artifact_id': row.id}] if stored_text and not running else []
            result['issues'].append({
                'kind': 'knowledge', 'artifact_id': row.id, 'title': '报告尚未完成知识库入库', 'stage': '知识库入库',
                'reason': '研究报告正文已保存，但入库或索引处理失败。' if stored_text else '入库处理失败，尚未确认有可用的报告正文。',
                'advice': '重试入库只重新提交这份报告进入知识库处理队列，不重新生成研究报告。后续解析和索引仍需等待处理；可在公司知识库查看状态。',
                'actions': actions + download,
            })
    return result
