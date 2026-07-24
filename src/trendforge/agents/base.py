"""Agent 基类 — 运行时上下文、重试、Span 记录、决策日志、异常回退

平台化升级：
- RunContext 携带全球化字段（country/target_audience/platform/content_style）
- decision_log：每个 Agent 产出 _decision（"为什么"），由 _exec 自动归集到 ctx.decision_log
- 最终写入 task.decision_log / content.decision_log，实现 Workflow 可解释性
"""
from __future__ import annotations
import time
import asyncio
import functools
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from models import Task, TaskSpan
from prompts import PromptManager
from llm import BaseProvider as LLMProvider, get_llm
from config import settings


@dataclass
class Span:
    agent: str
    status: str  # ok|degraded|failed
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cny: float = 0.0
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    decision_reason: str = ""  # 该 Agent 的决策理由（可解释性）
    started_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RunContext:
    """运行时上下文：随 8 步 Workflow 流转，含 DB 会话、Task、全球化策略、决策日志"""
    task_id: str
    trace_id: str
    session: AsyncSession
    pm: PromptManager
    llm: LLMProvider
    task: Task
    topic: dict = field(default_factory=dict)
    language: str = "zh"
    vendor: str = ""
    # 全球化字段（平台化升级）
    country: str = "US"
    target_audience: str = ""
    platform: str = ""
    content_style: str = "deep_dive"
    review_rounds: int = 0
    spans: list[Span] = field(default_factory=list)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    # 决策日志：agent_name -> {"reason": str, "details": dict}（可解释性核心）
    decision_log: dict[str, dict] = field(default_factory=dict)

    @property
    def total_duration_ms(self) -> int:
        return sum(s.duration_ms for s in self.spans)

    @property
    def total_cost_cny(self) -> float:
        return round(sum(s.cost_cny for s in self.spans), 4)

    def log_decision(self, agent: str, reason: str, **details):
        """记录某 Agent 的决策理由（供 trace/可解释性查看）"""
        self.decision_log[agent] = {"reason": reason, "details": details}

    async def persist_spans(self):
        """将 span 写入 DB，并把决策日志回写 task

        注意：直接 session.add(TaskSpan(task_id=...))，不走 task.spans 关系，
        避免 async session 下 lazy load 触发 MissingGreenlet。
        """
        for s in self.spans:
            self.session.add(TaskSpan(
                task_id=self.task_id, agent=s.agent, status=s.status, model=s.model,
                tokens_in=s.tokens_in, tokens_out=s.tokens_out,
                cost_cny=s.cost_cny, duration_ms=s.duration_ms,
                warnings=s.warnings, started_at=s.started_at,
            ))
        self.task.total_duration_ms = self.total_duration_ms
        self.task.total_cost_cny = self.total_cost_cny
        self.task.review_rounds = self.review_rounds
        self.task.prompt_versions = self.prompt_versions
        self.task.decision_log = self.decision_log


class AgentError(Exception):
    def __init__(self, agent: str, message: str, recoverable: bool = True):
        self.agent = agent
        self.recoverable = recoverable
        super().__init__(f"[{agent}] {message}")


def retry(max_attempts: int = 3, base_delay: float = 5.0):
    """指数退避重试装饰器"""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **kw):
            last_err = None
            for attempt in range(max_attempts):
                try:
                    return await fn(*a, **kw)
                except AgentError as e:
                    if not e.recoverable:
                        raise
                    last_err = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
                except Exception as e:
                    last_err = AgentError(fn.__qualname__, str(e))
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
            raise last_err
        return wrapper
    return deco


class BaseAgent(ABC):
    name: str = "base"

    @abstractmethod
    async def run(self, ctx: RunContext, inputs: dict) -> dict: ...

    @abstractmethod
    async def fallback(self, ctx: RunContext, error: AgentError) -> dict: ...

    async def _exec(self, ctx: RunContext, inputs: dict) -> dict:
        """执行 run，自动记录 Span + 决策日志 + 异常回退"""
        t0 = time.time()
        span = Span(agent=self.name, status="ok", started_at=datetime.fromtimestamp(t0))
        try:
            result = await self.run(ctx, inputs)
            llm_resp = result.pop("_llm_resp", None) if isinstance(result, dict) else None
            if llm_resp:
                span.model = llm_resp.model
                span.tokens_in = llm_resp.tokens_in
                span.tokens_out = llm_resp.tokens_out
                span.cost_cny = llm_resp.cost_cny
            # 提取决策理由（可解释性）— 保留在 result 中，同时归集到 ctx.decision_log
            if isinstance(result, dict) and result.get("_decision"):
                dec = result["_decision"]
                ctx.log_decision(self.name, dec.get("reason", ""), **dec.get("details", {}))
                span.decision_reason = dec.get("reason", "")
            if result.get("_warnings"):
                span.warnings = result.pop("_warnings")
                span.status = "degraded"
        except AgentError as e:
            span.status = "failed"
            ctx.spans.append(span)
            span.duration_ms = int((time.time() - t0) * 1000)
            ctx.log_decision(self.name, f"fallback:{e}", recoverable=e.recoverable)
            return await self.fallback(ctx, e)
        span.duration_ms = int((time.time() - t0) * 1000)
        ctx.spans.append(span)
        return result


def make_run_context(
    task_id: str, trace_id: str, session: AsyncSession, task: Task, topic: dict,
    language: str = "zh", vendor: str | None = None,
    country: str = "US", target_audience: str = "", platform: str = "", content_style: str = "deep_dive",
) -> RunContext:
    """构造运行时上下文，注入全球化策略"""
    vendor = vendor or settings.llm_vendor
    return RunContext(
        task_id=task_id, trace_id=trace_id, session=session,
        pm=PromptManager(), llm=get_llm(vendor), task=task,
        topic=topic, language=language, vendor=vendor,
        country=country, target_audience=target_audience,
        platform=platform, content_style=content_style,
    )
