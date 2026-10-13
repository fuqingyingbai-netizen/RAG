from .company import CompanyResearchStrategy
from .industry import IndustryResearchStrategy
from .person import PersonResearchStrategy


_STRATEGIES = {
    "company": CompanyResearchStrategy(),
    "industry": IndustryResearchStrategy(),
    "person": PersonResearchStrategy(),
}


def get_research_strategy(target_type: str):
    return _STRATEGIES.get(str(target_type or "company").lower(), _STRATEGIES["company"])


__all__ = [
    "CompanyResearchStrategy",
    "IndustryResearchStrategy",
    "PersonResearchStrategy",
    "get_research_strategy",
]
