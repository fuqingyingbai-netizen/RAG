"""Offline provenance binding of complete report chapter histories."""
import importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location("person_sweep_ancestors_test",Path(__file__).resolve().parents[1]/"scripts/run_person_report_sweep.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def fixture(tmp_path):
    folders=[tmp_path/'work'/str(i) for i in range(3)]
    text='## 2. 履历\n\n同一履历。\n\n## 9. 利益\n\n同一利益记录。\n\n## 10. 专项\n\n同一专项记录。'
    for i,(folder,n) in enumerate(zip(folders,[9,10,2])):
        folder.mkdir(parents=True)
        (folder/'desktop_report.md').write_text(text,encoding='utf-8')
        (folder/'acceptance-results.json').write_text(json.dumps({str(n):{'status':'pending_review'}}),encoding='utf-8')
        summary={'sources_sha256':'same-source','code_unchanged_during_run':True}
        if i:summary['draft_run']=str(folders[i-1])
        (folder/'summary.json').write_text(json.dumps(summary),encoding='utf-8')
    return folders


def test_prior_chapter_progress_survives_later_completed_chapters(tmp_path):
    folders=fixture(tmp_path);found=module.prior_chapter_runs(folders[-1],tmp_path)
    assert found=={9:folders[0],10:folders[1],2:folders[2]}


def test_changed_body_cannot_borrow_a_prior_chapter_candidate(tmp_path):
    folders=fixture(tmp_path);p=folders[-1]/'desktop_report.md';p.write_text(p.read_text(encoding='utf-8').replace('同一利益记录','改变后的利益记录'),encoding='utf-8')
    assert 9 not in module.prior_chapter_runs(folders[-1],tmp_path)


def test_another_source_snapshot_stops_the_ancestry_walk(tmp_path):
    folders=fixture(tmp_path);p=folders[1]/'summary.json';s=json.loads(p.read_text(encoding='utf-8'));s['sources_sha256']='other-source';p.write_text(json.dumps(s),encoding='utf-8')
    assert module.prior_chapter_runs(folders[-1],tmp_path)=={2:folders[-1]}


def test_a_cycle_in_metadata_never_loops_or_invents_a_new_origin(tmp_path):
    folders=fixture(tmp_path);p=folders[-1]/'summary.json';s=json.loads(p.read_text(encoding='utf-8'));s['draft_run']=str(folders[-1]);p.write_text(json.dumps(s),encoding='utf-8')
    assert module.prior_chapter_runs(folders[-1],tmp_path)=={2:folders[-1]}
