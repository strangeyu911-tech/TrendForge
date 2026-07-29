"""Workflow 编排器 — 8 步链路 + 状态机 + 决策日志 + 实验接入

8 步 Agent 链（数据在 RunContext 中真实传递，不独立调 LLM）：
  1. TrendDetector   → trends（热点趋势）
  2. TopicSelector   → topics（结合国家策略选题）
  3. Retriever       → evidences（RAG 检索）
  4. OutlinePlanner  → outline（文章大纲）
  5. Writer          → article（按大纲+风格成文）
  6. FactChecker     → fact_check（论断核查）
  7. Reviewer        → review（质量+合规裁决，含回退循环）
  8. Publisher       → publish（分发策略+灰度+埋点）

可解释性：每个 Agent 产出 _decision（"为什么"），归集到 ctx.decision_log，
最终写入 task.decision_log 与 content.decision_log，可通过 trace 查看。
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Task, BadCase, PromptExperiment, ExperimentAssignment, Content
from db import async_session
from agents import (
    RunContext, make_run_context,
    TrendDetectorAgent, TopicSelectorAgent, ResearchAgent, OutlinePlannerAgent,
    WriterAgent, FactCheckerAgent, ReviewerAgent, PublisherAgent,
)
from config import settings, COUNTRY_STRATEGIES

# 内容形态 → 中文标签（P2 多视角变体标题后缀）
_STYLE_LABEL: dict[str, str] = {
    "breaking_news": "快讯", "deep_dive": "深度解读", "analysis": "行业分析",
    "brief": "简报", "summary": "要点梳理", "trending": "热点追踪",
    "startup": "创业视角", "tech_explainer": "技术科普", "industry_analysis": "产业洞察",
    "commentary": "评论", "news_card": "资讯卡",
}


class WorkflowOrchestrator:
    """端到端编排：8 步 Agent 链 + 回退 + 决策日志 + 实验分桶"""

    def __init__(self):
        self.trend_detector = TrendDetectorAgent()
        self.topic_selector = TopicSelectorAgent()
        self.retriever = ResearchAgent()
        self.outliner = OutlinePlannerAgent()
        self.writer = WriterAgent()
        self.fact_checker = FactCheckerAgent()
        self.reviewer = ReviewerAgent()
        self.publisher = PublisherAgent()

    async def run_topic(
        self, session: AsyncSession, topic: dict, signals: list | None = None,
    ) -> dict:
        """单话题端到端生产（8 步中的 3-8 步；1-2 步在 run_pipeline）。topic 含国家策略字段"""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        country = topic.get("country", "CN")
        language = topic.get("language", "zh")
        target_audience = topic.get("target_audience", "")
        content_style = topic.get("content_style", "deep_dive")
        platform = topic.get("platform", "")

        task = Task(
            task_id=task_id, trace_id=trace_id,
            topic_id=topic.get("topic_id", ""), topic_title=topic.get("title", ""),
            category=topic.get("category", "tech"), language=language,
            priority=topic.get("priority", "P1"), status="running",
        )
        session.add(task)
        await session.flush()

        ctx = make_run_context(
            task_id, trace_id, session, task, topic, language,
            country=country, target_audience=target_audience,
            platform=platform, content_style=content_style,
        )
        ctx.topic["_signals"] = signals or []

        result = {"task_id": task_id, "trace_id": trace_id, "topic": topic, "steps": []}
        try:
            # 3. Retriever（RAG 检索）
            research_out = await self.retriever._exec(ctx, {"topic": topic})
            evidences = research_out.get("evidences", [])
            result["steps"].append(self._step("retriever", research_out))
            if not evidences:
                task.status = "degraded"
                result["status"] = "degraded"
                result["error"] = "无可用证据"
                await ctx.persist_spans()
                await session.flush()
                return result

            # 4. OutlinePlanner
            outline_out = await self.outliner._exec(ctx, {
                "topic": topic, "evidences": evidences, "content_style": content_style})
            outline = outline_out.get("outline", [])
            result["steps"].append(self._step("outline_planner", outline_out))

            # 5-7. Writer → FactChecker → Reviewer 循环（含回退）
            article, review = None, None
            for round_idx in range(settings.max_review_rounds + 1):
                ctx.review_rounds = round_idx
                # 5. Writer
                writer_out = await self.writer._exec(ctx, {
                    "topic": topic, "evidences": evidences, "outline": outline,
                    "content_style": content_style, "template": content_style})
                article = writer_out.get("article", {})
                result["steps"].append(self._step("writer", writer_out, round_idx))

                # 6. FactChecker
                fact_out = await self.fact_checker._exec(ctx, {"article": article, "evidences": evidences})
                fact_check = fact_out.get("fact_check", {})
                result["steps"].append(self._step("fact_checker", fact_out, round_idx))

                # 7. Reviewer（注入 FactChecker 结果）
                review_out = await self.reviewer._exec(ctx, {
                    "topic": topic, "evidences": evidences, "article": article,
                    "fact_check": fact_check})
                review = review_out
                # 用 FactChecker 的结果覆盖 review.fact_check（独立核查更可信）
                review["fact_check"] = {
                    "checked_claims": fact_check.get("checked_claims", 0),
                    "consistent": fact_check.get("consistent", 0),
                    "inconsistent": fact_check.get("checked_claims", 0) - fact_check.get("consistent", 0),
                }
                result["steps"].append(self._step("reviewer", review_out, round_idx))

                if review["verdict"] == "pass":
                    break
                if review["verdict"] == "reject":
                    await self._record_bad_case(session, ctx, article, review, evidences)
                    task.status = "aborted"
                    result["status"] = "rejected"
                    result["error"] = f"审核拒绝：{review.get('revision_suggestions')}"
                    await ctx.persist_spans()
                    await session.flush()
                    return result
            else:
                task.status = "human_pending"
                result["status"] = "human_pending"
                result["error"] = "审核回退次数耗尽，转人工"
                await ctx.persist_spans()
                await session.flush()
                return result

            # 8. Publisher（分发策略 + 灰度 + 埋点）
            pub_out = await self.publisher._exec(ctx, {
                "article": article, "review_verdict": "pass", "review": review,
                "evidences": evidences, "topic": topic, "outline": outline,
                "citations": result["steps"][-3]["output"].get("citations", []),
                "prompt_version": ctx.prompt_versions.get("writer", ""),
            })
            result["steps"].append(self._step("publisher", pub_out))
            result["final"] = pub_out
            result["status"] = "succeeded"
            task.status = "succeeded"
            content_id = pub_out.get("content_id", "")
            task.result = {"content_id": content_id, "status": "succeeded"}

            # 实验分桶接入（打通 experiment_assignments 表）
            await self._assign_experiment(session, content_id, ctx)

        except Exception as e:
            task.status = "failed"
            result["status"] = "failed"
            result["error"] = str(e)

        await ctx.persist_spans()
        await session.flush()
        return result

    async def run_pipeline(
        self, session: AsyncSession, signals: list, strategy: dict,
    ) -> dict:
        """完整流水线：1.TrendDetector → 2.TopicSelector → 逐话题 3-8 步生产"""
        country = strategy.get("country", "CN")
        variants_per_topic = max(1, int(strategy.get("variants_per_topic", 1)))
        # P0: 查询已发布标题，供选题器去重（避免重复生产）
        published_titles = await self._published_titles(session)
        # 1. TrendDetector
        td_ctx = make_run_context(
            f"task_td_{uuid.uuid4().hex[:8]}", f"trace_{uuid.uuid4().hex[:12]}",
            session, Task(task_id="td_dummy", trace_id="t", status="running"), {},
            country=country, content_style=strategy.get("content_style", "deep_dive"),
        )
        td_out = await self.trend_detector._exec(td_ctx, {
            "signals": signals, "country": country, "category": strategy.get("category")})
        trends = td_out.get("trends", [])
        # 2. TopicSelector（传入已发布标题做去重）
        ts_out = await self.topic_selector._exec(td_ctx, {
            "trends": trends, "country": country, "max_topics": strategy.get("max_topics", 5),
            "published_titles": published_titles})
        topics = ts_out.get("topics", [])
        dedup_stats = ts_out.get("_dedup")
        # 3-8. 逐话题生产（含 P2 多视角变体；串行保证 session 安全）
        results = []
        for topic in topics[: strategy.get("max_topics", 5)]:
            for vt in self._build_variants(topic, country, variants_per_topic):
                r = await self.run_topic(session, vt, signals)
                results.append(r)
        return {"country": country, "trends_count": len(trends), "topics_count": len(topics),
                "variants_per_topic": variants_per_topic, "dedup": dedup_stats,
                "results": results, "decision_log": td_ctx.decision_log}

    @staticmethod
    async def _published_titles(session: AsyncSession) -> list[str]:
        """查已成功发布的内容标题（P0 选题去重用）"""
        try:
            stmt = select(Content.title).where(Content.status == "succeeded")
            rows = (await session.execute(stmt)).scalars().all()
            return [t for t in rows if t]
        except Exception:
            return []

    @staticmethod
    def _build_variants(topic: dict, country: str, n: int) -> list[dict]:
        """P2: 同一话题按国家内容形态生成多视角变体（不同风格/角度，标题加风格后缀避免重复）"""
        if n <= 1:
            return [topic]
        styles = COUNTRY_STRATEGIES.get(country, {}).get(
            "content_styles", [topic.get("content_style", "deep_dive")])
        angles = topic.get("suggested_angles") or []
        jobs: list[dict] = []
        for i in range(n):
            vt = dict(topic)
            style = styles[i % len(styles)]
            vt["content_style"] = style
            label = _STYLE_LABEL.get(style, style)
            if i > 0:
                vt["title"] = f"{topic.get('title', '')} · {label}"
                vt["topic_id"] = f"{topic.get('topic_id', 'topic')}_v{i}"
            if angles:
                vt["suggested_angles"] = [angles[i % len(angles)]]
            jobs.append(vt)
        return jobs

    def _step(self, agent: str, out: dict, round_idx: int | None = None) -> dict:
        step = {"agent": agent, "output": {k: v for k, v in out.items() if k != "_llm_resp"}}
        if round_idx is not None:
            step["round"] = round_idx
        return step

    async def _assign_experiment(self, session: AsyncSession, content_id: str, ctx: RunContext):
        """若有活跃的 writer 实验，按 content_id 哈希分桶并记录 assignment"""
        try:
            stmt = (select(PromptExperiment).where(
                PromptExperiment.agent == "writer", PromptExperiment.status == "running"))
            exp = (await session.execute(stmt)).scalars().first()
            if not exp:
                return
            # 哈希分桶
            h = int(uuid.UUID(bytes=hashlib.md5(content_id.encode()).digest()[:16]).int)
            variant = "treatment" if (h % 100) < exp.traffic_split.get("treatment", 50) else "control"
            session.add(ExperimentAssignment(
                content_id=content_id, experiment_id=exp.experiment_id, variant=variant))
            await session.flush()
            ctx.log_decision("publisher", f"接入实验{exp.experiment_id}，分桶={variant}",
                             experiment_id=exp.experiment_id, variant=variant)
        except Exception:
            pass  # 实验接入失败不影响发布

    async def _record_bad_case(self, session: AsyncSession, ctx: RunContext,
                               article: dict, review: dict, evidences: list):
        bc = BadCase(
            bad_case_id=f"bc_{uuid.uuid4().hex[:12]}",
            content_id=ctx.task_id, trace_id=ctx.trace_id,
            category_l1="G" if review.get("compliance", {}).get("sensitive_hits") else "Q",
            category_l2="G01" if review.get("compliance", {}).get("sensitive_hits") else "Q03",
            severity="critical" if review.get("compliance", {}).get("sensitive_hits") else "major",
            source="reviewer",
            description=f"verdict={review.get('verdict')}; suggestions={review.get('revision_suggestions')}",
            evidence={"compliance": review.get("compliance"), "fact_check": review.get("fact_check")},
            root_cause=review.get("revision_suggestions", [{}])[0].get("issue", "") if review.get("revision_suggestions") else "",
            affected_prompt_versions=list(ctx.prompt_versions.values()),
            status="open",
        )
        session.add(bc)
        await session.flush()


# 向后兼容：run_topic 里用到的 hashlib
import hashlib


async def run_topic_standalone(topic: dict) -> dict:
    """便捷入口：独立 session 运行单话题"""
    async with async_session() as session:
        result = await WorkflowOrchestrator().run_topic(session, topic)
        await session.commit()
        return result
