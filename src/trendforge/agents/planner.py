"""Planner Agent — 选题策划与任务分配（真实 LLM）"""
from __future__ import annotations
import hashlib
import json
from config import settings
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class PlannerAgent(BaseAgent):
    name = "planner"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        signals = inputs.get("signals", [])
        strategy = inputs.get("strategy", {"categories": ["tech"], "languages": ["zh"], "max_topics": 10})
        # 渲染 Prompt
        prompt = await ctx.pm.render_production(
            ctx.session, "planner", "topic", ctx.language,
            {"signals": signals, "strategy": strategy},
        )
        ctx.prompt_versions["planner"] = await self._prod_version(ctx)
        # 调 LLM
        resp = await ctx.llm.chat(prompt, model=settings.planner_model, json_mode=True, temperature=0.3)
        topics = self._parse(resp.text, signals, strategy)
        return {"topics": topics, "_llm_resp": resp}

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        """降级：基于信号热度规则打分，不调 LLM"""
        signals = ctx.topic.get("_signals", []) if ctx.topic else []
        topics = []
        for sig in signals:
            for item in sig.get("items", [])[:5]:
                topics.append({
                    "topic_id": f"topic_{hashlib.md5(item['title'].encode()).hexdigest()[:8]}",
                    "title": item["title"], "summary": f"来自 {sig['source']}",
                    "category": "tech", "heat_score": round(item.get("heat", 5.0) / 1e6, 2),
                    "suggested_angles": ["技术解析", "行业影响"], "target_languages": ["zh"],
                    "priority": "P0" if item.get("heat", 0) > 5e5 else "P1",
                })
        return {"topics": topics, "_warnings": [f"llm_failed:{error}"]}

    def _parse(self, text: str, signals: list, strategy: dict) -> list[dict]:
        try:
            data = extract_json(text)
            topics = data.get("topics", data) if isinstance(data, dict) else data
        except Exception:
            topics = []
        if not topics and not signals:
            topics = self._builtin_topics()
        seen, deduped = set(), []
        for t in topics[:strategy.get("max_topics", 10)]:
            key = hashlib.md5(t.get("title", "").encode()).hexdigest()[:8]
            if key in seen:
                continue
            seen.add(key)
            t.setdefault("topic_id", f"topic_{key}")
            t.setdefault("priority", "P1")
            t.setdefault("target_languages", ["zh"])
            t.setdefault("heat_score", 5.0)
            deduped.append(t)
        return deduped

    def _builtin_topics(self) -> list[dict]:
        return [{
            "topic_id": "topic_default", "title": "今日热点汇总",
            "summary": "系统默认选题", "category": "tech", "heat_score": 5.0,
            "suggested_angles": ["综合报道"], "target_languages": ["zh"], "priority": "P1",
        }]

    async def _prod_version(self, ctx: RunContext) -> str:
        from sqlalchemy import select
        from models import Prompt
        stmt = select(Prompt).where(Prompt.agent == "planner", Prompt.status == "production", Prompt.language == ctx.language)
        p = (await ctx.session.execute(stmt)).scalars().first()
        return p.version if p else "v1.0.0"
