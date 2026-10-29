"""Execution failures may be retained for audit, never reused as successful work."""


def stage_cache_issue(payload, kind):
    if not isinstance(payload, dict):
        return 'invalid_saved_payload'
    if payload.get('workflow_error'):
        return 'previous_execution_failed'
    if kind == 'cleaned_facts':
        diagnostic = payload.get('cleaning_diagnostic') or {}
        # Preserve usable partial model extraction. A circuit-open run with
        # only rule facts must get a fresh attempt on an explicit new run.
        if diagnostic.get('circuit_open') and not any(
            f.get('cleaning_method') == 'llm' for f in payload.get('facts', []) if isinstance(f, dict)):
            return 'previous_cleaning_model_failed'
    if kind == 'risk_assessment':
        status = (payload.get('validation_diagnostics') or {}).get('primary_status')
        if status in {'empty_or_invalid_json', 'request_failed', 'connection_failed'}:
            return 'previous_risk_request_failed'
    return ''
