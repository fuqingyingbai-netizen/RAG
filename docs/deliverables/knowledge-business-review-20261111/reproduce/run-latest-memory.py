from pathlib import Path
import os,sys
repo=Path('E:/projects/RAG/work/knowledge-business-review-code-20261111');root=Path(__file__).parent
os.environ['PYTHON_DOTENV_DISABLED']='1';os.environ['DATABASE_URL']='sqlite://'
sys.path[:0]=[str(repo/'backend'),str(repo/'test')]
import company_knowledge as kb
import company_workspace as ws
# These cases test request/answer memory, not periodic ingestion/recycle workers.
# The unchanged worker lifecycle remains enabled in the full baseline suite.
for router in (kb.router,ws.workspace_router):router.on_startup.clear();router.on_shutdown.clear()
import pytest
raise SystemExit(pytest.main([str(repo/'test/test_company_memory.py'),str(repo/'test/test_company_memory_routing.py'),'-q','--tb=short','--junitxml='+str(root/'latest-memory-junit.xml')]))
