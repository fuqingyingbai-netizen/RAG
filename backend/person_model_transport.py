"""Retry transient transport failures without changing a writing task or candidate."""
import hashlib
import os
from company_platform import failure_kind


class EmptyPersonModelResponse(RuntimeError):
    """The provider returned no final answer; reasoning is never report prose."""

    def __init__(self, message, *, finish_reason=None):
        super().__init__(message)
        self.finish_reason = finish_reason


def section_model_options(model_name):
    """Bound output generation, never source admission or input records."""
    raw=os.getenv('PERSON_REPORT_SECTION_MAX_OUTPUT_TOKENS','8192')
    try:limit=int(raw)
    except ValueError:raise ValueError('invalid_person_section_output_token_budget') from None
    if not 1024<=limit<=32768:raise ValueError('invalid_person_section_output_token_budget')
    options={'max_tokens':limit}
    streaming = os.getenv('PERSON_REPORT_SECTION_STREAMING', '').strip().lower()
    if streaming:
        if streaming not in {'true', 'false'}:
            raise ValueError('invalid_person_section_streaming_mode')
        options['streaming'] = streaming == 'true'
    if str(model_name or '').lower().startswith('deepseek'):
        thinking=os.getenv('PERSON_REPORT_SECTION_THINKING','disabled').strip().lower()
        if thinking not in {'enabled','disabled'}:raise ValueError('invalid_person_section_thinking_mode')
        options['extra_body']={'thinking':{'type':thinking}}
        if thinking=='enabled':
            effort=os.getenv('PERSON_REPORT_SECTION_REASONING_EFFORT','low').strip().lower()
            if effort not in {'low','high','max'}:raise ValueError('invalid_person_section_reasoning_effort')
            options['reasoning_effort']=effort
    elif str(model_name or '').lower() in {'qwen3.8-max', 'qwen3.8-max-0902'} and os.getenv('PERSON_REPORT_QWEN_THINKING','').strip():
        # Explicit experiment only; existing Qwen calls retain provider defaults.
        # https://platform.qianwenai.com/docs/developer-guides/text-generation/thinking
        thinking = os.environ['PERSON_REPORT_QWEN_THINKING'].strip().lower()
        if thinking not in {'enabled', 'disabled'}:
            raise ValueError('invalid_person_qwen_thinking_mode')
        options['extra_body'] = {'enable_thinking': thinking == 'enabled'}
    elif str(model_name or '').lower()=='glm-5.2' and os.getenv('PERSON_REPORT_SECTION_THINKING','').strip():
        # Explicit opt-in only; preserve the prior default and exact cache key.
        # https://docs.bigmodel.cn/cn/guide/capabilities/thinking
        thinking=os.environ['PERSON_REPORT_SECTION_THINKING'].strip().lower()
        if thinking not in {'enabled','disabled'}:raise ValueError('invalid_person_section_thinking_mode')
        options['extra_body']={'thinking':{'type':thinking}}
    return options


def section_model_context():
    model=os.getenv('PERSON_REPORT_SECTION_MODEL') or os.getenv('MODEL')
    return {'model':model,
        'endpoint_sha256':hashlib.sha256((os.getenv('BASE_URL') or '').rstrip('/').encode()).hexdigest(),
        'temperature':0.2,'request_options':section_model_options(model)}


def invoke_same_input(invoke,role,prompt,emit,audit,field):
    attempts=[]
    record={'attempts':attempts,'exhausted':False}
    audit[field]=record
    for attempt in range(2):
        try:
            result=invoke(role,prompt,emit)
            attempts.append({'status':'returned'})
            return result
        except Exception as exc:
            kind=failure_kind({'error':str(exc)})
            transient=(isinstance(exc,(TimeoutError,ConnectionError)) or type(exc).__name__ in {
                'APIConnectionError','APITimeoutError','InternalServerError','EmptyPersonModelResponse',
                'RemoteProtocolError','ReadError'})
            if isinstance(exc, EmptyPersonModelResponse) and exc.finish_reason == 'length':
                # An exhausted output budget is not a transient disconnect.
                # Keep the candidate pending; a later bounded run can change
                # the evidence partition without resending this same input.
                transient = False
                kind = 'model_output_exhausted'
            attempts.append({'status':'failed','exception_type':type(exc).__name__,'failure_kind':kind})
            if attempt==0 and transient and kind not in {'quota_exceeded','unauthorized','access_denied'}:
                continue
            record['exhausted']=True
            raise
