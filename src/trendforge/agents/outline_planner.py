"""Outline Planner Agent — 生成文章大纲（8步 Workflow 第4步）

输入: {topic, evidences, content_style}
输出: {outline: [{section, points, evidence_ids}]}
职责: 基于话题和证据，按内容风格生成结构化大纲（Writer 据此成文）
决策日志: 大纲结构 + 引用了哪些证据
"""
from __future__ import annotations
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class OutlinePlannerAgent(BaseAgent):
    name = "outline_planner"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        topic = inputs.get("topic", ctx.topic)
        evidences = inputs.get("evidences", [])
        style = inputs.get("content_style", ctx.content_style)
        ev_brief = [{"id": e.get("evidence_id"), "t": e.get("title", ""), "src": e.get("source_name", "")}
                    for e in evidences[:20]]
        prompt = (
            f"你是内容架构师。为话题生成大纲，风格={style}，国家={ctx.country}，受众={ctx.target_audience}。\n"
            f"话题: {topic.get('title', '')}\n角度建议: {topic.get('suggested_angles', [])}\n可用证据: {ev_brief}\n"
            f"输出 JSON: {{\"outline\": [{{\"section\": str, \"points\": [str], \"evidence_ids\": [str]}}]}}"
        )
        resp = await ctx.llm.chat(prompt, json_mode=True, temperature=0.3)
        outline = self._parse(resp.text)
        cited = sum(len(s.get("evidence_ids", [])) for s in outline)
        return {"outline": outline, "_llm_resp": resp,
                "_decision": {"reason": f"生成{len(outline)}段大纲，风格={style}，引用{cited}条证据",
                               "details": {"sections": [s.get("section", "") for s in outline]}}}

    def _parse(self, text: str) -> list[dict]:
        try:
            data = extract_json(text)
            ol = data.get("outline", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            ol = []
        if not ol:
            ol = [
                {"section": "概述", "points": ["背景与意义"], "evidence_ids": []},
                {"section": "核心分析", "points": ["关键影响"], "evidence_ids": []},
                {"section": "展望", "points": ["未来趋势"], "evidence_ids": []},
            ]
        return ol

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"outline": [{"section": "概述", "points": [], "evidence_ids": []}],
                "_warnings": [f"outline_failed:{error}"]}
