import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.research_workflow import ResearchWorkflow


def test_structured_entity_candidates_prefer_canonical_company_and_credit_code():
    workflow = ResearchWorkflow()
    project = SimpleNamespace(
        title="硅基流动3.3",
        target_name="硅基流动",
        industry="科技推广和应用服务业 信息技术服务业",
        sources=[
            SimpleNamespace(
                title="硅基流动赴港上市",
                summary="成立仅34个月的北京硅基流动科技股份有限公司递表港交所。",
                content="统一社会信用代码：91110108MACUTWH50K。曾用名：北京硅基流动科技有限公司。",
                source_metadata={},
            )
        ],
    )
    intake = {
        "target_name": "硅基流动",
        "company_name": "硅基流动",
        "industry": "科技推广和应用服务业 信息技术服务业",
    }

    candidates = workflow._structured_entity_candidates(project, intake, "硅基流动")

    assert candidates[:3] == [
        "北京硅基流动科技股份有限公司",
        "91110108MACUTWH50K",
        "北京硅基流动科技有限公司",
    ]
    assert "硅基流动" in candidates
    assert "科技推广和应用服务业信息技术服务业" not in candidates
