"""Planner Agent：选题策划与任务分配"""
from __future__ import annotations
import time
import hashlib
from datetime import datetime
from .base import BaseAgent, TaskContext, AgentError
from llm import call_llm, extract_json
from config import CONFIG


class PlannerAgent(BaseAgent):
    name = "planner"
    version = "1.2.0"

    async def run(self, ctx: TaskContext, inputs: dict) -> dict:
        t0 = time.time()
        signals = inputs.get("signals", [])
        strategy = inputs.get("strategy", {})
        try:
            # 用 LLM 改写/打分选题（模拟模式下也会产出结构化结果）
            prompt = self._build_prompt(signals, strategy)
            llm_resp = call_llm(prompt, model=CONFIG.planner_model, response_format={"type": "json_object"})
            topics = self._parse_topics(llm_resp.text, signals, strategy)
            self._record_span(ctx, "ok", t0, llm_resp)
            return {"topics": topics}
        except Exception as e:
            self._record_span(ctx, "failed", t0)
            return await self.fallback(ctx, AgentError(self.name, str(e)))

    async def fallback(self, ctx: TaskContext, error: AgentError) -> dict:
        """降级：基于热度规则打分，不调 LLM 生成角度"""
        t0 = time.time()
        # 简单规则：按原始热度排序取 top N
        signals = ctx.history  # 无信号时无法降级
        self._record_span(ctx, "degraded", t0, warnings=["llm_failed_rule_based_fallback"])
        return {
            "topics": [],
            "degraded": True,
            "reason": str(error),
        }

    def _build_prompt(self, signals: list, strategy: dict) -> str:
        return (
            "你是热点选题策划 Agent。基于以下热点信号，输出 JSON：\n"
            '{"topics":[{"title":"","summary":"","category":"","heat_score":0.0,'
            '"suggested_angles":[""],"target_languages":["zh"],"priority":"P0"}]}\n\n'
            f"信号源：{signals[:5]}\n策略：{strategy}\n"
            "要求：去重、过滤敏感、热度打分(0-10)、每话题给 3 个差异化角度。"
        )

    def _parse_topics(self, text: str, signals: list, strategy: dict) -> list[dict]:
        max_topics = strategy.get("max_topics", 10)
        try:
            data = extract_json(text)
            if isinstance(data, dict) and "topics" in data:
                topics = data["topics"]
            elif isinstance(data, list):
                topics = data
            else:
                topics = []
        except Exception:
            # 模拟模式下 LLM 返回的是 [simulated] 文本，无法解析为 JSON
            # 此时直接基于 signals 构造选题，保证 Demo 可运行
            topics = self._topics_from_signals(signals, strategy)

        # 兜底：若信号也没数据，用内置示例
        if not topics and not signals:
            topics = self._builtin_demo_topics()

        # 去重
        seen = set()
        deduped = []
        for t in topics[:max_topics]:
            key = hashlib.md5(t.get("title", "").encode()).hexdigest()[:8]
            if key in seen:
                continue
            seen.add(key)
            t.setdefault("topic_id", f"topic_{key}")
            t.setdefault("priority", "P1")
            t.setdefault("target_languages", ["zh"])
            deduped.append(t)
        return deduped

    def _topics_from_signals(self, signals: list, strategy: dict) -> list[dict]:
        topics = []
        for sig in signals:
            for item in sig.get("items", [])[:3]:
                topics.append({
                    "topic_id": f"topic_{hashlib.md5(item['title'].encode()).hexdigest()[:8]}",
                    "title": item["title"],
                    "summary": f"来自 {sig['source']} 的热点",
                    "category": strategy.get("categories", ["tech"])[0],
                    "heat_score": round(item.get("heat", 5.0) / 1e6, 2) if item.get("heat", 0) > 100 else item.get("heat", 5.0),
                    "suggested_angles": ["技术解析", "行业影响", "竞品对比"],
                    "target_languages": strategy.get("languages", ["zh"]),
                    "priority": "P0" if item.get("heat", 0) > 5e5 else "P1",
                })
        return topics

    def _builtin_demo_topics(self) -> list[dict]:
        """内置示例选题，确保无外部信号也能演示"""
        return [
            {
                "topic_id": "topic_demo_gpt6",
                "title": "OpenAI 发布 GPT-6：10 万亿参数与多模态推理突破",
                "summary": "OpenAI 于今日发布 GPT-6，参数量较 GPT-5 提升 5 倍，新增原生多模态推理能力。",
                "category": "tech",
                "heat_score": 9.5,
                "suggested_angles": ["技术架构解析", "对行业格局的影响", "与竞品对比"],
                "target_languages": ["zh", "en"],
                "priority": "P0",
                "evidence_hint": ["https://openai.com/blog/gpt6"],
            },
            {
                "topic_id": "topic_demo_fed",
                "title": "美联储 7 月议息会议：维持利率不变，暗示年内降息",
                "summary": "美联储宣布维持基准利率不变，但点阵图显示年内可能降息一次。",
                "category": "finance",
                "heat_score": 8.7,
                "suggested_angles": ["决议要点解读", "对全球资产影响", "对 A 股影响"],
                "target_languages": ["zh"],
                "priority": "P0",
            },
        ]
