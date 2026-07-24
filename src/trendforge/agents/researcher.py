"""Research Agent — 热点检索与信息收集（RAG + LLM query 改写）"""
from __future__ import annotations
from config import settings
from rag import get_retriever
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class ResearchAgent(BaseAgent):
    name = "research"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        topic = inputs.get("topic", ctx.topic)
        # 1. LLM 改写 query
        queries = await self._rewrite_queries(ctx, topic)
        # 2. RAG 检索（从 topic 推导过滤条件：分类/语言/时间窗口）
        retriever = get_retriever()
        filters = self._build_filters(topic, ctx.language)
        chunks = retriever.retrieve(queries, top_k=settings.rag_top_k, filters=filters)
        # 3. 转证据集合
        evidences = self._to_evidences(chunks)
        # 4. 冲突检测（简化）
        conflicts = self._detect_conflicts(evidences)
        summary = f"共召回 {len(evidences)} 条证据，覆盖 {len({e['source_name'] for e in evidences})} 个来源"
        if filters:
            summary += f"，过滤={filters}"
        if conflicts:
            summary += f"，{len(conflicts)} 处冲突"
        warnings = []
        if len(evidences) < 5:
            warnings.append("low_evidence")
        ctx.prompt_versions["research"] = "rag-v1.0"
        return {
            "evidences": evidences, "conflicts": conflicts,
            "coverage_summary": summary, "queries": queries, "filters": filters,
            "_warnings": warnings or None,
            "_decision": {"reason": f"检索召回{len(evidences)}条证据，覆盖{len({e['source_name'] for e in evidences})}个来源，过滤={filters}",
                          "details": {"evidence_count": len(evidences),
                                      "sources": list({e["source_name"] for e in evidences})[:5],
                                      "queries": queries}},
        }

    def _build_filters(self, topic: dict, language: str) -> dict:
        """从 topic 推导检索过滤条件"""
        f = {}
        cat = topic.get("category")
        if cat:
            f["category"] = cat
        if language:
            f["language"] = language if language in ("en", "zh") else "en"
        # 默认只看权威+正规媒体（credibility_level ≤ 2），近 30 天
        f["credibility_level_max"] = 2
        f["time_window_hours"] = 24 * 30
        return f

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"evidences": [], "conflicts": [], "coverage_summary": "降级：无证据",
                "_warnings": [f"research_failed:{error}"]}

    async def _rewrite_queries(self, ctx: RunContext, topic: dict) -> list[str]:
        title = topic.get("title", "")
        angles = topic.get("suggested_angles", [])
        prompt = (
            f"你是检索专家。基于话题「{title}」生成 5 个用于新闻检索的 query（中英混合）。\n"
            f"角度建议：{angles}\n输出 JSON 数组：[\"query1\",\"query2\",...]"
        )
        try:
            resp = await ctx.llm.chat(prompt, model=settings.research_model, json_mode=True, temperature=0.2)
            qs = extract_json(resp.text)
            if isinstance(qs, list) and qs:
                return [str(q) for q in qs][:5]
        except Exception:
            pass
        # 兜底：基于标题构造
        queries = [title]
        for a in angles:
            queries.append(f"{title} {a}")
        return queries[:5]

    def _to_evidences(self, chunks: list[dict]) -> list[dict]:
        evs = []
        for i, c in enumerate(chunks):
            evs.append({
                "evidence_id": f"ev_{i+1:03d}",
                "content": c["content"],
                "title": c.get("title", ""),
                "source_url": c.get("source_url", ""),
                "source_name": c.get("source_name", ""),
                "published_at": c.get("published_at", ""),
                "credibility": c.get("credibility", 0.5),
                "credibility_level": c.get("credibility_level", c.get("credibility", 2)),
                "country": c.get("country", ""),
                "language": c.get("language", "en"),
                "category": c.get("category", ""),
                "section_path": c.get("section_path", ""),
                "retrieval_score": round(c.get("final_score", c.get("score", 0.5)), 4),
                "is_conflict": False,
                "entities": c.get("entities", []),
            })
        return evs

    def _detect_conflicts(self, evidences: list[dict]) -> list[dict]:
        # 简化：同来源不同内容标记。真实场景用 LLM 抽断言比对
        return []
