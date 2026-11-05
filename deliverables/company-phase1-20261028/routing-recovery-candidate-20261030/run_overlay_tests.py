"""Exercise exact candidate paths in a separate Python process."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

here=Path(__file__).resolve().parent;root=here.parents[2]
overlay=root/'work/company-phase1-20261028/routing-candidate-overlay'
sys.path[:0]=[str(overlay/'test'),str(root/'backend'),str(root/'test'),str(root)]
package_root=root/'backend/report_agents'
spec=importlib.util.spec_from_file_location('report_agents',package_root/'__init__.py',
    submodule_search_locations=[str(overlay/'backend/report_agents'),str(package_root)])
package=importlib.util.module_from_spec(spec);sys.modules['report_agents']=package;spec.loader.exec_module(package)
from report_agents import company_information_usage,company_information_journal,company_report_agent
manifest=json.loads((here/'candidate-manifest.json').read_text(encoding='utf-8'))
observed={}
for module in [company_information_usage,company_information_journal,company_report_agent]:
    path=Path(module.__file__).resolve();assert path.is_relative_to(overlay)
    relative=path.relative_to(overlay).as_posix();digest=hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest==manifest['paths'][relative]['candidate_utf8_sha256']
    observed[relative]=digest
(here/'overlay-runtime-proof.json').write_text(json.dumps({'loaded_candidate_modules':observed,
    'patch_sha256':manifest['patch_sha256'],'live_backend_modified':False},indent=2)+'\n',encoding='utf-8')
import pytest
args=sys.argv[1:] or ['-q',str(overlay/'test')]
raise SystemExit(pytest.main(args))
