"""A fresh source audit must retain registered commits instead of today's HEAD."""
import importlib.util
import json
from pathlib import Path


def test_fetch_uses_registered_commit_and_rejects_stale_cached_head(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('phase1_upstream',Path(__file__).parents[1]/'diagnostics/company_phase1_upstream.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    repo=module.REPOS[0];pin=module.pinned_record(repo)['commit'];urls=[]
    monkeypatch.setattr(module,'OUT',tmp_path)
    folder=tmp_path/repo.replace('/','--');folder.mkdir()
    (folder/'metadata.json').write_text(json.dumps({'status':'pinned','commit':'a'*40}),encoding='utf-8')
    def fetch(url):
        urls.append(url)
        assert not url.endswith('/HEAD')
        return json.dumps({'tree':[],'license':{'spdx_id':'Apache-2.0'}}).encode()
    monkeypatch.setattr(module,'fetch',fetch)
    result=module.inspect(repo)
    assert result['status']=='pinned' and result['commit']==pin
    assert any('/git/trees/'+pin in u for u in urls)
