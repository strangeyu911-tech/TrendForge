"""Topic Selector Agent — 结合国家策略选题（8步 Workflow 第2步）

输入: {trends, country, max_topics?}
输出: {topics: [{topic_id, title, summary, category, country, language, target_audience, content_style, suggested_angles, why}]}
职责: 从趋势中结合国家内容策略选出最适合目标受众的话题
决策日志: 为什么为该国受众选这些话题
"""
from __future__ import annotations
import hashlib
from config import COUNTRY_STRATEGIES
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class TopicSelectorAgent(BaseAgent):
    name = "topic_selector"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        trends = inputs.get("trends", [])
        country = inputs.get("country", ctx.country)
        strat = COUNTRY_STRATEGIES.get(country, COUNTRY_STRATEGIES["US"])
        max_topics = inputs.get("max_topics", 5)
        prompt = (
            f"你是内容选题官。从以下热点趋势中为【{country}/{strat['label']}】受众选出 {max_topics} 个最适合的话题。\n"
            f"目标受众: {strat['target_audience']}；偏好风格: {strat['content_styles']}；调性: {strat['tone']}\n"
            f"趋势: {trends}\n"
            f"输出 JSON: {{\"topics\": [{{\"title\": str, \"summary\": str, \"category\": str, \"content_style\": str, \"suggested_angles\": [str], \"why\": str}}]}}"
        )
        resp = await ctx.llm.chat(prompt, json_mode=True, temperature=0.4)
        topics = self._parse(resp.text, trends, country, strat, max_topics)
        return {"topics": topics, "_llm_resp": resp,
                "_decision": {"reason": f"为{country}({strat['target_audience']})选出{len(topics)}个话题，调性={strat['tone']}",
                               "details": {"country_strategy": strat["default_style"], "audience": strat["target_audience"]}}}

    def _parse(self, text: str, trends: list, country: str, strat: dict, max_topics: int) -> list[dict]:
        try:
            data = extract_json(text)
            ts = data.get("topics", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            ts = []
        if not ts and trends:
            ts = [{"title": t["title"], "summary": t.get("why", ""), "category": t.get("category", "tech"),
                   "content_style": strat["default_style"], "suggested_angles": ["综合报道"], "why": t.get("why", "")}
                  for t in trends[:max_topics]]
        out = []
        for t in ts[:max_topics]:
            key = hashlib.md5(t.get("title", "").encode()).hexdigest()[:8]
            out.append({
                "topic_id": f"topic_{key}", "title": t.get("title", ""), "summary": t.get("summary", ""),
                "category": t.get("category", "tech"), "country": country, "language": strat["language"],
                "target_audience": strat["target_audience"],
                "content_style": t.get("content_style", strat["default_style"]),
                "suggested_angles": t.get("suggested_angles", []), "heat_score": 7.0,
                "priority": "P1", "why": t.get("why", ""),
            })
        return out

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"topics": [], "_warnings": [f"topic_select_failed:{error}"]}
