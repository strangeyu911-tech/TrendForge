"""Research Agent：热点检索与信息收集（调用 RAG）"""
from __future__ import annotations
import time
from .base import BaseAgent, TaskContext, AgentError
from llm import call_llm
from rag.news_kb import NewsKnowledgeBase
from config import CONFIG


class ResearchAgent(BaseAgent):
    name = "research"
    version = "1.1.0"

    def __init__(self, kb: NewsKnowledgeBase | None = None):
        self.kb = kb or NewsKnowledgeBase()

    async def run(self, ctx: TaskContext, inputs: dict) -> dict:
        t0 = time.time()
        topic = inputs.get("topic", {})
        try:
            # 1. Query 改写（LLM）
            queries = self._rewrite_queries(topic)
            # 2. RAG 检索
            chunks = self.kb.retrieve(queries, top_k=CONFIG.rag_top_k)
            # 3. 转为证据集合
            evidences = self._chunks_to_evidences(chunks)
            # 4. 冲突检测
            conflicts = self._detect_conflicts(evidences)
            # 5. 覆盖统计
            summary = f"共召回 {len(evidences)} 条证据，覆盖 {len({e['source_name'] for e in evidences})} 个来源"
            if conflicts:
                summary += f"，{len(conflicts)} 处冲突"

            warnings = []
            if len(evidences) < 5:
                warnings.append("low_evidence")
            if conflicts:
                warnings.append(f"{len(conflicts)}_conflicts")

            self._record_span(ctx, "degraded" if warnings else "ok", t0, warnings=warnings)
            return {
                "evidences": evidences,
                "conflicts": conflicts,
                "coverage_summary": summary,
                "queries_used": queries,
            }
        except Exception as e:
            self._record_span(ctx, "failed", t0)
            return await self.fallback(ctx, AgentError(self.name, str(e)))

    async def fallback(self, ctx: TaskContext, error: AgentError) -> dict:
        """降级：仅返回知识库中能命中的少量证据"""
        t0 = time.time()
        self._record_span(ctx, "degraded", t0, warnings=["rag_degraded"])
        return {
            "evidences": [],
            "conflicts": [],
            "coverage_summary": "降级：无可用证据",
            "degraded": True,
            "reason": str(error),
        }

    def _rewrite_queries(self, topic: dict) -> list[str]:
        title = topic.get("title", "")
        angles = topic.get("suggested_angles", [])
        # 简单改写（真实场景用 LLM）
        queries = [title]
        for angle in angles:
            queries.append(f"{title} {angle}")
        # 加入实体关键词
        for kw in ["发布", "参数", "性能", "对比", "影响"]:
            queries.append(f"{title} {kw}")
        return queries

    def _chunks_to_evidences(self, chunks: list[dict]) -> list[dict]:
        evidences = []
        for i, c in enumerate(chunks):
            evidences.append({
                "evidence_id": f"ev_{i+1:03d}",
                "content": c["content"],
                "source_url": c.get("source_url", ""),
                "source_name": c.get("source_name", "unknown"),
                "published_at": c.get("published_at", ""),
                "credibility": c.get("credibility", 0.5),
                "language": c.get("language", "zh"),
                "retrieval_score": c.get("score", 0.5),
                "is_conflict": False,
                "entities": c.get("entities", []),
            })
        return evidences

    def _detect_conflicts(self, evidences: list[dict]) -> list[dict]:
        """简化版冲突检测：同一实体不同数值视为冲突"""
        # Demo 中返回空，真实场景用 LLM 抽取断言比对
        return []
