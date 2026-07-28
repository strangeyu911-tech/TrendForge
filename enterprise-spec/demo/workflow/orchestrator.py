"""Workflow 编排器：串联 5 个 Agent，处理回退与异常"""
from __future__ import annotations
import asyncio
import time
import uuid
from datetime import datetime, timedelta
from agents import (
    BaseAgent, TaskContext, AgentError,
    PlannerAgent, ResearchAgent, WriterAgent, ReviewerAgent, PublisherAgent,
)
from rag import NewsKnowledgeBase
from prompts import PromptManager
from config import CONFIG


class WorkflowOrchestrator:
    """端到端内容生产流水线"""

    def __init__(self, kb: NewsKnowledgeBase | None = None, pm: PromptManager | None = None):
        self.kb = kb or NewsKnowledgeBase()
        self.pm = pm or PromptManager()
        self.planner = PlannerAgent()
        self.researcher = ResearchAgent(self.kb)
        self.writer = WriterAgent(self.pm)
        self.reviewer = ReviewerAgent()
        self.publisher = PublisherAgent()
        self.bad_cases: list[dict] = []

    async def run_topic(self, topic: dict, signals: list | None = None) -> dict:
        """单话题端到端流程"""
        ctx = TaskContext(
            task_id=f"task_{uuid.uuid4().hex[:8]}",
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
            topic=topic.get("title", ""),
            language=topic.get("target_languages", ["zh"])[0],
            priority=topic.get("priority", "P1"),
            sla_deadline=(datetime.now() + timedelta(seconds=CONFIG.sla_seconds)).isoformat(),
            prompt_versions={
                "planner": self.pm.get_latest("planner", "default"),
                "research": "v1.0.0",
                "writer": self.pm.get_latest("writer", "deep_dive"),
                "reviewer": self.pm.get_latest("reviewer", "default"),
            },
        )
        ctx.status = "running"

        result = {"ctx": ctx, "topic": topic, "steps": []}

        # Step 1: Research（Planner 已在外部完成选题）
        research_out = await self._run_with_fallback(
            ctx, self.researcher, {"topic": topic}
        )
        result["steps"].append({"agent": "research", "output": research_out})
        evidences = research_out.get("evidences", [])

        # Step 2-3: Writer → Reviewer 循环（最多 max_review_rounds 次）
        article = None
        review_out = None
        for round_idx in range(CONFIG.max_review_rounds + 1):
            ctx.review_rounds = round_idx + 1
            writer_out = await self._run_with_fallback(
                ctx, self.writer, {
                    "topic": topic, "evidences": evidences,
                    "template": "deep_dive", "language": ctx.language,
                }
            )
            result["steps"].append({"agent": "writer", "round": round_idx + 1, "output": writer_out})
            article = writer_out.get("article")

            review_out = await self._run_with_fallback(
                ctx, self.reviewer, {
                    "topic": topic, "evidences": evidences, "article": article,
                }
            )
            result["steps"].append({"agent": "reviewer", "round": round_idx + 1, "output": review_out})

            verdict = review_out.get("verdict", "reject")
            if verdict == "pass":
                break
            elif verdict == "reject":
                # 标记 Bad Case
                self._record_bad_case(ctx, topic, article, review_out)
                ctx.status = "aborted"
                result["final"] = {"status": "rejected", "reason": review_out.get("revision_suggestions")}
                return result
            # verdict == revise：继续循环

        if review_out and review_out.get("verdict") != "pass":
            # 超过轮次仍未通过 → 转人工
            self._record_bad_case(ctx, topic, article, review_out)
            ctx.status = "human_pending"
            result["final"] = {"status": "human_pending", "reason": "max_review_rounds_exceeded"}
            return result

        # Step 4: Publisher
        publish_out = await self._run_with_fallback(
            ctx, self.publisher, {
                "article": article, "review_verdict": "pass",
                "publish_config": {
                    "channels": ["site_feed", "weibo", "rss"],
                    "gray_release": {"enabled": True, "initial_ratio": CONFIG.gray_initial_ratio},
                },
            }
        )
        result["steps"].append({"agent": "publisher", "output": publish_out})

        ctx.status = "succeeded"
        result["final"] = {
            "status": "published",
            "content_id": publish_out.get("content_id"),
            "publish_records": publish_out.get("publish_records", []),
            "gray_status": publish_out.get("gray_status"),
        }
        return result

    async def run_pipeline(self, signals: list = None, strategy: dict = None) -> dict:
        """完整流水线：热点发现 → 选题 → 生产 → 发布"""
        signals = signals or []
        strategy = strategy or {"categories": ["tech", "finance"], "languages": ["zh"], "max_topics": 5}

        # Planner 选题
        ctx = TaskContext(
            task_id=f"task_{uuid.uuid4().hex[:8]}",
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
            prompt_versions={"planner": self.pm.get_latest("planner", "default")},
        )
        planner_out = await self._run_with_fallback(ctx, self.planner, {"signals": signals, "strategy": strategy})
        topics = planner_out.get("topics", [])

        # 并行处理多个话题（Demo 限制并发 3）
        semaphore = asyncio.Semaphore(3)

        async def run_one(topic):
            async with semaphore:
                return await self.run_topic(topic, signals)

        results = await asyncio.gather(*[run_one(t) for t in topics], return_exceptions=True)

        return {
            "planner": planner_out,
            "topics_count": len(topics),
            "results": [r if not isinstance(r, Exception) else {"error": str(r)} for r in results],
            "bad_cases": self.bad_cases,
        }

    async def _run_with_fallback(self, ctx: TaskContext, agent: BaseAgent, inputs: dict) -> dict:
        try:
            return await agent.run(ctx, inputs)
        except AgentError as e:
            return await agent.fallback(ctx, e)
        except Exception as e:
            return await agent.fallback(ctx, AgentError(agent.name, str(e)))

    def _record_bad_case(self, ctx: TaskContext, topic: dict, article: dict, review: dict) -> None:
        bc = {
            "bad_case_id": f"bc_{uuid.uuid4().hex[:8]}",
            "trace_id": ctx.trace_id,
            "topic": topic.get("title", ""),
            "verdict": review.get("verdict"),
            "quality_scores": review.get("quality_scores"),
            "fact_check": review.get("fact_check"),
            "compliance": review.get("compliance"),
            "suggestions": review.get("revision_suggestions"),
            "prompt_version": ctx.prompt_versions.get("writer"),
            "created_at": datetime.now().isoformat(),
        }
        self.bad_cases.append(bc)
