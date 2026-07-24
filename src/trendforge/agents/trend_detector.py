"""Trend Detector Agent — 从知识库检测热点趋势（8步 Workflow 第1步）

输入: {signals?, country?, category?, days?}
输出: {trends: [{trend_id, title, heat_score, category, country, why}]}
职责: 扫描知识库最近新闻 + 外部信号，识别上升热点趋势
决策日志: 为什么选这些热点
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import select
from models import NewsDocument
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class TrendDetectorAgent(BaseAgent):
    name = "trend_detector"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        signals = inputs.get("signals", [])
        country = inputs.get("country", ctx.country)
        category = inputs.get("category")
        # 1. 从知识库取最近文档作为热点原料
        since = datetime.utcnow() - timedelta(days=inputs.get("days", 7))
        stmt = (select(NewsDocument).where(NewsDocument.published_at >= since)
                .order_by(NewsDocument.published_at.desc()).limit(60))
        docs = (await ctx.session.execute(stmt)).scalars().all()
        corpus = [{"title": d.title, "source": d.source_name, "category": d.category, "country": d.country}
                  for d in docs]
        # 2. LLM 聚类出热点趋势
        prompt = (
            f"你是热点分析师。基于以下最近新闻标题（{len(corpus)}篇），识别 5 个正在上升的热点趋势。\n"
            f"目标国家: {country}；分类过滤: {category or '全部'}；外部信号: {signals[:3]}\n"
            f"新闻列表: {corpus[:50]}\n"
            f"输出 JSON: {{\"trends\": [{{\"title\": str, \"heat_score\": float(0-10), \"category\": str, \"country\": str, \"why\": str}}]}}"
        )
        resp = await ctx.llm.chat(prompt, json_mode=True, temperature=0.4)
        trends = self._parse(resp.text, corpus, country)
        return {"trends": trends, "corpus_size": len(corpus), "_llm_resp": resp,
                "_decision": {"reason": f"从{len(corpus)}篇近7天新闻中识别出{len(trends)}个热点趋势",
                               "details": {"top_trend": trends[0]["title"] if trends else "", "country": country}}}

    def _parse(self, text: str, corpus: list, country: str) -> list[dict]:
        try:
            data = extract_json(text)
            ts = data.get("trends", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            ts = []
        if not ts and corpus:
            ts = [{"title": corpus[0]["title"], "heat_score": 6.0, "category": corpus[0]["category"],
                   "country": country, "why": "近7天最新"}]
        out = []
        for i, t in enumerate(ts[:8]):
            out.append({"trend_id": f"trend_{i+1:02d}", "title": t.get("title", ""),
                        "heat_score": float(t.get("heat_score", 5.0)), "category": t.get("category", "tech"),
                        "country": t.get("country", country), "signals": [], "why": t.get("why", "")})
        return out

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"trends": [], "corpus_size": 0, "_warnings": [f"trend_detect_failed:{error}"]}
