"""SQLAlchemy 数据模型 — 覆盖设计文档全部表结构"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, ForeignKey, JSON, BigInteger, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db import Base


# ============ RAG 知识库 ============
class NewsDocument(Base):
    """新闻文档 — 完整 metadata + hash 去重"""
    __tablename__ = "news_documents"
    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_name: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="tech_media")
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(Text, default="")              # 摘要（首段/前 200 字）
    content: Mapped[str] = mapped_column(Text, default="")              # 清洗后正文（向后兼容）
    full_text: Mapped[str] = mapped_column(Text, default="")            # 完整正文（采集原文）
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    author: Mapped[str] = mapped_column(String(128), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    country: Mapped[str] = mapped_column(String(8), default="US", index=True)       # US/GB/CN...
    language: Mapped[str] = mapped_column(String(8), default="en", index=True)      # en/zh
    category: Mapped[str] = mapped_column(String(32), default="tech", index=True)   # tech/finance/world
    credibility_tier: Mapped[int] = mapped_column(Integer, default=2)                # 旧字段（兼容）
    credibility_level: Mapped[int] = mapped_column(Integer, default=2, index=True)  # 1=权威官方 2=权威媒体 3=一般
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)          # sha256(url) 去重
    entities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="indexed")  # raw|processed|indexed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    chunks: Mapped[list["NewsChunk"]] = relationship(back_populates="document", cascade="all,delete-orphan")


class NewsChunk(Base):
    """新闻分块 — 带完整 metadata，支持 DB 层过滤"""
    __tablename__ = "news_chunks"
    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("news_documents.doc_id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # chunk 级 metadata（与 Chroma metadata 对齐）
    title: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    country: Mapped[str] = mapped_column(String(8), default="", index=True)
    language: Mapped[str] = mapped_column(String(8), default="", index=True)
    source_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    publish_time: Mapped[datetime] = mapped_column(DateTime, nullable=True, index=True)
    credibility: Mapped[int] = mapped_column(Integer, default=2)         # 1/2/3
    section_path: Mapped[str] = mapped_column(String(256), default="")   # 所属结构路径，如 "h2>多模态推理"
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    document: Mapped[NewsDocument] = relationship(back_populates="chunks")


# ============ Prompt 管理 ============
class Prompt(Base):
    __tablename__ = "prompts"
    prompt_id: Mapped[str] = mapped_column(String(64), primary_key=True)   # 如 writer_deep_dive
    version: Mapped[str] = mapped_column(String(32), primary_key=True)     # 如 v2.0.1
    agent: Mapped[str] = mapped_column(String(32), index=True)
    scene: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(8), default="zh")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|staging|production|archived
    template: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSON, default=list)
    changelog: Mapped[str] = mapped_column(Text, default="")
    parent_version: Mapped[str] = mapped_column(String(32), default="")
    author: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    eval_score: Mapped[float] = mapped_column(Float, default=0.0)
    tags: Mapped[list] = mapped_column(JSON, default=list)


class PromptExperiment(Base):
    __tablename__ = "prompt_experiments"
    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent: Mapped[str] = mapped_column(String(32), index=True)
    scene: Mapped[str] = mapped_column(String(32))
    control_version: Mapped[str] = mapped_column(String(32))
    treatment_version: Mapped[str] = mapped_column(String(32))
    traffic_split: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|concluded|aborted
    start_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    target_metrics: Mapped[list] = mapped_column(JSON, default=list)
    min_sample_size: Mapped[int] = mapped_column(Integer, default=1000)
    assignments: Mapped[list["ExperimentAssignment"]] = relationship(back_populates="experiment", cascade="all,delete-orphan")


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"
    content_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("prompt_experiments.experiment_id"), primary_key=True)
    variant: Mapped[str] = mapped_column(String(16))  # control|treatment
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    experiment: Mapped[PromptExperiment] = relationship(back_populates="assignments")


# ============ 任务与 Trace ============
class Task(Base):
    __tablename__ = "tasks"
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    topic_id: Mapped[str] = mapped_column(String(64), default="")
    topic_title: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[str] = mapped_column(String(32), default="tech")
    language: Mapped[str] = mapped_column(String(8), default="zh")
    priority: Mapped[str] = mapped_column(String(4), default="P1")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|running|degraded|succeeded|failed|human_pending|aborted
    prompt_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    review_rounds: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_log: Mapped[dict] = mapped_column(JSON, default=dict)   # 全流程决策日志（可解释性：每个Agent的"为什么"）
    error: Mapped[str] = mapped_column(Text, default="")
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    spans: Mapped[list["TaskSpan"]] = relationship(back_populates="task", cascade="all,delete-orphan")


class TaskSpan(Base):
    __tablename__ = "task_spans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    agent: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    task: Mapped[Task] = relationship(back_populates="spans")


# ============ 内容与行为（DWD） ============
class Content(Base):
    """dwd_content_fact — 一行 = 一篇生产的内容"""
    __tablename__ = "contents"
    content_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    topic_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(8), default="zh")
    template_type: Mapped[str] = mapped_column(String(32), default="deep_dive")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # 全球化字段（平台化升级）
    country: Mapped[str] = mapped_column(String(8), default="US", index=True)        # 目标国家 US/GB/JP/KR/IN/BR/CN
    target_audience: Mapped[str] = mapped_column(String(64), default="")              # 目标受众
    platform: Mapped[str] = mapped_column(String(32), default="", index=True)         # 主分发平台
    content_style: Mapped[str] = mapped_column(String(32), default="deep_dive")       # breaking_news/summary/deep_dive...
    outline: Mapped[list] = mapped_column(JSON, default=list)                          # OutlinePlanner 产出的大纲
    distribution_plan: Mapped[dict] = mapped_column(JSON, default=dict)                # Publisher 分发计划
    decision_log: Mapped[dict] = mapped_column(JSON, default=dict)                     # 全流程决策日志（可解释性）
    prompt_writer_v: Mapped[str] = mapped_column(String(32), default="", index=True)
    prompt_planner_v: Mapped[str] = mapped_column(String(32), default="")
    prompt_research_v: Mapped[str] = mapped_column(String(32), default="")
    prompt_reviewer_v: Mapped[str] = mapped_column(String(32), default="")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_overall: Mapped[float] = mapped_column(Float, default=0.0)
    fact_consistency: Mapped[float] = mapped_column(Float, default=0.0)
    review_verdict: Mapped[str] = mapped_column(String(16), default="")
    review_rounds: Mapped[int] = mapped_column(Integer, default=0)
    is_bad_case: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    bad_case_reason: Mapped[str] = mapped_column(String(128), default="")
    channels: Mapped[list] = mapped_column(JSON, default=list)
    gray_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContentEvent(Base):
    """dwd_content_event — 一行 = 一次用户行为"""
    __tablename__ = "content_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    event_type: Mapped[str] = mapped_column(String(16), index=True)  # exposed|clicked|read|finished|interacted
    channel: Mapped[str] = mapped_column(String(32), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    read_duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    action_type: Mapped[str] = mapped_column(String(16), default="")  # like|comment|share
    # 全球化与反馈指标（平台化升级）
    country: Mapped[str] = mapped_column(String(8), default="", index=True)       # 用户所在国家
    language: Mapped[str] = mapped_column(String(8), default="", index=True)      # 内容语言
    platform: Mapped[str] = mapped_column(String(32), default="", index=True)     # 触达平台
    finish_rate: Mapped[float] = mapped_column(Float, default=0.0)                # 阅读完成率 0~1
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_feedback: Mapped[int] = mapped_column(Integer, default=0)            # 负反馈数
    event_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ============ Bad Case ============
class BadCase(Base):
    __tablename__ = "bad_cases"
    bad_case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    category_l1: Mapped[str] = mapped_column(String(4), index=True)  # F|H|C|G|Q|U|D
    category_l2: Mapped[str] = mapped_column(String(8), default="")
    severity: Mapped[str] = mapped_column(String(16), default="major")  # critical|major|minor
    source: Mapped[str] = mapped_column(String(32), default="reviewer")
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    root_cause: Mapped[str] = mapped_column(Text, default="")
    affected_prompt_versions: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|in_fix|resolved|wontfix
    assigned_to: Mapped[str] = mapped_column(String(64), default="")
    fix_action: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


# 索引
Index("idx_events_content_type", ContentEvent.content_id, ContentEvent.event_type)
Index("idx_contents_cat_pub", Content.category, Content.published_at)
