"""Publisher Agent — 内容发布、分发策略与灰度（8步 Workflow 第8步）

平台化升级：
- 基于国家策略生成分发计划（推荐平台/内容形态/发布时间）
- 写 Content 表时填充全球化字段 + outline + decision_log
- 接入事件埋点（record_event），打通数据反馈闭环
"""
from __future__ import annotations
import hashlib
from datetime import datetime
from sqlalchemy import select
from models import Content, ContentEvent
from config import settings, COUNTRY_STRATEGIES, DISTRIBUTION_PLATFORMS, CONTENT_FORMATS
from .base import BaseAgent, RunContext, AgentError


class PublisherAgent(BaseAgent):
    name = "publisher"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        article = inputs.get("article", {})
        verdict = inputs.get("review_verdict", "pass")
        review = inputs.get("review", {})
        evidences = inputs.get("evidences", [])
        topic = inputs.get("topic", ctx.topic)
        outline = inputs.get("outline", [])
        prompt_version = inputs.get("prompt_version", ctx.prompt_versions.get("writer", ""))

        if verdict != "pass":
            return {"publish_records": [], "status": "skipped", "reason": f"review verdict={verdict}",
                    "_warnings": [f"not_published:{verdict}"]}

        content_id = self._gen_content_id(ctx)
        # 分发策略：基于国家策略推荐平台/形态/时间
        dist_plan = self._build_distribution_plan(ctx, article)
        primary_platform = dist_plan["primary_platform"]

        # 写 Content 表（含全球化字段 + outline + decision_log）
        content = Content(
            content_id=content_id, status="succeeded", task_id=ctx.task_id, topic_id=topic.get("topic_id", ""),
            title=article.get("title", ""), summary=article.get("summary", ""),
            body=article.get("body", []), tags=article.get("tags", []),
            category=topic.get("category", "tech"), language=ctx.language,
            template_type=inputs.get("template", ctx.content_style),
            word_count=article.get("word_count", 0),
            country=ctx.country, target_audience=ctx.target_audience,
            platform=primary_platform, content_style=ctx.content_style,
            outline=outline, distribution_plan=dist_plan, decision_log=ctx.decision_log,
            prompt_writer_v=prompt_version,
            prompt_planner_v=ctx.prompt_versions.get("topic_selector", ctx.prompt_versions.get("planner", "")),
            prompt_research_v=ctx.prompt_versions.get("research", ""),
            prompt_reviewer_v=ctx.prompt_versions.get("reviewer", ""),
            evidence_count=len(evidences),
            citation_count=len(inputs.get("citations", [])),
            quality_overall=review.get("quality_scores", {}).get("overall", 0.0),
            fact_consistency=self._fact_consistency(review),
            review_verdict=verdict, review_rounds=ctx.review_rounds,
            is_bad_case=review.get("bad_case_flag", False),
            channels=dist_plan["channels"], gray_ratio=settings.gray_initial_ratio,
            published_at=datetime.utcnow(),
        )
        ctx.session.add(content)
        await ctx.session.flush()

        # 灰度发布记录
        records = []
        for ch in dist_plan["channels"]:
            records.append({
                "channel": ch, "content_id": content_id,
                "url": f"https://trendforge.app/{ch}/{content_id}",
                "status": "gray_10pct" if settings.gray_initial_ratio < 1 else "published",
                "published_at": datetime.utcnow().isoformat(),
            })
        gray_status = {
            "current_ratio": settings.gray_initial_ratio,
            "next_action": "observe",
            "observed_ctr": None,
            "observation_minutes": settings.gray_observation_minutes,
        }
        return {
            "publish_records": records, "gray_status": gray_status,
            "content_id": content_id, "distribution_plan": dist_plan,
            "metadata": {"prompt_version": ctx.prompt_versions, "trace_id": ctx.trace_id},
            "_decision": {"reason": f"分发至{ctx.country}的{len(dist_plan['channels'])}个平台，主推={primary_platform}，形态={dist_plan['recommended_format']}",
                          "details": {"country": ctx.country, "platforms": dist_plan["channels"],
                                      "format": dist_plan["recommended_format"]}},
        }

    def _build_distribution_plan(self, ctx: RunContext, article: dict) -> dict:
        """基于国家策略 + 文章特征生成分发计划"""
        strat = COUNTRY_STRATEGIES.get(ctx.country, COUNTRY_STRATEGIES["US"])
        platforms = strat["platforms"]
        # 推荐内容形态：长文→deep_analysis/article；短→news_card/summary
        wc = article.get("word_count", 0)
        if ctx.content_style in ("summary", "brief", "breaking_news") or wc < 300:
            rec_format = "news_card"
        elif ctx.content_style in ("deep_dive", "analysis", "industry_analysis"):
            rec_format = "deep_analysis"
        else:
            rec_format = "article"
        per_platform = []
        for p in platforms:
            pcfg = DISTRIBUTION_PLATFORMS.get(p, {"format": "article", "max_len": 0, "best_hour_local": [9]})
            per_platform.append({
                "platform": p,
                "content_form": self._map_form(pcfg["format"], rec_format),
                "max_len": pcfg["max_len"],
                "best_publish_hour": pcfg["best_hour_local"][0],
                "format": pcfg["format"],
            })
        return {
            "country": ctx.country,
            "target_audience": strat["target_audience"],
            "primary_platform": platforms[0],
            "channels": platforms,
            "recommended_format": rec_format,
            "per_platform": per_platform,
            "tone": strat["tone"],
        }

    def _map_form(self, platform_format: str, rec_format: str) -> str:
        """平台格式 × 推荐形态 → 具体内容形态"""
        if platform_format in ("short_card", "brief_card"):
            return "news_card" if rec_format != "deep_analysis" else "summary"
        if platform_format == "video_script":
            return "short_video_script"
        if platform_format == "visual_card":
            return "commentary"
        return rec_format

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"publish_records": [], "status": "failed", "reason": str(error),
                "_warnings": [f"publish_failed:{error}"]}

    def _gen_content_id(self, ctx: RunContext) -> str:
        return f"c_{hashlib.md5(f'{ctx.trace_id}:{ctx.task_id}'.encode()).hexdigest()[:12]}"

    def _fact_consistency(self, review: dict) -> float:
        fc = review.get("fact_check", {})
        total = fc.get("checked_claims", 0)
        if total == 0:
            return 1.0
        return round(fc.get("consistent", 0) / total, 4)

    async def record_event(self, session, content_id: str, event_type: str, user_id: str = "",
                           channel: str = "", **extra):
        """记录用户行为事件（埋点）— 打通数据反馈闭环"""
        session.add(ContentEvent(
            content_id=content_id, user_id=user_id, event_type=event_type,
            channel=channel, **{k: v for k, v in extra.items()
                                if k in {"position", "read_duration_sec", "action_type",
                                         "country", "language", "platform", "finish_rate",
                                         "like_count", "share_count", "negative_feedback"}},
        ))
        await session.flush()

    async def retract(self, session, content_id: str) -> dict:
        """撤回"""
        c = await session.get(Content, content_id)
        if c:
            c.channels = []
            c.gray_ratio = 0
            c.is_bad_case = True
        return {"content_id": content_id, "status": "retracted",
                "retracted_at": datetime.utcnow().isoformat()}
