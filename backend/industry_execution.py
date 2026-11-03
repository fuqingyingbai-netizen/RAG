"""Industry cancellation is control flow, never a generation failure."""
class IndustryPauseSignal(BaseException):
    """Cross worker futures without being swallowed by model fallback handlers."""

def check_pause(project):
    callback = getattr(project, 'industry_pause_requested', None)
    if callable(callback) and callback():
        raise IndustryPauseSignal()
