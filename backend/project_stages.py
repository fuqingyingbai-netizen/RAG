"""Business workspace stage, independent of worker execution status."""

def workflow_stage(status, running=False, intake=None):
    if status == 'draft' and not running:
        return 'intake'
    if status == 'completed' and not running:
        return 'review'
    saved = intake if isinstance(intake, dict) else {}
    explicit = saved.get('workspace_stage')
    if explicit in ('deliverables', 'review'):
        return explicit
    # Legacy formal-plan attempts already persist this marker in project intake.
    if saved.get('stage') in ('formal_plan', 'second_stage'):
        return 'review'
    return 'deliverables'
