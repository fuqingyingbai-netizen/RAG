from typing import Any, Optional

from pydantic import BaseModel, Field


class ResearchProjectCreate(BaseModel):
    title: str
    target_name: str = ""
    target_type: str = "company"
    industry: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchProjectResponse(BaseModel):
    id: int
    title: str
    target_name: str
    target_type: str
    industry: str
    description: str
    status: str
    created_at: str
    updated_at: str


class ResearchProjectListResponse(BaseModel):
    projects: list[ResearchProjectResponse]


class ResearchSourceCreate(BaseModel):
    source_type: str = "manual"
    title: str
    url: str = ""
    content: str
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    credibility_score: int = 60


class ResearchSourceResponse(BaseModel):
    id: int
    project_id: int
    source_type: str
    title: str
    url: str
    summary: str
    credibility_score: int
    created_at: str


class ResearchArtifactResponse(BaseModel):
    id: int
    project_id: int
    artifact_type: str
    title: str
    version: int
    content: str
    object_key: str
    metadata: dict[str, Any]
    created_by: str
    created_at: str


class ResearchRunRequest(BaseModel):
    search_queries: list[str] = Field(default_factory=list)
    focus_questions: list[str] = Field(default_factory=list)
    target_type: str = ""
    max_results_per_query: int = 30
    generate_proposal: bool = True
    client_name: str = ""
    deadline: str = ""
    company_name: str = ""
    official_identifier: str = ""
    affiliation: str = ""
    focus_entities: str = ""
    region: str = ""
    research_type: str = "商业尽调"
    focus_modules: list[str] = Field(default_factory=list)
    ai_search_enabled: bool = True
    special_requirements: str = ""
    # Optional, plain-language industry research inputs.  They deliberately do
    # not require users to understand research taxonomy; the workflow converts
    # them into a bounded ``industry_scope`` with explicit assumptions.
    industry_focus: str = ""
    research_purpose: str = ""
    include_capital_markets: Optional[bool] = None
    as_of_date: str = ""
    min_sources_per_module: int = 5
    max_search_rounds: int = 3


class ResearchRunResponse(BaseModel):
    project: ResearchProjectResponse
    artifacts: list[ResearchArtifactResponse]
    sources_added: int


class ResearchRevisionRequest(BaseModel):
    artifact_type: str
    instructions: str
    base_artifact_id: Optional[int] = None

class ResearchAssistantRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    limit: int = 8
    history_summary: str = ""
    recent_messages: list[dict[str, str]] = Field(default_factory=list)

class ResearchUploadResponse(BaseModel):
    source: ResearchSourceResponse
    message: str

