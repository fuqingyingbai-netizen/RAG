"""Acceptance infrastructure tests; these do not certify candidate business labels."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('industry_acceptance', ROOT / 'scripts/industry_acceptance.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def suite():
    return json.loads(acceptance.DEFAULT_SUITE.read_text(encoding='utf-8'))


def test_frozen_dataset_has_balanced_controls_and_explicit_review_status():
    data = acceptance.validate_suite(suite())
    assert len(data['cases']) == 30
    assert sum(c['expected']['allowed'] for c in data['cases']) == 15
    assert sum(c['split'] == 'challenge' for c in data['cases']) == 8
    assert len({c['category'] for c in data['cases']}) == 15
    assert len({c['scope']['industry_name'] for c in data['cases']}) >= 4
    assert data['label_status'] == 'candidate'
    assert 'not business-reviewed' in data['label_author']
    manifest = json.loads(acceptance.DEFAULT_SUITE.with_name('manifest.json').read_text(encoding='utf-8'))
    assert manifest['suite_sha256'] == acceptance.digest(acceptance.DEFAULT_SUITE)


@pytest.mark.parametrize('change', [
    lambda d: d['cases'].append(deepcopy(d['cases'][0])),
    lambda d: d['cases'][0]['expected'].update(allowed=1),
    lambda d: d['cases'][0].update(target='made_up_gate'),
    lambda d: d.update(label_status='business_reviewed'),
    lambda d: d['cases'][0].pop('rationale'),
    lambda d: d['cases'][0].update(split='unseen_independent_gold'),
])
def test_invalid_or_unearned_labels_are_rejected(change):
    data = suite(); change(data)
    with pytest.raises(ValueError):
        acceptance.validate_suite(data)


@pytest.mark.parametrize('allow,false_allow,false_reject', [(True,15,0),(False,0,15)])
def test_accept_all_and_reject_all_cannot_pass(allow,false_allow,false_reject):
    result = acceptance.evaluate_suite(observer=lambda case: {'allowed':allow,'issues':[]})
    assert not result['passed']
    assert result['metrics']['false_allow'] == false_allow
    assert result['metrics']['false_reject'] == false_reject
    assert sum(row['case_count'] for row in result['by_split'].values()) == 30


def test_extra_labels_are_checked_even_when_the_main_decision_matches():
    case = suite()['cases'][1]
    row = acceptance.compare_case(case, {'allowed':True,'period':'2099','issues':[]})
    assert not row['passed'] and row['differences'][0]['field'] == 'period'


def test_required_error_codes_are_not_replaced_with_any_rejection():
    case = next(c for c in suite()['cases'] if c['id'] == 'IA-003')
    row = acceptance.compare_case(case, {'allowed':False,'issues':['unrelated_error']})
    assert not row['passed']


def test_evaluator_exceptions_are_errors_and_not_successful_rejections():
    def broken(case):
        raise RuntimeError('not a classification')
    result = acceptance.evaluate_suite(observer=broken)
    assert not result['passed'] and result['metrics']['errors'] == 30
    assert result['metrics']['true_reject'] == 0
    assert result['metrics']['false_allow_rate'] is None
    assert result['metrics']['false_reject_rate'] is None


def test_observer_cannot_change_expected_labels_and_network_guard_is_restored():
    original = socket.getaddrinfo
    before = acceptance.digest(acceptance.DEFAULT_SUITE)
    def mutating(case):
        with pytest.raises(RuntimeError, match='offline'):
            socket.getaddrinfo('model.example',443)
        case['expected']['allowed'] = not case['expected']['allowed']
        return {'allowed':case['expected']['allowed'],'issues':[]}
    result = acceptance.evaluate_suite(observer=mutating)
    assert result['metrics']['false_allow'] == result['metrics']['false_reject'] == 15
    assert socket.getaddrinfo is original
    assert acceptance.digest(acceptance.DEFAULT_SUITE) == before


def test_real_production_adapter_keeps_the_wrong_unit_and_correct_amount_distinct():
    bad,good = suite()['cases'][:2]
    original = deepcopy(good)
    with acceptance.offline():
        assert acceptance.observe_case(bad)['allowed'] is False
        assert acceptance.observe_case(good)['allowed'] is True
    assert good == original


def test_full_fixture_evaluation_does_not_import_business_services(monkeypatch):
    import builtins
    original = builtins.__import__
    prohibited = {'database', 'research_workflow', 'research_api', 'model', 'app', 'auth'}
    def isolated(name, *args, **kwargs):
        if name.split('.')[0] in prohibited:
            raise RuntimeError('Business service import is prohibited in acceptance')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', isolated)
    result=acceptance.evaluate_suite()
    assert result['metrics']['case_count']==30 and result['metrics']['errors']==0
    assert result['label_status']=='candidate'


def test_literal_locator_does_not_invent_a_body_for_summary_only_material():
    missing,located = suite()['cases'][10:12]
    assert acceptance.fixture_fact(missing['fact'])[0]['provenance']['locator']['status'] == 'unlocated'
    fact,body = acceptance.fixture_fact(located['fact'])
    loc = fact['provenance']['locator']
    assert body[loc['start']:loc['end']] == loc['quote']


def test_html_review_escapes_material_and_marks_labels_as_candidates():
    data = suite(); data['cases'][0]['rationale'] = '<script>bad()</script>'
    result = acceptance.evaluate_suite(observer=lambda c: {'allowed':False,'issues':[]})
    document = acceptance.render_review(data,result)
    assert '<script>' not in document and '&lt;script&gt;' in document
    assert document.count('<article ') == 30
    assert '尚待业务复核' in document


def historical_manifest(tmp_path,monkeypatch):
    monkeypatch.setattr(acceptance,'ROOT',tmp_path)
    folder = tmp_path/'work/fixture'; folder.mkdir(parents=True)
    payloads = {'cleaned_facts': ('facts.json','{}'), 'risk_assessment':('risk.json','{}'),
        'report': ('report.md','\n'.join(f'## {i}. 合成章节\n正文。' for i in range(1,17))),
        'proposal': ('proposal.md','\n'.join(f'## {i}. 建议章节\n正文。' for i in range(1,8)))}
    files={}
    for kind,(name,body) in payloads.items():
        path=folder/name;path.write_text(body,encoding='utf8')
        files[kind]={'path':str(path.relative_to(tmp_path)),'sha256':acceptance.digest(path)}
    manifest=folder/'manifest.json'
    manifest.write_text(json.dumps({'schema_version':1,'cases':[{
        'id':'H01','business_review_status':'pending','files':files}]}),encoding='utf8')
    return manifest,folder


def test_historical_identity_and_chapter_counts_never_become_business_acceptance(tmp_path,monkeypatch):
    manifest,folder=historical_manifest(tmp_path,monkeypatch)
    result=acceptance.inspect_private_manifest(manifest)
    row=result['cases'][0]
    assert result['integrity_verified'] and row['report_chapters']==list(range(1,17))
    assert row['proposal_chapters']==list(range(1,8))
    assert row['summary_body_chars']==3  # Only chapter one, never the whole report.
    assert row['business_quality_passed'] is None and result['business_quality_passed'] is None
    (folder/'report.md').write_text('changed',encoding='utf8')
    result=acceptance.inspect_private_manifest(manifest)
    assert not result['integrity_verified']
    assert result['cases'][0]['business_quality_passed'] is None


def test_private_output_rejects_public_paths_and_overwriting_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(acceptance,'ROOT',tmp_path)
    with pytest.raises(ValueError):
        acceptance.write_result({}, tmp_path/'docs/leaked.json')
    target=tmp_path/'work/result.json'
    acceptance.write_result({'first':True},target)
    with pytest.raises(ValueError):
        acceptance.write_result({'second':True},target)
    assert json.loads(target.read_text())=={'first':True}


def test_cli_reports_a_semantic_gap_without_relabelling_the_frozen_case(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(acceptance,'ROOT',tmp_path)
    case=deepcopy(suite()['cases'][-2])
    assert case['id']=='IA-029' and case['expected']['allowed'] is False
    path=tmp_path/'work/candidate.json';path.parent.mkdir()
    data={**suite(),'cases':[case]};path.write_text(json.dumps(data),encoding='utf8')
    # A permissive observer deliberately simulates a missed semantic error.
    monkeypatch.setattr(acceptance,'observe_case',lambda c: {'allowed':True,'issues':[]})
    before=acceptance.digest(path)
    output=tmp_path/'work/result.json';review=tmp_path/'work/review.html'
    assert acceptance.main(['--suite',str(path),'--output',str(output),'--review-output',str(review)])==2
    assert json.loads(output.read_text(encoding='utf-8'))['metrics']['false_allow']==1
    assert acceptance.digest(path)==before
    assert 'IA-029' in review.read_text(encoding='utf8')
    assert acceptance.main(['--suite',str(path),'--output',str(path)])==1
    assert acceptance.digest(path)==before


def test_cli_success_and_missing_input_have_distinct_exit_codes(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(acceptance,'ROOT',tmp_path)
    data=suite();data['cases']=[data['cases'][1]]
    path=tmp_path/'one.json';path.write_text(json.dumps(data),encoding='utf8')
    assert acceptance.main(['--suite',str(path)])==0
    assert acceptance.main(['--suite',str(tmp_path/'missing.json')])==1


def test_existing_entrypoint_can_run_acceptance_without_pytest_or_research(monkeypatch):
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location('check_industry_entry', ROOT/'scripts/check_industry.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    def execute(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(module.subprocess,'run',execute)
    assert module.main(['--acceptance-only','--acceptance-output','work/example.json'])==2
    assert len(calls)==1 and calls[0][1].endswith('industry_acceptance.py')
    assert calls[0][-2]=='--output' and Path(calls[0][-1])==Path('work/example.json')
