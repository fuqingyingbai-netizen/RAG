"""Fourteen isolated chapter writers; deterministic tables remain evidence-bound."""
import hashlib
import re
import threading
from company_chapters import chapter, prompt_contract, VERSION


class CompanyChapterAgent:
    def __init__(self, number, project, emit, trace_emit=None):
        self.spec = chapter(number)
        self.project = project
        self.emit = emit
        self.trace_emit = trace_emit
        self._lock = threading.Lock()
        self.model_calls = 0

    @property
    def number(self):
        return self.spec['chapter']

    def _event(self, label, status, **extra):
        self.emit(self.trace_emit, 'report', self.spec['agent_id'], label,
            self.spec['title'], status=status, chapter=self.number,
            chapter_id=self.spec['id'], template_version=VERSION, **extra)

    def execute(self, operation, *, phase='evidence_render'):
        self._event('章节Agent开始', 'running', phase=phase)
        try:
            text = operation()
            headings = [int(n) for n in re.findall(r'(?m)^##\s+(\d+)[.、．]', text or '')]
            if any(n != self.number for n in headings):
                raise ValueError('Chapter agent attempted to write another chapter.')
            if not headings:
                text = f"## {self.number}. {self.spec['title']}\n\n" + str(text or '')
            self._event('章节Agent完成', 'done', phase=phase)
            return text
        except Exception:
            self._event('章节Agent未完成', 'error', phase=phase)
            raise

    def invoke(self, invoke, role, prompt, trace_emit=None):
        bound = prompt_contract(self.number, str(self.project.target_name)) + prompt
        with self._lock:
            self.model_calls += 1
        self._event('章节Agent模型调用', 'running',
                    prompt_sha256=hashlib.sha256(bound.encode()).hexdigest())
        return invoke(role + '｜' + self.spec['agent_id'], bound,
                      self.trace_emit if trace_emit is None else trace_emit)

    def metadata(self):
        journal=getattr(self.project,'_company_flow_journal',None)
        actual=sum(e.get('kind')=='model' and e.get('request_invoked') is True and
            str(e.get('role','')).endswith('｜'+self.spec['agent_id']) for e in journal.data.get('events',[])) if journal else self.model_calls
        return {'chapter': self.number, 'chapter_id': self.spec['id'],
            'agent_id': self.spec['agent_id'], 'title': self.spec['title'],
            'template_version': VERSION, 'template_cells': self.spec['source_cells'],
            'few_shot_status': self.spec['few_shot']['status'], 'model_calls':actual,
            'model_step_calls':self.model_calls,'count_basis':'actual_sdk_invocations' if journal else 'step_invocations_without_journal'}


def create_chapter_agents(project, emit, trace_emit=None):
    return {n: CompanyChapterAgent(n, project, emit, trace_emit) for n in range(1, 15)}
