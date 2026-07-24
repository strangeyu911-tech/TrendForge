"""TaskContext & Agent 基类"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from abc import ABC, abstractmethod


@dataclass
class Span:
    agent: str
    start: str
    end: str
    duration_ms: int
    status: str  # ok | degraded | failed
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cny: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class TaskContext:
    task_id: str
    trace_id: str
    topic: str = ""
    language: str = "zh"
    priority: str = "P1"
    sla_deadline: str = ""
    prompt_versions: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    review_rounds: int = 0
    status: str = "pending"  # pending|running|degraded|failed|succeeded|human_pending|aborted

    def add_span(self, span: Span) -> None:
        self.spans.append(span)
        self.history.append({"agent": span.agent, "ts": span.end, "status": span.status})

    @property
    def total_duration_ms(self) -> int:
        return sum(s.duration_ms for s in self.spans)

    @property
    def total_cost_cny(self) -> float:
        return round(sum(s.cost_cny for s in self.spans), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "topic": self.topic,
            "language": self.language,
            "status": self.status,
            "review_rounds": self.review_rounds,
            "total_duration_ms": self.total_duration_ms,
            "total_cost_cny": self.total_cost_cny,
            "spans": [s.__dict__ for s in self.spans],
            "history": self.history,
        }


class AgentError(Exception):
    def __init__(self, agent: str, message: str, recoverable: bool = True):
        self.agent = agent
        self.recoverable = recoverable
        super().__init__(f"[{agent}] {message}")


class BaseAgent(ABC):
    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    async def run(self, ctx: TaskContext, inputs: dict) -> dict:
        ...

    @abstractmethod
    async def fallback(self, ctx: TaskContext, error: AgentError) -> dict:
        ...

    def _record_span(self, ctx: TaskContext, status: str, t0: float, llm_resp=None, warnings=None) -> None:
        from datetime import datetime
        duration_ms = int((datetime.now().timestamp() - t0) * 1000)
        span = Span(
            agent=self.name,
            start=datetime.fromtimestamp(t0).isoformat(),
            end=datetime.now().isoformat(),
            duration_ms=duration_ms,
            status=status,
            model=llm_resp.model if llm_resp else "",
            tokens_in=llm_resp.tokens_in if llm_resp else 0,
            tokens_out=llm_resp.tokens_out if llm_resp else 0,
            cost_cny=llm_resp.cost_cny if llm_resp else 0.0,
            warnings=warnings or [],
        )
        ctx.add_span(span)
