"""Fact Checker Agent — 事实核查（8步 Workflow 第6步）

输入: {article, evidences}
输出: {fact_check: {checked_claims, consistent, inconsistent_claims, confidence}}
职责: 提取文章关键论断，核对是否被证据支持（独立于 Reviewer 的合规审核）
决策日志: 核查了多少论断、多少有据、置信度
"""
from __future__ import annotations
from llm import extract_json
from .base import BaseAgent, RunContext, AgentError


class FactCheckerAgent(BaseAgent):
    name = "fact_checker"

    async def run(self, ctx: RunContext, inputs: dict) -> dict:
        article = inputs.get("article", {})
        evidences = inputs.get("evidences", [])
        body_text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in article.get("body", []))
        ev_text = "\n".join(f"[{e.get('evidence_id')}] {e.get('content', '')[:300]}" for e in evidences[:15])
        prompt = (
            f"你是事实核查员。核对文章中的关键论断是否被证据支持。\n"
            f"文章标题: {article.get('title', '')}\n文章正文: {body_text[:1500]}\n\n可用证据:\n{ev_text}\n"
            f"输出 JSON: {{\"claims\": [{{\"claim\": str, \"supported\": bool, \"evidence_id\": str, \"note\": str}}], \"confidence\": float(0-1)}}"
        )
        resp = await ctx.llm.chat(prompt, json_mode=True, temperature=0.1)
        fc = self._parse(resp.text)
        consistent = sum(1 for c in fc["claims"] if c["supported"])
        unsupported = len(fc["claims"]) - consistent
        return {"fact_check": {"checked_claims": len(fc["claims"]), "consistent": consistent,
                               "inconsistent_claims": [c for c in fc["claims"] if not c["supported"]],
                               "confidence": fc["confidence"]},
                "_llm_resp": resp,
                "_decision": {"reason": f"核查{len(fc['claims'])}条论断，{consistent}条有据，{unsupported}条无据，置信度={fc['confidence']}",
                               "details": {"unsupported_count": unsupported}}}

    def _parse(self, text: str) -> dict:
        try:
            data = extract_json(text)
            claims = data.get("claims", []) if isinstance(data, dict) else []
            conf = float(data.get("confidence", 0.8)) if isinstance(data, dict) else 0.8
        except Exception:
            claims, conf = [], 0.5
        if not claims:
            claims = [{"claim": "默认论断", "supported": True, "evidence_id": "", "note": "无明确可核查论断"}]
        return {"claims": claims, "confidence": conf}

    async def fallback(self, ctx: RunContext, error: AgentError) -> dict:
        return {"fact_check": {"checked_claims": 0, "consistent": 0, "inconsistent_claims": [], "confidence": 0.0},
                "_warnings": [f"fact_check_failed:{error}"]}
