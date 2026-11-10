import sys
from pathlib import Path
repo=Path('E:/projects/RAG/work/knowledge-update-fixes-20261110b')
sys.path[:0]=[str(repo/'backend'),str(repo/'test')]
import company_knowledge as kb
# These are route/content regression tests. Ingestion/recycle startup is covered
# by the earlier full suite; do not launch those background workers per fixture.
kb.router.on_startup.clear();kb.router.on_shutdown.clear()
import pytest
raise SystemExit(pytest.main([str(repo/'test/test_company_answer_exports.py'),'-q','--tb=short',
    '--junitxml=E:/projects/RAG/work/knowledge-update-audit-20261110b/export-fixed-regression.xml']))
