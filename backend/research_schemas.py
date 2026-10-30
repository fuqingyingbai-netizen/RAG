from typing import Any, Optional

from datetime import date

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator


class ResearchProjectCreate(BaseModel):
    title: str
    target_name: str = ""
    target_type: str = "company"
    industry: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_industry_intake(self):
        if self.target_type in {"industry", "sector", "行业", "赛道"}:
            ResearchRunRequest.model_validate(self.metadata)
        return self


class ResearchProjectResponse(BaseModel):
    id: int
    title: str
    target_name: str
    target_type: str
    industry: str
    description: str
    status: str
    is_running: bool = False
    state_label: str = ""
    created_at: str
    updated_at: str


class ResearchProjectListResponse(BaseModel):
    projects: list[ResearchProjectResponse]
    summary: dict[str, int] = Field(default_factory=dict)


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
    person_aliases: list[str] = Field(default_factory=list)
    person_context: str = Field(default="", max_length=12000)
    identity_anchors: str = Field(default="", max_length=6000)
    uploaded_identity_clues: list[dict[str, Any]] = Field(default_factory=list)
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
    industry_segments: list[str] = Field(default_factory=list)
    excluded_segments: list[str] = Field(default_factory=list)
    research_purpose: str = ""
    include_capital_markets: Optional[StrictBool] = None
    as_of_date: str = ""
    required_chapters: list[int] = Field(default_factory=list)
    scoring_required: Optional[StrictBool] = None
    industry_scope: dict[str, Any] = Field(default_factory=dict)
    min_sources_per_module: int = 5
    max_search_rounds: int = 3

    @field_validator('required_chapters')
    @classmethod
    def valid_company_required_chapters(cls,value):
        if any(n<2 or n>12 for n in value):
            raise ValueError('必答实质章节只能为第2至12章')
        return list(dict.fromkeys(value))

    @field_validator("as_of_date")
    @classmethod
    def valid_cutoff(cls, value: str) -> str:
        if value:
            parsed = date.fromisoformat(value)
            if value != parsed.isoformat():
                raise ValueError("数据截止日必须为 YYYY-MM-DD")
        return value

    @field_validator("industry_scope")
    @classmethod
    def valid_saved_scope(cls, value: dict) -> dict:
        cutoff = value.get("as_of_date")
        if cutoff and (not isinstance(cutoff, str) or date.fromisoformat(cutoff).isoformat() != cutoff):
            raise ValueError("保存范围中的数据截止日必须为 YYYY-MM-DD")
        return value


class ResearchRunResponse(BaseModel):
    project: ResearchProjectResponse
    artifacts: list[ResearchArtifactResponse]
    sources_added: int


class ResearchRevisionRequest(BaseModel):
    artifact_type: str
    instructions: str
    base_artifact_id: Optional[int] = None

class ResearchAssistantImport(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=80)
    summary: str = Field(default='', max_length=8000)


class ResearchAssistantRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, pattern=r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    request_id: Optional[str] = Field(default=None, pattern=r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    current_page: str = Field(default="submit", max_length=40)
    message: str = Field(default='', max_length=6000)
    images: list[str] = Field(default_factory=list, max_length=2)
    project_id: Optional[int] = None
    limit: int = 8
    history_summary: str = ""
    recent_messages: list[dict[str, str]] = Field(default_factory=list)

    @field_validator('images')
    @classmethod
    def valid_assistant_images(cls, values):
        from assistant_images import normalize_image
        return [normalize_image(value) for value in values]

    @model_validator(mode='after')
    def assistant_content_required(self):
        if not self.message and not self.images:
            raise ValueError('请输入问题或选择截图')
        return self

class ResearchUploadResponse(BaseModel):
    source: ResearchSourceResponse
    message: str

