"""Pydantic schemas — API 入参出参与 Agent 间数据契约"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


# ============ Agent I/O 契约 ============
class Topic(BaseModel):
    topic_id: str
    title: str
    summary: str = ""
    category: str = "tech"
    heat_score: float = 0.0
    suggested_angles: list[str] = Field(default_factory=list)
    target_languages: list[str] = Field(default_factory=lambda: ["zh"])
    priority: str = "P1"
    evidence_hint: list[str] = Field(default_factory=list)


class SignalItem(BaseModel):
    title: str
    heat: float = 0.0
    url: str = ""


class Signal(BaseModel):
    source: str
    items: list[SignalItem] = Field(default_factory=list)


class Evidence(BaseModel):
    evidence_id: str
    content: str
    source_url: str = ""
    source_name: str = ""
    published_at: str = ""
    credibility: float = 0.5
    language: str = "zh"
    retrieval_score: float = 0.0
    is_conflict: bool = False
    entities: list[str] = Field(default_factory=list)


class ArticleBlock(BaseModel):
    type: str  # paragraph|heading
    text: str
    citations: list[str] = Field(default_factory=list)


class Article(BaseModel):
    title: str
    summary: str = ""
    body: list[ArticleBlock] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    cover_suggestion: str = ""
    word_count: int = 0
    language: str = "zh"


class QualityScores(BaseModel):
    readability: float = 0.0
    objectivity: float = 0.0
    completeness: float = 0.0
    timeliness: float = 0.0
    overall: float = 0.0


class FactCheckDetail(BaseModel):
    section: str = ""
    evidence_id: str = ""
    status: str = ""  # consistent|inconsistent|no_citation|invalid_citation
    reason: str = ""


class FactCheck(BaseModel):
    checked_claims: int = 0
    consistent: int = 0
    inconsistent: int = 0
    details: list[FactCheckDetail] = Field(default_factory=list)


class Compliance(BaseModel):
    sensitive_hits: list[str] = Field(default_factory=list)
    copyright_risk: str = "low"
    politics_risk: str = "none"


class RevisionSuggestion(BaseModel):
    section: str = ""
    issue: str = ""
    fix: str = ""


class ReviewResult(BaseModel):
    verdict: str  # pass|revise|reject
    quality_scores: QualityScores
    fact_check: FactCheck
    compliance: Compliance
    revision_suggestions: list[RevisionSuggestion] = Field(default_factory=list)
    bad_case_flag: bool = False


# ============ API schemas ============
class RunTopicRequest(BaseModel):
    title: str
    summary: str = ""
    category: str = "tech"
    language: str = "zh"
    country: str = "CN"
    priority: str = "P1"
    angles: list[str] = Field(default_factory=list)


class RunPipelineRequest(BaseModel):
    signals: list[Signal] = Field(default_factory=list)
    max_topics: int = 5
    categories: list[str] = Field(default_factory=lambda: ["tech", "finance"])
    variants_per_topic: int = 1  # P2: 每个话题生成的多视角变体数（≥2 时按国家内容形态裂变）
    country: str = "CN"
    force: bool = False  # 为 True 时跳过结果缓存、强制重新生成（用于现场演示真实生成）


class TaskResponse(BaseModel):
    task_id: str
    trace_id: str
    status: str
    topic_title: str
    total_duration_ms: int
    total_cost_cny: float
    review_rounds: int
    content_id: str | None = None
    article: Article | None = None
    error: str = ""


class PromptCreateRequest(BaseModel):
    prompt_id: str
    agent: str
    scene: str
    language: str = "zh"
    template: str
    variables: list[str] = Field(default_factory=list)
    changelog: str = ""
    parent_version: str = ""
    author: str = "api"


class ExperimentCreateRequest(BaseModel):
    experiment_id: str
    agent: str
    scene: str
    control_version: str
    treatment_version: str
    traffic_split: dict = Field(default_factory=lambda: {"control": 0.5, "treatment": 0.5})
    target_metrics: list[str] = Field(default_factory=lambda: ["ctr"])
    min_sample_size: int = 1000


class NewsIngestRequest(BaseModel):
    source_name: str
    title: str
    content: str
    url: str
    published_at: datetime | str
    language: str = "zh"
    category: str = "tech"
    credibility_tier: int = 2
    entities: list[str] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    impressions: int = 0
    clicks: int = 0
    reads: int = 0
    finishes: int = 0
    ctr: float = 0.0
    read_rate: float = 0.0
    finish_rate: float = 0.0


class ABTestReport(BaseModel):
    control: dict
    treatment: dict
    lift_pct: float
    z_score: float
    p_value: float
    significant: bool
    conclusion: str
